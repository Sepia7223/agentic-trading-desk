"""Common deterministic contract for cutoff-safe strategy evaluators."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from trading_desk.context.fingerprints import fingerprint
from trading_desk.context.models import ContextTimeframe, MarketContextSnapshot
from trading_desk.strategy.models import StrategyMarketData


class PortfolioStrategyModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


class StrategyDecision(StrEnum):
    CANDIDATE = "CANDIDATE"
    REJECT = "REJECT"
    INELIGIBLE_REGIME = "INELIGIBLE_REGIME"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    STALE_DATA = "STALE_DATA"


class StrategyDirection(StrEnum):
    LONG = "LONG"


class StrategyEvaluationContext(PortfolioStrategyModel):
    evaluation_id: str = Field(min_length=64, max_length=64)
    evaluation_timestamp: datetime
    instrument_id: str
    epic: str
    timeframe: ContextTimeframe
    completed_bar_timestamp: datetime
    market_data: StrategyMarketData
    higher_timeframe_data: StrategyMarketData | None = None
    market_context: MarketContextSnapshot
    existing_position: bool | None = False
    strategy_configuration_fingerprint: str = Field(min_length=64, max_length=64)

    @field_validator("evaluation_timestamp", "completed_bar_timestamp")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("strategy evaluation timestamps must be UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def cutoff_safe(self) -> Self:
        if self.epic != self.market_data.epic or self.epic != self.market_context.epic:
            raise ValueError("strategy context instrument mismatch")
        if self.completed_bar_timestamp > self.evaluation_timestamp:
            raise ValueError("evaluation cutoff cannot be in the future")
        if not self.market_data.timestamps:
            raise ValueError("strategy context requires market history")
        if self.market_data.timestamps[-1] != self.completed_bar_timestamp:
            raise ValueError("market data must end at the completed-bar cutoff")
        if any(item > self.completed_bar_timestamp for item in self.market_data.timestamps):
            raise ValueError("future lower-timeframe data is prohibited")
        if self.market_context.data_cutoff_timestamp > self.completed_bar_timestamp:
            raise ValueError("future market context is prohibited")
        if self.higher_timeframe_data is not None and any(
            item > self.completed_bar_timestamp for item in self.higher_timeframe_data.timestamps
        ):
            raise ValueError("incomplete higher-timeframe bars are prohibited")
        expected = fingerprint(self.model_dump(mode="python", exclude={"evaluation_id"}))
        if self.evaluation_id != expected:
            raise ValueError("strategy evaluation identity mismatch")
        return self


class StrategyEvidence(PortfolioStrategyModel):
    name: str
    value: Decimal | str | bool
    threshold: Decimal | str | bool | None = None
    passed: bool | None = None


class StrategyEvaluationResult(PortfolioStrategyModel):
    result_id: str = Field(min_length=64, max_length=64)
    evaluation_id: str
    strategy_id: str
    strategy_version: str
    strategy_fingerprint: str = Field(min_length=64, max_length=64)
    instrument_id: str
    epic: str
    timeframe: ContextTimeframe
    evaluation_timestamp: datetime
    decision: StrategyDecision
    direction: StrategyDirection | None = None
    signal_strength: Decimal = Field(ge=0, le=1)
    signal_confidence: Decimal = Field(ge=0, le=1)
    entry_reference: Decimal | None = Field(default=None, gt=0)
    proposed_stop: Decimal | None = Field(default=None, gt=0)
    proposed_target: Decimal | None = Field(default=None, gt=0)
    expected_holding_period: timedelta | None = None
    estimated_win_probability: Decimal | None = Field(default=None, ge=0, le=1)
    estimated_average_gain: Decimal | None = Field(default=None, gt=0)
    estimated_average_loss: Decimal | None = Field(default=None, gt=0)
    gross_expected_value: Decimal | None = None
    invalidation_conditions: tuple[str, ...] = ()
    evidence: tuple[StrategyEvidence, ...] = ()
    rejection_reasons: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_candidate(self) -> Self:
        fields = self.model_dump(mode="python", exclude={"result_id"})
        if self.result_id != fingerprint(fields):
            raise ValueError("strategy result fingerprint mismatch")
        if self.decision is StrategyDecision.CANDIDATE:
            required = (
                self.direction,
                self.entry_reference,
                self.proposed_stop,
                self.proposed_target,
                self.expected_holding_period,
                self.estimated_win_probability,
                self.estimated_average_gain,
                self.estimated_average_loss,
                self.gross_expected_value,
            )
            if any(item is None for item in required):
                raise ValueError("candidate result is incomplete")
            assert self.entry_reference and self.proposed_stop and self.proposed_target
            if not self.proposed_stop < self.entry_reference < self.proposed_target:
                raise ValueError("long candidate price structure is invalid")
            if self.direction is not StrategyDirection.LONG:
                raise ValueError("Milestone 12 is long-only")
            if self.rejection_reasons:
                raise ValueError("candidate cannot contain rejection reasons")
        elif self.direction is not None:
            raise ValueError("non-candidates cannot imply a trading direction")
        return self


class StrategyEvaluator(Protocol):
    strategy_id: str
    strategy_version: str
    strategy_fingerprint: str

    def evaluate(self, *, context: StrategyEvaluationContext) -> StrategyEvaluationResult: ...


def evaluation_context(**values: object) -> StrategyEvaluationContext:
    fields = dict(values)
    identity = fingerprint(fields)
    return StrategyEvaluationContext.model_validate({**fields, "evaluation_id": identity})


def strategy_result(**values: object) -> StrategyEvaluationResult:
    fields = dict(values)
    defaults: dict[str, object] = {
        "direction": None,
        "entry_reference": None,
        "proposed_stop": None,
        "proposed_target": None,
        "expected_holding_period": None,
        "estimated_win_probability": None,
        "estimated_average_gain": None,
        "estimated_average_loss": None,
        "gross_expected_value": None,
        "invalidation_conditions": (),
        "evidence": (),
        "rejection_reasons": (),
    }
    for name, value in defaults.items():
        fields.setdefault(name, value)
    return StrategyEvaluationResult.model_validate({**fields, "result_id": fingerprint(fields)})
