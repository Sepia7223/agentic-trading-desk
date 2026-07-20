"""Deterministic readiness dossier and advisory go/no-go recommendation.

The recommendation is advisory governance output, never an authorization. The
rules are fail-closed and encode that Demo certification is not financial
suitability:

- Any domain that FAILs, or any unresolved HIGH/CRITICAL finding, forces NO_GO.
- GO is possible only when every domain PASSes, no unresolved MEDIUM-or-worse
  finding remains, AND every human-gated go-live prerequisite is met (milestones
  accepted, Demo certified, legal/financial review, independent safety review,
  separate Live infrastructure and credentials) with named approvers recorded.
- Everything else is CONDITIONAL_GO, with the unmet prerequisites and required
  controls listed. Software alone cannot satisfy the prerequisites, so an
  unattended assessment can never reach GO by itself.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import Field, model_validator

from trading_desk.context.fingerprints import fingerprint
from trading_desk.readiness.assessment import (
    Approver,
    AssessmentDomain,
    DomainAssessment,
    DomainStatus,
    FindingSeverity,
    GoLivePrerequisites,
    ReadinessModel,
    RequiredControl,
    ResidualRisk,
)

_ALL_DOMAINS = frozenset(AssessmentDomain)
_MEDIUM_OR_WORSE = frozenset(
    {FindingSeverity.MEDIUM, FindingSeverity.HIGH, FindingSeverity.CRITICAL}
)
_BLOCKING = frozenset({FindingSeverity.HIGH, FindingSeverity.CRITICAL})


class Recommendation(StrEnum):
    GO = "GO"
    CONDITIONAL_GO = "CONDITIONAL_GO"
    NO_GO = "NO_GO"


class ReadinessDossier(ReadinessModel):
    dossier_id: str = Field(min_length=64, max_length=64)
    recommendation: Recommendation
    assessments: tuple[DomainAssessment, ...] = Field(min_length=1)
    prerequisites: GoLivePrerequisites
    unmet_prerequisites: tuple[str, ...]
    blocking_findings: tuple[str, ...]
    residual_risks: tuple[ResidualRisk, ...]
    required_controls: tuple[RequiredControl, ...]
    approvers: tuple[Approver, ...]
    rationale: str = Field(min_length=1)
    demo_only_notice: str = Field(min_length=1)

    @model_validator(mode="after")
    def identity(self) -> Self:
        expected = fingerprint(self.model_dump(mode="python", exclude={"dossier_id"}))
        if self.dossier_id != expected:
            raise ValueError("readiness dossier fingerprint mismatch")
        return self

    @model_validator(mode="after")
    def go_requires_everything(self) -> Self:
        if self.recommendation is Recommendation.GO:
            if self.unmet_prerequisites or self.blocking_findings:
                raise ValueError("GO is impossible with unmet prerequisites or blocking findings")
            if not self.approvers:
                raise ValueError("GO requires named human approvers")
        return self


def evaluate_readiness(
    assessments: tuple[DomainAssessment, ...],
    prerequisites: GoLivePrerequisites,
    *,
    residual_risks: tuple[ResidualRisk, ...] = (),
    required_controls: tuple[RequiredControl, ...] = (),
    approvers: tuple[Approver, ...] = (),
) -> ReadinessDossier:
    """Compute the deterministic, advisory readiness recommendation."""

    if not assessments:
        raise ValueError("a readiness assessment requires at least one domain")
    covered = {assessment.domain for assessment in assessments}
    if covered != _ALL_DOMAINS:
        missing = ", ".join(sorted(domain.value for domain in _ALL_DOMAINS - covered))
        raise ValueError(f"readiness assessment is missing domains: {missing}")

    ordered = tuple(sorted(assessments, key=lambda item: item.domain.value))
    unresolved = [
        finding for assessment in ordered for finding in assessment.findings if not finding.resolved
    ]
    blocking = tuple(
        f"{finding.domain.value}:{finding.severity.value}:{finding.summary}"
        for finding in unresolved
        if finding.severity in _BLOCKING
    )
    any_domain_failed = any(item.status is DomainStatus.FAIL for item in ordered)
    all_pass = all(item.status is DomainStatus.PASS for item in ordered)
    any_medium_or_worse = any(finding.severity in _MEDIUM_OR_WORSE for finding in unresolved)
    unmet = prerequisites.unmet()

    if any_domain_failed or blocking:
        recommendation = Recommendation.NO_GO
        rationale = "fundamental blocker: a domain failed or an unresolved high/critical finding"
    elif all_pass and not any_medium_or_worse and prerequisites.all_met and approvers:
        recommendation = Recommendation.GO
        rationale = (
            "all domains pass, no material unresolved finding, prerequisites met, approvers named"
        )
    else:
        recommendation = Recommendation.CONDITIONAL_GO
        rationale = (
            "no fundamental blocker, but go-live prerequisites and/or controls remain "
            "outstanding; proceed only after they are satisfied and independently reviewed"
        )

    draft_fields = {
        "dossier_id": "0" * 64,
        "recommendation": recommendation,
        "assessments": ordered,
        "prerequisites": prerequisites,
        "unmet_prerequisites": unmet,
        "blocking_findings": blocking,
        "residual_risks": residual_risks,
        "required_controls": required_controls,
        "approvers": approvers,
        "rationale": rationale,
        "demo_only_notice": (
            "This assessment does not enable Live trading. The system remains "
            "Demo-only regardless of outcome; any Live work requires a new "
            "architecture decision, legal and financial approval, separate "
            "credentials and infrastructure, and an independent safety review."
        ),
    }
    draft = ReadinessDossier.model_construct(**draft_fields)  # type: ignore[arg-type]
    fields = draft.model_dump(mode="python", exclude={"dossier_id"})
    return ReadinessDossier.model_validate({**fields, "dossier_id": fingerprint(fields)})
