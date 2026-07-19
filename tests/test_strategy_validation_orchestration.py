from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from test_strategy_governance import NOW, trade
from trading_desk.strategy.validation import ValidationGates, calculate_metrics, cost_stress
from trading_desk.strategy.validation_orchestration import (
    COST_SENSITIVITY_GATE,
    REGIME_COVERAGE_GATE,
    WALK_FORWARD_CONSISTENCY_GATE,
    StageBoundaries,
    ValidationRunnerError,
    build_walk_forward,
    create_final_test_lock,
    evaluate_extended_gates,
    load_trades,
    read_lock,
    serialize_trades,
    trades_in_range,
    write_lock,
)

BOUNDARIES = StageBoundaries(
    development_start=datetime(2019, 7, 1, tzinfo=UTC),
    development_end=datetime(2021, 12, 31, tzinfo=UTC),
    validation_start=datetime(2022, 1, 1, tzinfo=UTC),
    validation_end=datetime(2025, 6, 30, tzinfo=UTC),
    final_test_start=datetime(2025, 7, 1, tzinfo=UTC),
    final_test_end=datetime(2026, 6, 30, tzinfo=UTC),
    walk_forward_window_count=7,
)


def test_stage_boundaries_reject_disorder() -> None:
    with pytest.raises(ValueError, match="chronological"):
        StageBoundaries(
            development_start=datetime(2022, 1, 1, tzinfo=UTC),
            development_end=datetime(2021, 1, 1, tzinfo=UTC),
            validation_start=datetime(2023, 1, 1, tzinfo=UTC),
            validation_end=datetime(2024, 1, 1, tzinfo=UTC),
            final_test_start=datetime(2024, 6, 1, tzinfo=UTC),
            final_test_end=datetime(2025, 1, 1, tzinfo=UTC),
        )


def test_walk_forward_windows_are_contiguous_and_cover_validation() -> None:
    windows = BOUNDARIES.walk_forward_windows()
    assert len(windows) == 7
    assert windows[0][0] == BOUNDARIES.validation_start
    assert windows[-1][1] == BOUNDARIES.validation_end
    for (_, left_end), (right_start, _) in zip(windows, windows[1:], strict=False):
        assert left_end == right_start


def test_build_walk_forward_assigns_trades_by_entry_time() -> None:
    inside = trade(0, "1").model_copy(
        update={
            "entry_at": datetime(2022, 3, 1, tzinfo=UTC),
            "exit_at": datetime(2022, 3, 2, tzinfo=UTC),
        }
    )
    definitions = build_walk_forward("s", (inside,), BOUNDARIES, "a" * 64)
    assert len(definitions) == 7
    populated = [definition for definition in definitions if definition[4]]
    assert len(populated) == 1
    assert populated[0][4][0].entry_at == inside.entry_at


def test_final_test_lock_round_trip_and_immutability(tmp_path: Path) -> None:
    lock = create_final_test_lock(
        dataset_fingerprint="d" * 64,
        boundaries=BOUNDARIES,
        strategy_ids=("a-strategy",),
        configuration_fingerprints=(("a-strategy", "c" * 64),),
        validation_report_ids=(("a-strategy", "e" * 64),),
        locked_at=NOW,
        locked_by="Sepia7223",
    )
    path = tmp_path / "final_test_lock.json"
    write_lock(lock, path)
    assert read_lock(path) == lock
    with pytest.raises(ValidationRunnerError, match="immutable"):
        write_lock(lock, path)
    missing = tmp_path / "absent.json"
    with pytest.raises(ValidationRunnerError, match="required"):
        read_lock(missing)


def test_extended_gates_flag_cost_sensitivity_and_regime_coverage() -> None:
    profitable = tuple(
        trade(index, "-0.10" if index % 10 == 9 else "0.25").model_copy(
            update={"regime": "BULL_LOW_VOL"}
        )
        for index in range(120)
    )
    metrics = calculate_metrics(profitable)
    failed = evaluate_extended_gates(
        metrics,
        ValidationGates(),
        walk_forward_profitable_fraction=Decimal("1"),
        walk_forward_window_count=7,
        parameter_instability=Decimal("0"),
        cost_results=cost_stress(profitable, "s"),
        trades=profitable,
    )
    assert REGIME_COVERAGE_GATE in failed
    assert COST_SENSITIVITY_GATE not in failed


def test_extended_gates_flag_walk_forward_inconsistency() -> None:
    profitable = tuple(
        trade(index, "0.004").model_copy(
            update={"regime": "BULL_LOW_VOL" if index % 2 else "TRANSITIONAL"}
        )
        for index in range(120)
    )
    metrics = calculate_metrics(profitable)
    failed = evaluate_extended_gates(
        metrics,
        ValidationGates(),
        walk_forward_profitable_fraction=Decimal("0.4"),
        walk_forward_window_count=7,
        parameter_instability=Decimal("0"),
        cost_results=cost_stress(profitable, "s"),
        trades=profitable,
    )
    assert WALK_FORWARD_CONSISTENCY_GATE in failed
    assert REGIME_COVERAGE_GATE not in failed


def test_trades_serialize_round_trip(tmp_path: Path) -> None:
    trades = (trade(0, "1"), trade(1, "-1"))
    path = tmp_path / "trades.jsonl"
    digest = serialize_trades(trades, path)
    assert len(digest) == 64
    assert load_trades(path) == trades


def test_trades_in_range_uses_entry_timestamp() -> None:
    inside = trade(0, "1").model_copy(
        update={
            "entry_at": datetime(2022, 6, 1, tzinfo=UTC),
            "exit_at": datetime(2022, 6, 2, tzinfo=UTC),
        }
    )
    outside = trade(1, "1").model_copy(
        update={
            "entry_at": datetime(2026, 1, 1, tzinfo=UTC),
            "exit_at": datetime(2026, 1, 2, tzinfo=UTC),
        }
    )
    selected = trades_in_range(
        (inside, outside), BOUNDARIES.validation_start, BOUNDARIES.validation_end
    )
    assert selected == (inside,)
