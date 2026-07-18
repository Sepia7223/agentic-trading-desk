"""Persistent fail-closed Demo Exploration preflight policy."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from trading_desk.opportunity.campaign import DemoCampaignSnapshot
from trading_desk.opportunity.config import (
    DemoExplorationConfiguration,
    OpportunityEngineConfiguration,
)
from trading_desk.opportunity.exposure import CurrentExposureSnapshot
from trading_desk.opportunity.ledger import DemoTradeLedger
from trading_desk.opportunity.models import CandidateStatus, OpportunityCandidate


class ExplorationRejectionCode(StrEnum):
    WRONG_ENVIRONMENT = "WRONG_ENVIRONMENT"
    ENGINE_DISABLED = "ENGINE_DISABLED"
    EXPLORATION_DISABLED = "EXPLORATION_DISABLED"
    EXPLICIT_AUTHORIZATION_REQUIRED = "EXPLICIT_AUTHORIZATION_REQUIRED"
    CANDIDATE_INELIGIBLE = "CANDIDATE_INELIGIBLE"
    NON_POSITIVE_EXPECTED_VALUE = "NON_POSITIVE_EXPECTED_VALUE"
    STRATEGY_NOT_EXECUTABLE = "STRATEGY_NOT_EXECUTABLE"
    ENTRY_HALTED = "ENTRY_HALTED"
    DAILY_TRADE_LIMIT = "DAILY_TRADE_LIMIT"
    CONCURRENT_POSITION_LIMIT = "CONCURRENT_POSITION_LIMIT"
    CORRELATED_POSITION_LIMIT = "CORRELATED_POSITION_LIMIT"
    UNRESOLVED_EXECUTION_AMBIGUITY = "UNRESOLVED_EXECUTION_AMBIGUITY"
    RECONCILIATION_MISMATCH = "RECONCILIATION_MISMATCH"
    CAMPAIGN_SAFETY_LIMIT = "CAMPAIGN_SAFETY_LIMIT"
    EXPOSURE_UNKNOWN = "EXPOSURE_UNKNOWN"


class ExplorationPreflightDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    ready: bool
    rejection_codes: tuple[ExplorationRejectionCode, ...]


def exploration_preflight(
    candidate: OpportunityCandidate | None,
    *,
    observed_at: datetime,
    engine: OpportunityEngineConfiguration,
    exploration: DemoExplorationConfiguration,
    explicit_authorization: bool,
    exposure: CurrentExposureSnapshot | None,
    ledger: DemoTradeLedger,
    campaign: DemoCampaignSnapshot | None,
    unresolved_execution_ambiguity: bool = False,
    reconciliation_mismatch: bool = False,
) -> ExplorationPreflightDecision:
    if observed_at.tzinfo is None or observed_at.utcoffset() != UTC.utcoffset(observed_at):
        raise ValueError("exploration preflight timestamp must be UTC")
    reasons: list[ExplorationRejectionCode] = []
    if engine.environment != "DEMO" or exploration.environment != "DEMO":
        reasons.append(ExplorationRejectionCode.WRONG_ENVIRONMENT)
    if not engine.enabled:
        reasons.append(ExplorationRejectionCode.ENGINE_DISABLED)
    if not exploration.enabled:
        reasons.append(ExplorationRejectionCode.EXPLORATION_DISABLED)
    if not explicit_authorization:
        reasons.append(ExplorationRejectionCode.EXPLICIT_AUTHORIZATION_REQUIRED)
    if candidate is None or candidate.status is not CandidateStatus.ELIGIBLE:
        reasons.append(ExplorationRejectionCode.CANDIDATE_INELIGIBLE)
    else:
        if candidate.net_expected_value <= 0:
            reasons.append(ExplorationRejectionCode.NON_POSITIVE_EXPECTED_VALUE)
        if "DEMO_EXPLORATION_ENABLED" not in {
            item.value for item in candidate.strategy_validation_states
        }:
            reasons.append(ExplorationRejectionCode.STRATEGY_NOT_EXECUTABLE)
    if campaign is None or campaign.entry_halted:
        reasons.append(
            ExplorationRejectionCode.ENTRY_HALTED
            if campaign is not None
            else ExplorationRejectionCode.CAMPAIGN_SAFETY_LIMIT
        )
    if ledger.submitted_on(observed_at.date()) >= exploration.maximum_trades_per_day:
        reasons.append(ExplorationRejectionCode.DAILY_TRADE_LIMIT)
    if exposure is None:
        reasons.append(ExplorationRejectionCode.EXPOSURE_UNKNOWN)
    else:
        if exposure.current_position_count >= exploration.maximum_concurrent_positions:
            reasons.append(ExplorationRejectionCode.CONCURRENT_POSITION_LIMIT)
        for group in candidate.correlation_groups if candidate else ():
            if exposure.occupied_correlation_groups.count(group) >= (
                exploration.maximum_correlated_positions
            ):
                reasons.append(ExplorationRejectionCode.CORRELATED_POSITION_LIMIT)
                break
    if unresolved_execution_ambiguity:
        reasons.append(ExplorationRejectionCode.UNRESOLVED_EXECUTION_AMBIGUITY)
    if reconciliation_mismatch:
        reasons.append(ExplorationRejectionCode.RECONCILIATION_MISMATCH)
    unique = tuple(dict.fromkeys(reasons))
    return ExplorationPreflightDecision(ready=not unique, rejection_codes=unique)
