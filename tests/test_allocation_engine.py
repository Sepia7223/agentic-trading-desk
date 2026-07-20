from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from trading_desk.allocation.correlation import ReturnSeries, build_correlation_matrix
from trading_desk.allocation.engine import batch_identity, evaluate_batch
from trading_desk.allocation.models import (
    PortfolioCandidate,
    PortfolioConstraints,
    PortfolioDecisionType,
    SizingPolicy,
    StrategyBudget,
    create_state_snapshot,
)
from trading_desk.allocation.ranking import RankingComponents, rank_candidates

NOW = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)


def candidate(identifier: str, *, epic: str = "CS.D.EURUSD.CFD.IP") -> PortfolioCandidate:
    return PortfolioCandidate(
        candidate_id=identifier,
        opportunity_id=f"opp-{identifier}",
        strategy_id="trend-regime-v1",
        strategy_version="1.0.0",
        instrument="EUR/USD",
        epic=epic,
        timeframe="HOUR",
        evaluation_timestamp=NOW,
        completed_bar_timestamp=NOW - timedelta(hours=1),
        gross_expected_value=Decimal("0.002"),
        net_expected_value=Decimal("0.001"),
        signal_confidence=Decimal("0.6"),
        entry_reference=Decimal("1.1000"),
        proposed_stop=Decimal("1.0950"),
        proposed_target=Decimal("1.1100"),
        strategy_fingerprint="a" * 64,
        evidence_fingerprint="b" * 64,
        market_regime="BULL_LOW_VOL",
        correlation_group="usd-majors",
        proposed_risk_distance=Decimal("0.0050"),
        exposure_snapshot_id="exposure-1",
        base_currency="EUR",
        quote_currency="USD",
    )


def components(identifier: str, *, eligible: bool = True) -> RankingComponents:
    return RankingComponents(
        candidate_id=identifier,
        eligible=eligible,
        risk_adjusted_score=Decimal("0.5"),
        regime_fit=Decimal("0.8"),
        diversification_benefit=Decimal("0.5"),
        concentration_penalty=Decimal("0.1"),
    )


def snapshot(**overrides: object):  # type: ignore[no-untyped-def]
    fields: dict[str, object] = {
        "captured_at": NOW,
        "state_complete": True,
        "account_equity": Decimal("10000"),
        "available_capital": Decimal("8000"),
        "daily_realized_pnl": Decimal("0"),
        "daily_unrealized_pnl": Decimal("0"),
        "daily_deployed_capital": Decimal("0"),
        "campaign_drawdown_fraction": Decimal("0"),
        "entries_halted": False,
        "configuration_fingerprint": "c" * 64,
    }
    fields.update(overrides)
    return create_state_snapshot(**fields)


def budget(**overrides: object) -> StrategyBudget:
    fields: dict[str, object] = {
        "strategy_id": "trend-regime-v1",
        "maximum_allocated_capital": Decimal("50000"),
        "maximum_risk_fraction": Decimal("0.01"),
        "maximum_concurrent_positions": 2,
        "maximum_daily_entries": 4,
        "maximum_instrument_concentration": Decimal("0.5"),
        "maximum_correlation_group_concentration": Decimal("0.5"),
        "enabled_policies": (SizingPolicy.FIXED_FRACTIONAL_RISK,),
    }
    fields.update(overrides)
    return StrategyBudget.model_validate(fields)


def run(candidates, comps, snap, **overrides):  # type: ignore[no-untyped-def]
    return evaluate_batch(
        candidates=candidates,
        components=comps,
        snapshot=snap,
        constraints=overrides.pop("constraints", PortfolioConstraints()),
        budgets=overrides.pop("budgets", (budget(),)),
        correlation=overrides.pop("correlation", None),
        decided_at=NOW,
        **overrides,
    )


def test_batch_evaluation_is_deterministic_and_idempotent() -> None:
    candidates = (candidate("cand-b"), candidate("cand-a"))
    comps = (components("cand-b"), components("cand-a"))
    snap = snapshot()
    first = run(candidates, comps, snap)
    second = run(candidates, comps, snap)
    assert [item.decision_id for item in first] == [item.decision_id for item in second]
    assert [item.idempotency_key for item in first] == [item.idempotency_key for item in second]
    assert batch_identity(snap, candidates, PortfolioConstraints()) == first[0].batch_id


def test_accepted_sizing_uses_fractional_risk_and_risk_owns_final_quantity() -> None:
    decisions = run((candidate("cand-1"),), (components("cand-1"),), snapshot())
    decision = decisions[0]
    assert decision.decision is PortfolioDecisionType.ACCEPT
    assert decision.sizing_policy is SizingPolicy.FIXED_FRACTIONAL_RISK
    assert decision.proposed_quantity == Decimal("20000.00")
    assert decision.proposed_capital == Decimal("22000.00")


def test_intra_batch_reservations_defer_later_candidates() -> None:
    constraints = PortfolioConstraints(
        maximum_concurrent_positions=1,
        maximum_total_risk_fraction=Decimal("0.1"),
        maximum_strategy_exposure_fraction=Decimal("10"),
        maximum_correlation_group_exposure_fraction=Decimal("10"),
    )
    candidates = (candidate("cand-1"), candidate("cand-2", epic="CS.D.GBPUSD.CFD.IP"))
    comps = (components("cand-1"), components("cand-2"))
    decisions = run(candidates, comps, snapshot(), constraints=constraints)
    by_id = {item.candidate_id: item for item in decisions}
    accepted = [item for item in decisions if item.decision is PortfolioDecisionType.ACCEPT]
    assert len(accepted) == 1
    deferred = by_id["cand-2"] if accepted[0].candidate_id == "cand-1" else by_id["cand-1"]
    assert deferred.decision is PortfolioDecisionType.DEFER
    assert "PORTFOLIO_CAPACITY_RESERVED" in deferred.reason_codes
    assert deferred.defer_expires_at is not None


def test_incomplete_state_and_halts_fail_closed() -> None:
    for overrides in ({"state_complete": False}, {"entries_halted": True}):
        decisions = run((candidate("cand-1"),), (components("cand-1"),), snapshot(**overrides))
        assert decisions[0].decision is PortfolioDecisionType.REJECT


def test_unknown_correlation_with_holdings_is_conservative() -> None:
    from trading_desk.allocation.models import ConfirmedPositionSummary

    snap = snapshot(
        confirmed_positions=(
            ConfirmedPositionSummary(
                position_id="p1",
                strategy_id="trend-regime-v1",
                epic="CS.D.GBPUSD.CFD.IP",
                correlation_group="usd-majors",
                base_currency="GBP",
                quote_currency="USD",
                quantity=Decimal("1"),
                notional=Decimal("1000"),
                open_risk=Decimal("10"),
            ),
        )
    )
    decisions = run((candidate("cand-1"),), (components("cand-1"),), snap)
    assert decisions[0].decision is PortfolioDecisionType.REJECT
    assert "CORRELATION_EVIDENCE_UNAVAILABLE" in decisions[0].reason_codes


def test_ranking_is_total_and_uses_stable_identifiers() -> None:
    candidates = (candidate("cand-z"), candidate("cand-a"))
    comps = (components("cand-z"), components("cand-a"))
    ranked = rank_candidates(candidates, comps)
    assert [item.candidate.candidate_id for item in ranked] == ["cand-a", "cand-z"]
    assert [item.rank for item in ranked] == [1, 2]


def test_correlation_matrix_marks_insufficient_overlap_unknown() -> None:
    stamps = tuple(f"2026-07-{day:02d}" for day in range(1, 16))
    series = (
        ReturnSeries(
            epic="A",
            timeframe="HOUR",
            bar_timestamps=stamps,
            returns=tuple(Decimal("0.001") * (1 if i % 2 else -1) for i in range(15)),
        ),
        ReturnSeries(
            epic="B",
            timeframe="HOUR",
            bar_timestamps=stamps,
            returns=tuple(Decimal("0.002") * (1 if i % 2 else -1) for i in range(15)),
        ),
        ReturnSeries(
            epic="C", timeframe="HOUR", bar_timestamps=stamps[:3], returns=(Decimal("0.001"),) * 3
        ),
    )
    matrix = build_correlation_matrix(series, lookback=15, minimum_overlap=10)
    known = matrix.lookup("A", "B")
    unknown = matrix.lookup("A", "C")
    assert known is not None and known.known and known.value == Decimal("1.0000")
    assert unknown is not None and not unknown.known
    assert unknown.reason == "INSUFFICIENT_OVERLAP"


def test_kelly_sizing_is_structurally_excluded() -> None:
    with pytest.raises(ValueError, match="research-only"):
        budget(enabled_policies=(SizingPolicy.KELLY_RESEARCH_ONLY,))


def test_allocation_package_has_no_operational_dependencies() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "trading_desk" / "allocation"
    forbidden = re.compile(
        r"from trading_desk\.(ig|execution|lifecycle|journal|api|operations|risk|portfolio)"
        r"|import httpx|import requests"
    )
    for path in root.glob("*.py"):
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith(("import ", "from ")):
                assert not forbidden.search(stripped), f"{path.name}: {stripped}"


def test_state_store_is_idempotent_and_detects_conflicts(tmp_path: Path) -> None:
    from trading_desk.allocation.state import (
        PortfolioStateError,
        PortfolioStateStore,
        create_persisted_batch,
    )

    decisions = run((candidate("cand-1"),), (components("cand-1"),), snapshot())
    batch = create_persisted_batch(
        batch_id=decisions[0].batch_id,
        state_snapshot_id=decisions[0].state_snapshot_id,
        configuration_fingerprint=decisions[0].configuration_fingerprint,
        decisions=decisions,
    )
    store = PortfolioStateStore(tmp_path / "portfolio-state.json")
    assert store.persist(batch) is True
    assert store.persist(batch) is False
    assert len(store.load()) == 1
    assert [item.candidate_id for item in store.open_reservations()] == ["cand-1"]

    forged = batch.model_copy(update={"state_snapshot_id": "f" * 64})
    with pytest.raises(PortfolioStateError):
        store.persist(
            create_persisted_batch(
                batch_id=forged.batch_id,
                state_snapshot_id=forged.state_snapshot_id,
                configuration_fingerprint=forged.configuration_fingerprint,
                decisions=forged.decisions,
            )
        )
