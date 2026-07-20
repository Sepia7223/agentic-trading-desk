"""Live-trading readiness assessment contracts (Milestone 19).

This is an optional governance assessment. It does not enable Live trading, add a
Live host or adapter, use Live credentials, or authorize anything. It structures
evidence into a documented go/no-go recommendation that is advisory only — a
human authorization process, legal and financial review, and a separate
architecture decision remain mandatory before any Live work. Demo certification
is explicitly not financial suitability.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ReadinessModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


class AssessmentDomain(StrEnum):
    ENGINEERING = "ENGINEERING"
    STRATEGY_PORTFOLIO = "STRATEGY_PORTFOLIO"
    RISK_GOVERNANCE = "RISK_GOVERNANCE"
    LEGAL_COMPLIANCE = "LEGAL_COMPLIANCE"
    SECURITY = "SECURITY"


class FindingSeverity(StrEnum):
    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


_BLOCKING_SEVERITIES = frozenset({FindingSeverity.HIGH, FindingSeverity.CRITICAL})


class DomainStatus(StrEnum):
    PASS = "PASS"
    CONCERNS = "CONCERNS"
    FAIL = "FAIL"


class Finding(ReadinessModel):
    domain: AssessmentDomain
    severity: FindingSeverity
    summary: str = Field(min_length=1)
    resolved: bool = False

    @property
    def is_blocking(self) -> bool:
        return not self.resolved and self.severity in _BLOCKING_SEVERITIES


class DomainAssessment(ReadinessModel):
    domain: AssessmentDomain
    status: DomainStatus
    summary: str = Field(min_length=1)
    findings: tuple[Finding, ...] = ()


class ResidualRisk(ReadinessModel):
    description: str = Field(min_length=1)
    severity: FindingSeverity
    quantified_impact: str = Field(min_length=1)
    accepted_by: str = ""


class RequiredControl(ReadinessModel):
    description: str = Field(min_length=1)
    domain: AssessmentDomain
    mandatory_before_live: bool = True


class Approver(ReadinessModel):
    name: str = Field(min_length=1)
    role: str = Field(min_length=1)
    review_date: str = Field(min_length=1)


class GoLivePrerequisites(ReadinessModel):
    """Human-gated prerequisites that no software step can satisfy on its own."""

    milestones_accepted: bool = False
    demo_operationally_certified: bool = False
    legal_and_financial_review_obtained: bool = False
    independent_safety_review_obtained: bool = False
    separate_live_infrastructure_and_credentials: bool = False

    @property
    def all_met(self) -> bool:
        return (
            self.milestones_accepted
            and self.demo_operationally_certified
            and self.legal_and_financial_review_obtained
            and self.independent_safety_review_obtained
            and self.separate_live_infrastructure_and_credentials
        )

    def unmet(self) -> tuple[str, ...]:
        pending = []
        if not self.milestones_accepted:
            pending.append("MILESTONES_NOT_ACCEPTED")
        if not self.demo_operationally_certified:
            pending.append("DEMO_NOT_CERTIFIED")
        if not self.legal_and_financial_review_obtained:
            pending.append("LEGAL_FINANCIAL_REVIEW_MISSING")
        if not self.independent_safety_review_obtained:
            pending.append("INDEPENDENT_SAFETY_REVIEW_MISSING")
        if not self.separate_live_infrastructure_and_credentials:
            pending.append("SEPARATE_LIVE_INFRA_MISSING")
        return tuple(pending)
