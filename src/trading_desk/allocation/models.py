"""Immutable contracts for portfolio construction and capital allocation.

The portfolio layer ranks and sizes candidate opportunities against one
authoritative state snapshot. It proposes capital and quantity only: Risk
remains the final approval and quantity authority, controlled execution
remains the sole broker mutation authority, and lifecycle remains the sole
close authority. The portfolio layer cannot activate strategies, change
signals, or touch broker state.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from trading_desk.context.fingerprints import fingerprint


class AllocationModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("allocation timestamps must be timezone-aware UTC")
    return value.astimezone(UTC)


class PortfolioDecisionType(StrEnum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    DEFER = "DEFER"


class SizingPolicy(StrEnum):
    FIXED_CAPITAL = "FIXED_CAPITAL"
    FIXED_FRACTIONAL_RISK = "FIXED_FRACTIONAL_RISK"
    VOLATILITY_TARGET = "VOLATILITY_TARGET"
    KELLY_RESEARCH_ONLY = "KELLY_RESEARCH_ONLY"


DEMO_ELIGIBLE_POLICIES = frozenset(
    {
        SizingPolicy.FIXED_CAPITAL,
        SizingPolicy.FIXED_FRACTIONAL_RISK,
        SizingPolicy.VOLATILITY_TARGET,
    }
)


class PortfolioCandidate(AllocationModel):
    """Immutable, cutoff-safe input contract from the opportunity layer."""

    schema_version: Literal["portfolio-candidate-v1"] = "portfolio-candidate-v1"
    candidate_id: str = Field(min_length=1, max_length=128)
    opportunity_id: str = Field(min_length=1, max_length=128)
    strategy_id: str = Field(min_length=1)
    strategy_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    instrument: str = Field(min_length=1)
    epic: str = Field(min_length=1)
    direction: Literal["LONG"] = "LONG"
    timeframe: str = Field(min_length=1)
    evaluation_timestamp: datetime
    completed_bar_timestamp: datetime
    gross_expected_value: Decimal
    net_expected_value: Decimal
    signal_confidence: Decimal = Field(ge=0, le=1)
    entry_reference: Decimal = Field(gt=0)
    proposed_stop: Decimal = Field(gt=0)
    proposed_target: Decimal | None = Field(default=None, gt=0)
    strategy_fingerprint: str = Field(min_length=64, max_length=64)
    evidence_fingerprint: str = Field(min_length=64, max_length=64)
    market_regime: str = Field(min_length=1)
    correlation_group: str = Field(min_length=1)
    proposed_risk_distance: Decimal = Field(gt=0)
    exposure_snapshot_id: str = Field(min_length=1)
    base_currency: str = Field(min_length=3, max_length=3)
    quote_currency: str = Field(min_length=3, max_length=3)

    @field_validator("evaluation_timestamp", "completed_bar_timestamp")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def cutoff_safe(self) -> Self:
        if self.completed_bar_timestamp > self.evaluation_timestamp:
            raise ValueError("candidate cutoff cannot be in the future")
        if self.proposed_stop >= self.entry_reference:
            raise ValueError("long candidate stop must sit below entry")
        return self


class ConfirmedPositionSummary(AllocationModel):
    position_id: str = Field(min_length=1)
    strategy_id: str = Field(min_length=1)
    epic: str = Field(min_length=1)
    correlation_group: str = Field(min_length=1)
    base_currency: str = Field(min_length=3, max_length=3)
    quote_currency: str = Field(min_length=3, max_length=3)
    quantity: Decimal = Field(gt=0)
    notional: Decimal = Field(gt=0)
    open_risk: Decimal = Field(ge=0)


class PendingReservation(AllocationModel):
    """Capital and risk reserved by unresolved or ambiguous submissions."""

    reservation_id: str = Field(min_length=1)
    strategy_id: str = Field(min_length=1)
    epic: str = Field(min_length=1)
    correlation_group: str = Field(min_length=1)
    reserved_capital: Decimal = Field(ge=0)
    reserved_risk: Decimal = Field(ge=0)
    ambiguous: bool


class PortfolioStateSnapshot(AllocationModel):
    """Authoritative state used by exactly one evaluation batch.

    Unknown or stale state fails closed for new entries while protective
    monitoring continues elsewhere; the portfolio layer never guesses.
    """

    schema_version: Literal["portfolio-state-v1"] = "portfolio-state-v1"
    snapshot_id: str = Field(min_length=64, max_length=64)
    captured_at: datetime
    state_complete: bool
    account_equity: Decimal = Field(gt=0)
    available_capital: Decimal = Field(ge=0)
    confirmed_positions: tuple[ConfirmedPositionSummary, ...] = ()
    pending_reservations: tuple[PendingReservation, ...] = ()
    strategy_allocated_capital: tuple[tuple[str, Decimal], ...] = ()
    strategy_daily_entries: tuple[tuple[str, int], ...] = ()
    instrument_exposure: tuple[tuple[str, Decimal], ...] = ()
    correlation_group_exposure: tuple[tuple[str, Decimal], ...] = ()
    currency_long_exposure: tuple[tuple[str, Decimal], ...] = ()
    currency_short_exposure: tuple[tuple[str, Decimal], ...] = ()
    daily_realized_pnl: Decimal
    daily_unrealized_pnl: Decimal
    daily_deployed_capital: Decimal = Field(ge=0)
    campaign_drawdown_fraction: Decimal = Field(ge=0)
    entries_halted: bool
    recent_close_cooldowns: tuple[tuple[str, datetime], ...] = ()
    configuration_fingerprint: str = Field(min_length=64, max_length=64)

    @field_validator("captured_at")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def identity(self) -> Self:
        expected = fingerprint(self.model_dump(mode="python", exclude={"snapshot_id"}))
        if self.snapshot_id != expected:
            raise ValueError("portfolio state snapshot fingerprint mismatch")
        return self


class StrategyBudget(AllocationModel):
    """Immutable per-strategy allocation bounds; never a promotion device."""

    strategy_id: str = Field(min_length=1)
    maximum_allocated_capital: Decimal = Field(gt=0)
    fixed_capital_amount: Decimal = Field(default=Decimal("1000"), gt=0)
    maximum_risk_fraction: Decimal = Field(gt=0, le=Decimal("0.05"))
    maximum_concurrent_positions: int = Field(ge=1, le=10)
    maximum_daily_entries: int = Field(ge=1, le=20)
    maximum_instrument_concentration: Decimal = Field(gt=0, le=1)
    maximum_correlation_group_concentration: Decimal = Field(gt=0, le=1)
    enabled_policies: tuple[SizingPolicy, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def demo_policies_only(self) -> Self:
        if SizingPolicy.KELLY_RESEARCH_ONLY in self.enabled_policies:
            raise ValueError("Kelly sizing is research-only and cannot be enabled")
        return self


class PortfolioConstraints(AllocationModel):
    """Portfolio-wide immutable limits applied to every batch."""

    schema_version: Literal["portfolio-constraints-v1"] = "portfolio-constraints-v1"
    maximum_total_risk_fraction: Decimal = Field(default=Decimal("0.02"), gt=0, le=Decimal("0.1"))
    maximum_concurrent_positions: int = Field(default=3, ge=1, le=10)
    margin_factor: Decimal = Field(default=Decimal("0.05"), gt=0, le=1)
    maximum_instrument_exposure_fraction: Decimal = Field(
        default=Decimal("2.5"), gt=0, le=Decimal("10")
    )
    maximum_strategy_exposure_fraction: Decimal = Field(
        default=Decimal("3"), gt=0, le=Decimal("10")
    )
    maximum_correlation_group_exposure_fraction: Decimal = Field(
        default=Decimal("4"), gt=0, le=Decimal("10")
    )
    maximum_currency_long_fraction: Decimal = Field(default=Decimal("5"), gt=0, le=Decimal("10"))
    maximum_currency_short_fraction: Decimal = Field(default=Decimal("5"), gt=0, le=Decimal("10"))
    maximum_daily_capital_fraction: Decimal = Field(default=Decimal("0.5"), gt=0, le=1)
    correlation_rejection_threshold: Decimal = Field(default=Decimal("0.85"), gt=0, le=1)
    correlation_penalty_threshold: Decimal = Field(default=Decimal("0.6"), gt=0, le=1)
    recent_close_cooldown_seconds: int = Field(default=3600, ge=0)
    defer_validity_seconds: int = Field(default=900, ge=60)
    volatility_target_fraction: Decimal = Field(default=Decimal("0.002"), gt=0, le=Decimal("0.01"))
    live_trading_enabled: Literal[False] = False

    @property
    def fingerprint(self) -> str:
        return fingerprint(self)

    @model_validator(mode="after")
    def ordered_correlation_thresholds(self) -> Self:
        if self.correlation_penalty_threshold >= self.correlation_rejection_threshold:
            raise ValueError("penalty threshold must sit below the rejection threshold")
        return self


class PortfolioDecision(AllocationModel):
    """Durable decision for exactly one candidate within one batch."""

    schema_version: Literal["portfolio-decision-v1"] = "portfolio-decision-v1"
    decision_id: str = Field(min_length=64, max_length=64)
    idempotency_key: str = Field(min_length=64, max_length=64)
    batch_id: str = Field(min_length=64, max_length=64)
    candidate_id: str = Field(min_length=1)
    decision: PortfolioDecisionType
    rank: int = Field(ge=1)
    proposed_capital: Decimal | None = Field(default=None, gt=0)
    proposed_quantity: Decimal | None = Field(default=None, gt=0)
    sizing_policy: SizingPolicy | None = None
    binding_constraints: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    correlation_value: Decimal | None = Field(default=None, ge=-1, le=1)
    concentration_value: Decimal | None = Field(default=None, ge=0)
    candidate_fingerprint: str = Field(min_length=64, max_length=64)
    state_snapshot_id: str = Field(min_length=64, max_length=64)
    configuration_fingerprint: str = Field(min_length=64, max_length=64)
    decided_at: datetime
    defer_expires_at: datetime | None = None

    @field_validator("decided_at")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if self.decision is PortfolioDecisionType.ACCEPT:
            if (
                self.proposed_capital is None
                or self.proposed_quantity is None
                or self.sizing_policy is None
            ):
                raise ValueError("accepted decisions require a complete sizing proposal")
            if self.sizing_policy not in DEMO_ELIGIBLE_POLICIES:
                raise ValueError("research-only sizing cannot reach an accepted decision")
        else:
            if self.proposed_capital is not None or self.proposed_quantity is not None:
                raise ValueError("only accepted decisions carry sizing proposals")
            if not self.reason_codes:
                raise ValueError("rejections and deferrals require reason codes")
        if self.decision is PortfolioDecisionType.DEFER:
            if self.defer_expires_at is None:
                raise ValueError("deferred decisions require an expiry boundary")
            if _utc(self.defer_expires_at) <= self.decided_at:
                raise ValueError("deferral expiry must follow the decision time")
        elif self.defer_expires_at is not None:
            raise ValueError("only deferrals carry an expiry boundary")
        expected = fingerprint(self.model_dump(mode="python", exclude={"decision_id"}))
        if self.decision_id != expected:
            raise ValueError("portfolio decision fingerprint mismatch")
        return self


def create_state_snapshot(**values: object) -> PortfolioStateSnapshot:
    draft_fields = {**values, "snapshot_id": "0" * 64}
    draft = PortfolioStateSnapshot.model_construct(**draft_fields)  # type: ignore[arg-type]
    fields = draft.model_dump(mode="python", exclude={"snapshot_id"})
    return PortfolioStateSnapshot.model_validate({**fields, "snapshot_id": fingerprint(fields)})


def create_decision(**values: object) -> PortfolioDecision:
    draft_fields = {**values, "decision_id": "0" * 64}
    draft = PortfolioDecision.model_construct(**draft_fields)  # type: ignore[arg-type]
    fields = draft.model_dump(mode="python", exclude={"decision_id"})
    return PortfolioDecision.model_validate({**fields, "decision_id": fingerprint(fields)})
