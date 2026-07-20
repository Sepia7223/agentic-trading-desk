"""Live-trading readiness assessment (Milestone 19).

Optional governance tooling. It produces an advisory go/no-go readiness dossier
and never enables Live trading, adds a Live host or adapter, uses Live
credentials, submits a Live order, or authorizes future implementation.
"""

from trading_desk.readiness.assessment import (
    Approver,
    AssessmentDomain,
    DomainAssessment,
    DomainStatus,
    Finding,
    FindingSeverity,
    GoLivePrerequisites,
    RequiredControl,
    ResidualRisk,
)
from trading_desk.readiness.dossier import (
    ReadinessDossier,
    Recommendation,
    evaluate_readiness,
)

__all__ = [
    "Approver",
    "AssessmentDomain",
    "DomainAssessment",
    "DomainStatus",
    "Finding",
    "FindingSeverity",
    "GoLivePrerequisites",
    "ReadinessDossier",
    "Recommendation",
    "RequiredControl",
    "ResidualRisk",
    "evaluate_readiness",
]
