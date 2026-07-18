"""Explicit, non-automatic strategy lifecycle governance."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from trading_desk.context.fingerprints import fingerprint


class StrategyLifecycleState(StrEnum):
    RESEARCH_ONLY = "RESEARCH_ONLY"
    BACKTEST_VALIDATED = "BACKTEST_VALIDATED"
    DEMO_EXPLORATION_ENABLED = "DEMO_EXPLORATION_ENABLED"
    DISABLED = "DISABLED"


class PromotionDecisionType(StrEnum):
    PROMOTE_TO_BACKTEST_VALIDATED = "PROMOTE_TO_BACKTEST_VALIDATED"
    PROMOTE_TO_DEMO_EXPLORATION = "PROMOTE_TO_DEMO_EXPLORATION"
    REMAIN_RESEARCH_ONLY = "REMAIN_RESEARCH_ONLY"
    DISABLE = "DISABLE"


_TRANSITIONS = {
    (StrategyLifecycleState.RESEARCH_ONLY, StrategyLifecycleState.BACKTEST_VALIDATED),
    (StrategyLifecycleState.BACKTEST_VALIDATED, StrategyLifecycleState.DEMO_EXPLORATION_ENABLED),
    (StrategyLifecycleState.DEMO_EXPLORATION_ENABLED, StrategyLifecycleState.DISABLED),
    (StrategyLifecycleState.DEMO_EXPLORATION_ENABLED, StrategyLifecycleState.RESEARCH_ONLY),
}


class PromotionDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    promotion_id: str = Field(min_length=64, max_length=64)
    strategy_id: str
    strategy_version: str
    decision: PromotionDecisionType
    previous_state: StrategyLifecycleState
    new_state: StrategyLifecycleState
    created_at: datetime
    validation_report_id: str
    validation_artifact_fingerprint: str = Field(min_length=64, max_length=64)
    dataset_fingerprint: str = Field(min_length=64, max_length=64)
    configuration_fingerprint: str = Field(min_length=64, max_length=64)
    required_gates: tuple[str, ...]
    observed_metrics: tuple[tuple[str, str], ...]
    failed_gates: tuple[str, ...]
    approver: str
    notes: str = ""

    @field_validator("created_at")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("promotion timestamp must be UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def explicit_and_valid(self) -> Self:
        if (
            self.previous_state != self.new_state
            and (
                self.previous_state,
                self.new_state,
            )
            not in _TRANSITIONS
        ):
            raise ValueError("strategy lifecycle transition is prohibited")
        expected_state = {
            PromotionDecisionType.PROMOTE_TO_BACKTEST_VALIDATED: (
                StrategyLifecycleState.BACKTEST_VALIDATED
            ),
            PromotionDecisionType.PROMOTE_TO_DEMO_EXPLORATION: (
                StrategyLifecycleState.DEMO_EXPLORATION_ENABLED
            ),
            PromotionDecisionType.REMAIN_RESEARCH_ONLY: StrategyLifecycleState.RESEARCH_ONLY,
            PromotionDecisionType.DISABLE: StrategyLifecycleState.DISABLED,
        }[self.decision]
        if self.new_state is not expected_state:
            raise ValueError("promotion decision does not match the requested lifecycle state")
        if (
            self.decision
            in {
                PromotionDecisionType.PROMOTE_TO_BACKTEST_VALIDATED,
                PromotionDecisionType.PROMOTE_TO_DEMO_EXPLORATION,
            }
            and self.failed_gates
        ):
            raise ValueError("failed validation gates prohibit promotion")
        expected = fingerprint(self.model_dump(mode="python", exclude={"promotion_id"}))
        if self.promotion_id != expected:
            raise ValueError("promotion decision fingerprint mismatch")
        return self


def promotion_decision(**values: object) -> PromotionDecision:
    fields = dict(values)
    fields.setdefault("notes", "")
    return PromotionDecision.model_validate({**fields, "promotion_id": fingerprint(fields)})
