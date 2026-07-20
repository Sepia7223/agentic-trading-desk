"""Rolling-window scorecards and convention-guarded scorecard comparison.

Window scorecards partition closed-trade evidence by explicit, half-open
[start, end) UTC boundaries and score each window independently and
deterministically. Scorecard comparison (the basis for Paper-versus-Demo
reporting) only computes a delta when both sides share the same declared
measure convention; a convention mismatch renders every value delta
unavailable rather than comparing incommensurable numbers.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from trading_desk.analytics.attribution import build_scorecard
from trading_desk.analytics.models import (
    AnalyticsModel,
    Measure,
    MeasureConvention,
    PortfolioScorecard,
    TradeEvidence,
    available,
    unavailable,
)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("window boundaries must be timezone-aware UTC")
    return value.astimezone(UTC)


class WindowBoundary(AnalyticsModel):
    label: str = Field(min_length=1)
    start: datetime
    end: datetime

    @field_validator("start", "end")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.end <= self.start:
            raise ValueError("window end must follow window start")
        return self


class WindowScorecard(AnalyticsModel):
    boundary: WindowBoundary
    scorecard: PortfolioScorecard


def build_window_scorecards(
    trades: tuple[TradeEvidence, ...],
    convention: MeasureConvention,
    boundaries: tuple[WindowBoundary, ...],
) -> tuple[WindowScorecard, ...]:
    """Score each half-open [start, end) window independently and deterministically."""

    ordered = tuple(sorted(boundaries, key=lambda item: (item.start, item.end, item.label)))
    results: list[WindowScorecard] = []
    for boundary in ordered:
        members = tuple(trade for trade in trades if boundary.start <= trade.exit_at < boundary.end)
        results.append(
            WindowScorecard(
                boundary=boundary,
                scorecard=build_scorecard(members, convention),
            )
        )
    return tuple(results)


class MeasureDelta(AnalyticsModel):
    name: str = Field(min_length=1)
    baseline: Measure
    candidate: Measure
    delta: Measure


class ScorecardComparison(AnalyticsModel):
    """Deterministic paper-versus-demo (or any A/B) scorecard comparison."""

    schema_version: Literal["analytics-scorecard-comparison-v1"] = (
        "analytics-scorecard-comparison-v1"
    )
    baseline_id: str = Field(min_length=64, max_length=64)
    candidate_id: str = Field(min_length=64, max_length=64)
    comparable: bool
    reason: str = ""
    deltas: tuple[MeasureDelta, ...]

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if not self.comparable and not self.reason:
            raise ValueError("an incomparable result requires a reason")
        return self


_COMPARED_MEASURES: tuple[str, ...] = (
    "gross_return",
    "net_return",
    "win_rate",
    "payoff_ratio",
    "expectancy",
    "profit_factor",
    "sharpe_like",
    "sortino_like",
    "maximum_drawdown",
    "turnover",
    "exposure_seconds",
    "cost_drag",
)


def _delta(baseline: Measure, candidate: Measure, comparable: bool) -> Measure:
    if not comparable:
        return unavailable("CONVENTION_MISMATCH")
    if not baseline.available:
        return unavailable(f"BASELINE_{baseline.reason}")
    if not candidate.available:
        return unavailable(f"CANDIDATE_{candidate.reason}")
    assert baseline.value is not None and candidate.value is not None
    return available(candidate.value - baseline.value)


def compare_scorecards(
    baseline: PortfolioScorecard, candidate: PortfolioScorecard
) -> ScorecardComparison:
    """Compare two scorecards; value deltas require a matching measure convention."""

    comparable = baseline.convention == candidate.convention
    reason = "" if comparable else "CONVENTION_MISMATCH"
    count_delta = MeasureDelta(
        name="trade_count",
        baseline=available(Decimal(baseline.trade_count)),
        candidate=available(Decimal(candidate.trade_count)),
        delta=(
            available(Decimal(candidate.trade_count - baseline.trade_count))
            if comparable
            else unavailable("CONVENTION_MISMATCH")
        ),
    )
    measure_deltas = tuple(
        MeasureDelta(
            name=name,
            baseline=getattr(baseline, name),
            candidate=getattr(candidate, name),
            delta=_delta(getattr(baseline, name), getattr(candidate, name), comparable),
        )
        for name in _COMPARED_MEASURES
    )
    return ScorecardComparison(
        baseline_id=baseline.scorecard_id,
        candidate_id=candidate.scorecard_id,
        comparable=comparable,
        reason=reason,
        deltas=(count_delta, *measure_deltas),
    )
