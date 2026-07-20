"""Immutable contracts for deterministic portfolio analytics.

Analytics is read-only: every metric traces to immutable source records via
explicit lineage identifiers, declared conventions travel with every result,
and missing evidence produces an explicitly unavailable metric — never a
fabricated value. Nothing in this package can change allocations, strategy
states, Risk policy, execution, lifecycle, campaign state, or broker data.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from trading_desk.context.fingerprints import fingerprint


class AnalyticsModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("analytics timestamps must be timezone-aware UTC")
    return value.astimezone(UTC)


class MeasureConvention(AnalyticsModel):
    """Declared calculation conventions carried by every analytics result."""

    schema_version: Literal["analytics-convention-v1"] = "analytics-convention-v1"
    reporting_currency: str = Field(default="USD", min_length=3, max_length=3)
    returns_definition: Literal["fraction_of_entry_notional", "account_currency_realized_pnl"] = (
        "fraction_of_entry_notional"
    )
    risk_ratio_definition: Literal["per_trade_mean_over_population_stddev"] = (
        "per_trade_mean_over_population_stddev"
    )
    downside_definition: Literal["losses_only_population_stddev"] = "losses_only_population_stddev"
    timezone: Literal["UTC"] = "UTC"

    @property
    def fingerprint(self) -> str:
        return fingerprint(self)


class Measure(AnalyticsModel):
    """One metric that is either available with a value or explicitly not."""

    available: bool
    value: Decimal | None = None
    reason: str = ""

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if self.available and self.value is None:
            raise ValueError("available measures require a value")
        if not self.available and self.value is not None:
            raise ValueError("unavailable measures cannot carry a value")
        if not self.available and not self.reason:
            raise ValueError("unavailable measures require a reason")
        return self


def available(value: Decimal) -> Measure:
    return Measure(available=True, value=value.quantize(Decimal("0.00000001")))


def unavailable(reason: str) -> Measure:
    return Measure(available=False, reason=reason)


class TradeEvidence(AnalyticsModel):
    """One closed trade traced to its immutable source records."""

    schema_version: Literal["analytics-trade-evidence-v1"] = "analytics-trade-evidence-v1"
    trade_id: str = Field(min_length=1)
    source_record_ids: tuple[str, ...] = Field(min_length=1)
    strategy_id: str = Field(min_length=1)
    instrument: str = Field(min_length=1)
    timeframe: str = Field(min_length=1)
    regime: str = Field(min_length=1)
    exit_reason: str = Field(min_length=1)
    currency: str = Field(min_length=3, max_length=3)
    entry_at: datetime
    exit_at: datetime
    gross_return: Decimal
    spread_cost: Decimal = Field(ge=0)
    slippage_cost: Decimal = Field(ge=0)
    commission_cost: Decimal = Field(ge=0)
    funding_cost: Decimal = Field(ge=0)
    turnover: Decimal = Field(ge=0)

    @field_validator("entry_at", "exit_at")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def chronological(self) -> Self:
        if self.exit_at <= self.entry_at:
            raise ValueError("trade exit must follow entry")
        return self

    @property
    def total_cost(self) -> Decimal:
        return self.spread_cost + self.slippage_cost + self.commission_cost + self.funding_cost

    @property
    def net_return(self) -> Decimal:
        return self.gross_return - self.total_cost


class DimensionName(StrEnum):
    STRATEGY = "STRATEGY"
    INSTRUMENT = "INSTRUMENT"
    TIMEFRAME = "TIMEFRAME"
    REGIME = "REGIME"
    EXIT_REASON = "EXIT_REASON"


class DimensionSlice(AnalyticsModel):
    dimension: DimensionName
    key: str
    trade_count: int = Field(ge=0)
    gross_return: Decimal
    net_return: Decimal
    total_cost: Decimal


class CostDecomposition(AnalyticsModel):
    spread: Decimal = Field(ge=0)
    slippage: Decimal = Field(ge=0)
    commission: Decimal = Field(ge=0)
    funding: Decimal = Field(ge=0)

    @property
    def total(self) -> Decimal:
        return self.spread + self.slippage + self.commission + self.funding


class PortfolioScorecard(AnalyticsModel):
    """Deterministic, fingerprinted, lineage-bound analytics result."""

    schema_version: Literal["analytics-scorecard-v1"] = "analytics-scorecard-v1"
    scorecard_id: str = Field(min_length=64, max_length=64)
    convention: MeasureConvention
    input_start: datetime | None
    input_end: datetime | None
    trade_count: int = Field(ge=0)
    source_record_count: int = Field(ge=0)
    gross_return: Measure
    net_return: Measure
    win_rate: Measure
    payoff_ratio: Measure
    expectancy: Measure
    profit_factor: Measure
    sharpe_like: Measure
    sortino_like: Measure
    maximum_drawdown: Measure
    recovery_duration_trades: Measure
    turnover: Measure
    exposure_seconds: Measure
    cost_drag: Measure
    costs: CostDecomposition
    attribution: tuple[DimensionSlice, ...]
    reconciled: bool

    @model_validator(mode="after")
    def identity(self) -> Self:
        expected = fingerprint(self.model_dump(mode="python", exclude={"scorecard_id"}))
        if self.scorecard_id != expected:
            raise ValueError("scorecard fingerprint mismatch")
        return self


def create_scorecard(**values: object) -> PortfolioScorecard:
    draft_fields = {**values, "scorecard_id": "0" * 64}
    draft = PortfolioScorecard.model_construct(**draft_fields)  # type: ignore[arg-type]
    fields = draft.model_dump(mode="python", exclude={"scorecard_id"})
    return PortfolioScorecard.model_validate({**fields, "scorecard_id": fingerprint(fields)})
