from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from trading_desk.research.grid import SearchSpaceError, expand_grid, neighbor_indices
from trading_desk.research.handoff import HandoffError, build_handoff, write_handoff
from trading_desk.research.models import (
    ExperimentStatus,
    ParameterRange,
    ResourceBudget,
    create_specification,
)
from trading_desk.research.registry import ExperimentRegistry, ResearchRegistryError
from trading_desk.research.runner import run_experiment
from trading_desk.strategy.validation_orchestration import StageBoundaries

NOW = datetime(2026, 7, 19, 6, 0, tzinfo=UTC)
START = datetime(2024, 1, 2, tzinfo=UTC)

BOUNDARIES = StageBoundaries(
    development_start=START + timedelta(hours=100),
    development_end=START + timedelta(hours=400),
    validation_start=START + timedelta(hours=400, seconds=1),
    validation_end=START + timedelta(hours=700),
    final_test_start=START + timedelta(hours=700, seconds=1),
    final_test_end=START + timedelta(hours=900),
    walk_forward_window_count=2,
)


def _write_bars(path: Path, count: int, *, poison_after: int | None = None) -> None:
    header = (
        "epic,timestamp,open_bid,open_ask,high_bid,high_ask,"
        "low_bid,low_ask,close_bid,close_ask,last_traded_volume\n"
    )
    rows = [header]
    for index in range(count):
        stamp = (START + timedelta(hours=index)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
        base = 1.10 + (index % 40) * 0.0002
        if poison_after is not None and index > poison_after:
            base = 9.0 + (index % 5)
        bid = f"{base:.5f}"
        ask = f"{base + 0.0001:.5f}"
        rows.append(
            f"CS.D.EURUSD.CFD.IP,{stamp},{bid},{ask},{bid},{ask},{bid},{ask},{bid},{ask},10\n"
        )
    path.write_text("".join(rows), encoding="utf-8")


def _specification(**overrides: object):
    fields: dict[str, object] = {
        "title": "test experiment",
        "hypothesis": "mechanics test",
        "strategy_family": "trend-pullback-v1",
        "parameter_space": (
            ParameterRange(
                name="minimum_reward_to_risk",
                minimum=Decimal("1.5"),
                maximum=Decimal("2.0"),
                step=Decimal("0.5"),
            ),
        ),
        "dataset_fingerprint": "d" * 64,
        "bars_root_declared": "test-bars",
        "pairs": ("EURUSD",),
        "timeframes": ("HOUR",),
        "boundaries": BOUNDARIES,
        "macro_scoring_included": False,
        "staleness_gates_included": False,
        "budget": ResourceBudget(maximum_trials=8, maximum_wall_clock_seconds=600),
        "created_at": NOW,
        "created_by": "Sepia7223",
    }
    fields.update(overrides)
    return create_specification(**fields)


def _run(tmp_path: Path, specification, *, subdir: str = "run"):  # type: ignore[no-untyped-def]
    root = tmp_path / subdir
    root.mkdir(parents=True, exist_ok=True)
    _write_bars(root / "EURUSD_HOUR.csv", 900)
    registry = ExperimentRegistry(root / "registry.jsonl")
    outcome = run_experiment(
        specification,
        bars_root=root,
        registry=registry,
        cache_root=root / "cache",
        started_at=NOW,
    )
    return outcome, registry


def test_grid_is_bounded_and_deterministic() -> None:
    space = (
        ParameterRange(name="a", minimum=Decimal("1"), maximum=Decimal("3"), step=Decimal("1")),
        ParameterRange(name="b", minimum=Decimal("0"), maximum=Decimal("1"), step=Decimal("1")),
    )
    grid = expand_grid(space, 16)
    assert len(grid) == 6
    assert grid == expand_grid(space, 16)
    with pytest.raises(SearchSpaceError, match="exceeds the frozen budget"):
        expand_grid(space, 5)
    center = grid.index((("a", Decimal("2")), ("b", Decimal("0"))))
    neighbors = neighbor_indices(_specification(parameter_space=space), grid, center)
    assert len(neighbors) == 3


def test_experiment_is_reproducible_and_cache_keys_are_correct(tmp_path: Path) -> None:
    specification = _specification()
    first, _ = _run(tmp_path, specification, subdir="one")
    second, _ = _run(tmp_path, specification, subdir="two")
    assert first.record.trials == second.record.trials
    assert first.cache_hits == 0
    third_root = tmp_path / "one"
    registry = ExperimentRegistry(third_root / "registry2.jsonl")
    third = run_experiment(
        specification,
        bars_root=third_root,
        registry=registry,
        cache_root=third_root / "cache",
        started_at=NOW,
    )
    assert third.cache_hits == len(first.record.trials)
    assert third.record.trials == first.record.trials


def test_final_test_data_is_unavailable_to_optimization(tmp_path: Path) -> None:
    specification = _specification()
    clean, _ = _run(tmp_path, specification, subdir="clean")
    poisoned_root = tmp_path / "poisoned"
    poisoned_root.mkdir()
    _write_bars(poisoned_root / "EURUSD_HOUR.csv", 900, poison_after=701)
    registry = ExperimentRegistry(poisoned_root / "registry.jsonl")
    poisoned = run_experiment(
        specification,
        bars_root=poisoned_root,
        registry=registry,
        cache_root=poisoned_root / "cache",
        started_at=NOW,
    )
    assert poisoned.record.status is ExperimentStatus.COMPLETED
    assert [trial.inner_selection for trial in poisoned.record.trials] == [
        trial.inner_selection for trial in clean.record.trials
    ]
    assert [trial.outer_evaluation for trial in poisoned.record.trials] == [
        trial.outer_evaluation for trial in clean.record.trials
    ]


def test_budget_exhaustion_persists_a_cancelled_record(tmp_path: Path) -> None:
    specification = _specification(
        budget=ResourceBudget(maximum_trials=8, maximum_wall_clock_seconds=0)
    )
    outcome, registry = _run(tmp_path, specification, subdir="cancelled")
    assert outcome.record.status is ExperimentStatus.CANCELLED
    assert "wall-clock" in outcome.record.status_reason
    persisted = registry.load()
    assert persisted[-1].status is ExperimentStatus.CANCELLED


def test_registry_detects_tampering_and_stale_appends(tmp_path: Path) -> None:
    specification = _specification()
    outcome, registry = _run(tmp_path, specification, subdir="tamper")
    with pytest.raises(ResearchRegistryError, match="does not extend"):
        registry.append(outcome.record)
    content = registry.path.read_text(encoding="utf-8")
    registry.path.write_text(content.replace("COMPLETED", "CANCELLED", 1), encoding="utf-8")
    with pytest.raises(ResearchRegistryError):
        registry.load()


def test_no_automatic_promotion_and_handoff_requires_positive_evidence(
    tmp_path: Path,
) -> None:
    outcome, _ = _run(tmp_path, _specification(), subdir="handoff")
    record = outcome.record
    assert "lifecycle" not in type(record).model_fields
    assert record.advisory_statement.startswith("Research output ranks candidates")
    with pytest.raises(HandoffError):
        build_handoff(record, trial_index=0, proposed_version="1.1.0", prepared_by="Sepia7223")


def test_handoff_documents_are_immutable(tmp_path: Path) -> None:
    from trading_desk.research.handoff import create_handoff

    handoff = create_handoff(
        experiment_record_id="a" * 64,
        strategy_family="trend-pullback-v1",
        proposed_version="1.1.0",
        parameters=(("minimum_reward_to_risk", "2.0"),),
        configuration_fingerprint="b" * 64,
        outer_objective_value="0.0001",
        diagnostics_summary=(("trial_count", "4"),),
        prepared_by="Sepia7223",
    )
    assert handoff.proposed_lifecycle_state == "RESEARCH_ONLY"
    target = tmp_path / "handoff.json"
    write_handoff(handoff, target)
    with pytest.raises(HandoffError, match="immutable"):
        write_handoff(handoff, target)


def test_research_package_has_no_operational_dependencies() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "trading_desk" / "research"
    forbidden = re.compile(
        r"from trading_desk\.(ig|execution|lifecycle|portfolio|journal|api|operations|risk)"
        r"|import httpx|import requests"
    )
    for path in root.glob("*.py"):
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith(("import ", "from ")):
                assert not forbidden.search(stripped), (
                    f"forbidden dependency in {path.name}: {stripped}"
                )
