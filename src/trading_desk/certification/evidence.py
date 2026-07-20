"""Certification evidence contract for full IG Demo operational certification.

The seventeen required observations are split into two groups: those observable
from read-only and software operation, and those that require a naturally
occurring bounded Demo trade. This split encodes a core certification rule —
markets being closed or no candidate appearing is a legitimate reason to
continue later, not a defect — so an absent natural trade yields
PARTIALLY_CERTIFIED, never FAILED. Nothing here manufactures a trade; it only
structures and classifies evidence that actually occurred.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CertificationModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


class CertificationItem(StrEnum):
    ENVIRONMENT_SECRET_PREFLIGHT = "ENVIRONMENT_SECRET_PREFLIGHT"
    AUTHENTICATION_ACCOUNT_DISCOVERY = "AUTHENTICATION_ACCOUNT_DISCOVERY"
    AUTHORITATIVE_ACCOUNT_STATE = "AUTHORITATIVE_ACCOUNT_STATE"
    COMPLETED_BAR_SCHEDULING = "COMPLETED_BAR_SCHEDULING"
    CONTEXT_ROUTING_SCORING_PORTFOLIO = "CONTEXT_ROUTING_SCORING_PORTFOLIO"
    OPERATIONS_CENTER_VISIBILITY = "OPERATIONS_CENTER_VISIBILITY"
    ACCEPTED_CANDIDATE_TO_RISK = "ACCEPTED_CANDIDATE_TO_RISK"
    RISK_APPROVAL_AND_QUANTITY = "RISK_APPROVAL_AND_QUANTITY"
    CONTROLLED_ORDER_SUBMISSION = "CONTROLLED_ORDER_SUBMISSION"
    CONFIRMATION_AND_RECONCILIATION = "CONFIRMATION_AND_RECONCILIATION"
    DURABLE_TRADE_STATE = "DURABLE_TRADE_STATE"
    RESTART_WITH_ACTIVE_POSITION = "RESTART_WITH_ACTIVE_POSITION"
    LIFECYCLE_MONITORING_AFTER_RESTART = "LIFECYCLE_MONITORING_AFTER_RESTART"
    NATURAL_OR_GOVERNED_CLOSE = "NATURAL_OR_GOVERNED_CLOSE"
    CLOSE_CONFIRMATION_AND_RECONCILIATION = "CLOSE_CONFIRMATION_AND_RECONCILIATION"
    REALIZED_PNL_AND_ATTRIBUTION = "REALIZED_PNL_AND_ATTRIBUTION"
    FINAL_RESTART_NO_DUPLICATE_MUTATION = "FINAL_RESTART_NO_DUPLICATE_MUTATION"


SOFTWARE_READONLY_ITEMS: frozenset[CertificationItem] = frozenset(
    {
        CertificationItem.ENVIRONMENT_SECRET_PREFLIGHT,
        CertificationItem.AUTHENTICATION_ACCOUNT_DISCOVERY,
        CertificationItem.AUTHORITATIVE_ACCOUNT_STATE,
        CertificationItem.COMPLETED_BAR_SCHEDULING,
        CertificationItem.CONTEXT_ROUTING_SCORING_PORTFOLIO,
        CertificationItem.OPERATIONS_CENTER_VISIBILITY,
    }
)

NATURAL_TRADE_ITEMS: frozenset[CertificationItem] = frozenset(
    set(CertificationItem) - SOFTWARE_READONLY_ITEMS
)


class DefectCategory(StrEnum):
    SAFETY = "SAFETY"
    CONSISTENCY = "CONSISTENCY"
    RECONCILIATION = "RECONCILIATION"
    AUTHORITY = "AUTHORITY"
    DUPLICATE_MUTATION = "DUPLICATE_MUTATION"


class EvidenceObservation(CertificationModel):
    """One observed certification item, traced to sanitized source evidence."""

    item: CertificationItem
    observed: bool
    source_evidence_id: str = ""
    note: str = ""

    @model_validator(mode="after")
    def observed_requires_source(self) -> Self:
        if self.observed and not self.source_evidence_id:
            raise ValueError("an observed item must reference sanitized source evidence")
        return self


class CertificationDefect(CertificationModel):
    """A recorded defect. Its presence forces a FAILED verdict."""

    category: DefectCategory
    summary: str = Field(min_length=1)
    source_evidence_id: str = Field(min_length=1)


def observed_items(observations: tuple[EvidenceObservation, ...]) -> frozenset[CertificationItem]:
    return frozenset(item.item for item in observations if item.observed)


def manufactured_evidence_is_prohibited(note: str) -> None:
    """Guard string used by callers to assert no synthetic candidate was created."""

    banned = ("forced", "synthetic", "manufactured", "fabricated")
    lowered = note.lower()
    if any(token in lowered for token in banned):
        raise ValueError("certification evidence must not be forced or synthetic")
