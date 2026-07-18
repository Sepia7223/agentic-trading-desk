"""Fail-closed authorization policy for bounded Demo exploration."""

from pydantic import BaseModel, ConfigDict

from trading_desk.opportunity.config import DemoExplorationConfiguration
from trading_desk.opportunity.models import CandidateStatus, OpportunityCandidate


class DemoExplorationDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    authorized_for_risk: bool
    recommended_risk_multiplier: str | None
    reasons: tuple[str, ...]


def authorize_for_risk(
    candidate: OpportunityCandidate | None,
    configuration: DemoExplorationConfiguration,
    *,
    explicit_enable: bool,
    entry_halted: bool = False,
) -> DemoExplorationDecision:
    reasons: list[str] = []
    if not configuration.enabled:
        reasons.append("DEMO_EXPLORATION_DISABLED")
    if not explicit_enable:
        reasons.append("EXPLICIT_ENABLE_REQUIRED")
    if entry_halted:
        reasons.append("ENTRY_HALTED")
    if candidate is None:
        reasons.append("NO_CANDIDATE")
    elif candidate.status is not CandidateStatus.ELIGIBLE:
        reasons.append("CANDIDATE_INELIGIBLE")
    elif candidate.net_expected_value <= 0:
        reasons.append("NON_POSITIVE_EXPECTED_VALUE")
    multiplier = None if candidate is None else str(candidate.recommended_risk_multiplier)
    return DemoExplorationDecision(
        authorized_for_risk=not reasons,
        recommended_risk_multiplier=multiplier if not reasons else None,
        reasons=tuple(reasons),
    )
