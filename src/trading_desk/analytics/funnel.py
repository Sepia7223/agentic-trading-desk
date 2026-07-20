"""Opportunity funnel and hindsight-free counterfactual reporting.

The funnel counts a candidate's progress from discovery through close and the
reasons candidates leave the pipeline. Counterfactual reporting is deliberately
constrained to frozen evidence: it reports how many candidates were rejected
and why, but never estimates what a rejected candidate *would* have returned —
that path was not taken and no immutable record carries its outcome, so the
foregone result is explicitly unavailable rather than fabricated with hindsight.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, model_validator

from trading_desk.analytics.models import (
    AnalyticsModel,
    Measure,
    available,
    unavailable,
)
from trading_desk.context.fingerprints import fingerprint


class FunnelStage(StrEnum):
    DISCOVERED = "DISCOVERED"
    EVALUATED = "EVALUATED"
    SELECTED = "SELECTED"
    EXECUTION_APPROVED = "EXECUTION_APPROVED"
    EXECUTED = "EXECUTED"
    CLOSED = "CLOSED"


_STAGE_ORDER: tuple[FunnelStage, ...] = (
    FunnelStage.DISCOVERED,
    FunnelStage.EVALUATED,
    FunnelStage.SELECTED,
    FunnelStage.EXECUTION_APPROVED,
    FunnelStage.EXECUTED,
    FunnelStage.CLOSED,
)


class RejectionTally(AnalyticsModel):
    reason: str = Field(min_length=1)
    count: int = Field(ge=0)


class FunnelTally(AnalyticsModel):
    """Frozen per-stage candidate counts drawn from immutable journal records."""

    schema_version: Literal["analytics-funnel-tally-v1"] = "analytics-funnel-tally-v1"
    discovered: int = Field(ge=0)
    evaluated: int = Field(ge=0)
    selected: int = Field(ge=0)
    execution_approved: int = Field(ge=0)
    executed: int = Field(ge=0)
    closed: int = Field(ge=0)
    rejections: tuple[RejectionTally, ...] = ()
    system_halts: int = Field(default=0, ge=0)

    def count(self, stage: FunnelStage) -> int:
        return {
            FunnelStage.DISCOVERED: self.discovered,
            FunnelStage.EVALUATED: self.evaluated,
            FunnelStage.SELECTED: self.selected,
            FunnelStage.EXECUTION_APPROVED: self.execution_approved,
            FunnelStage.EXECUTED: self.executed,
            FunnelStage.CLOSED: self.closed,
        }[stage]


class StageCount(AnalyticsModel):
    stage: FunnelStage
    count: int = Field(ge=0)


class StageConversion(AnalyticsModel):
    from_stage: FunnelStage
    to_stage: FunnelStage
    rate: Measure


class Counterfactual(AnalyticsModel):
    """Accepted-versus-rejected, reported without hindsight on the paths not taken."""

    accepted: int = Field(ge=0)
    rejected: int = Field(ge=0)
    rejections: tuple[RejectionTally, ...]
    foregone_outcome: Measure


class OpportunityFunnel(AnalyticsModel):
    schema_version: Literal["analytics-opportunity-funnel-v1"] = "analytics-opportunity-funnel-v1"
    funnel_id: str = Field(min_length=64, max_length=64)
    stages: tuple[StageCount, ...]
    conversions: tuple[StageConversion, ...]
    overall_conversion: Measure
    system_halts: int = Field(ge=0)
    counterfactual: Counterfactual

    @model_validator(mode="after")
    def identity(self) -> Self:
        expected = fingerprint(self.model_dump(mode="python", exclude={"funnel_id"}))
        if self.funnel_id != expected:
            raise ValueError("opportunity funnel fingerprint mismatch")
        return self


def _rate(numerator: int, denominator: int) -> Measure:
    if denominator == 0:
        return unavailable("NO_UPSTREAM_CANDIDATES")
    return available(Decimal(numerator) / Decimal(denominator))


def build_funnel(tally: FunnelTally) -> OpportunityFunnel:
    """Deterministic opportunity funnel with hindsight-free counterfactuals."""

    stages = tuple(StageCount(stage=stage, count=tally.count(stage)) for stage in _STAGE_ORDER)
    conversions = tuple(
        StageConversion(
            from_stage=upstream,
            to_stage=downstream,
            rate=_rate(tally.count(downstream), tally.count(upstream)),
        )
        for upstream, downstream in zip(_STAGE_ORDER, _STAGE_ORDER[1:], strict=False)
    )
    rejections = tuple(sorted(tally.rejections, key=lambda item: (item.reason,)))
    counterfactual = Counterfactual(
        accepted=tally.executed,
        rejected=sum(item.count for item in rejections),
        rejections=rejections,
        foregone_outcome=unavailable("NO_HINDSIGHT_COUNTERFACTUAL"),
    )
    draft_fields = {
        "funnel_id": "0" * 64,
        "stages": stages,
        "conversions": conversions,
        "overall_conversion": _rate(tally.closed, tally.discovered),
        "system_halts": tally.system_halts,
        "counterfactual": counterfactual,
    }
    draft = OpportunityFunnel.model_construct(**draft_fields)  # type: ignore[arg-type]
    fields = draft.model_dump(mode="python", exclude={"funnel_id"})
    return OpportunityFunnel.model_validate({**fields, "funnel_id": fingerprint(fields)})
