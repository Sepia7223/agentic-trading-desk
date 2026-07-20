"""Deterministic certification verdict.

Rules (from the milestone):
- A recorded defect (safety, consistency, reconciliation, authority, duplicate
  mutation) forces FAILED, regardless of how much evidence was collected.
- CERTIFIED requires every one of the seventeen required items observed.
- Otherwise the verdict is PARTIALLY_CERTIFIED — the natural-trade lifecycle
  evidence is simply not yet available (markets closed, no candidate), which is
  an explicit non-defect. The pending items and whether the software/read-only
  group is complete are reported so the gap is visible, never papered over.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import Field, model_validator

from trading_desk.certification.evidence import (
    NATURAL_TRADE_ITEMS,
    SOFTWARE_READONLY_ITEMS,
    CertificationDefect,
    CertificationItem,
    CertificationModel,
    EvidenceObservation,
    observed_items,
)
from trading_desk.context.fingerprints import fingerprint

_ALL_ITEMS = frozenset(CertificationItem)


class CertificationVerdict(StrEnum):
    CERTIFIED = "CERTIFIED"
    PARTIALLY_CERTIFIED = "PARTIALLY_CERTIFIED"
    FAILED = "FAILED"


class CertificationOutcome(CertificationModel):
    outcome_id: str = Field(min_length=64, max_length=64)
    verdict: CertificationVerdict
    satisfied_items: tuple[CertificationItem, ...]
    pending_items: tuple[CertificationItem, ...]
    software_readonly_complete: bool
    natural_trade_complete: bool
    defects: tuple[CertificationDefect, ...]
    rationale: str = Field(min_length=1)

    @model_validator(mode="after")
    def identity(self) -> Self:
        expected = fingerprint(self.model_dump(mode="python", exclude={"outcome_id"}))
        if self.outcome_id != expected:
            raise ValueError("certification outcome fingerprint mismatch")
        return self

    @model_validator(mode="after")
    def certified_requires_all_items(self) -> Self:
        if self.verdict is CertificationVerdict.CERTIFIED and self.pending_items:
            raise ValueError("CERTIFIED requires every required item observed")
        if self.verdict is CertificationVerdict.CERTIFIED and self.defects:
            raise ValueError("CERTIFIED is impossible with recorded defects")
        return self


def evaluate_certification(
    observations: tuple[EvidenceObservation, ...],
    defects: tuple[CertificationDefect, ...] = (),
) -> CertificationOutcome:
    """Compute the deterministic certification verdict from real evidence."""

    present = observed_items(observations)
    satisfied = tuple(item for item in CertificationItem if item in present)
    pending = tuple(item for item in CertificationItem if item not in present)
    software_complete = present >= SOFTWARE_READONLY_ITEMS
    natural_complete = present >= NATURAL_TRADE_ITEMS

    if defects:
        verdict = CertificationVerdict.FAILED
        rationale = "recorded defect(s) force FAILED: " + ", ".join(
            f"{defect.category.value}" for defect in defects
        )
    elif present >= _ALL_ITEMS:
        verdict = CertificationVerdict.CERTIFIED
        rationale = "all seventeen required items observed with no defect"
    elif software_complete:
        verdict = CertificationVerdict.PARTIALLY_CERTIFIED
        rationale = (
            "software and read-only operations complete; natural-trade lifecycle "
            "evidence not yet available (a legitimate reason to continue later)"
        )
    else:
        verdict = CertificationVerdict.PARTIALLY_CERTIFIED
        rationale = "certification in progress; software/read-only evidence incomplete"

    ordered_defects = tuple(
        sorted(defects, key=lambda defect: (defect.category.value, defect.source_evidence_id))
    )
    draft_fields = {
        "outcome_id": "0" * 64,
        "verdict": verdict,
        "satisfied_items": satisfied,
        "pending_items": pending,
        "software_readonly_complete": software_complete,
        "natural_trade_complete": natural_complete,
        "defects": ordered_defects,
        "rationale": rationale,
    }
    draft = CertificationOutcome.model_construct(**draft_fields)  # type: ignore[arg-type]
    fields = draft.model_dump(mode="python", exclude={"outcome_id"})
    return CertificationOutcome.model_validate({**fields, "outcome_id": fingerprint(fields)})
