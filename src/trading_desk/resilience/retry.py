"""Bounded retry for read-only operations; never for ambiguous mutations.

Only read-only operations are automatically retried, under a bounded budget with
deterministic exponential backoff. An ambiguous broker mutation — or any outcome
classified as ambiguous — is never retried and instead demands a halt and
reconciliation, because a retry could double a mutation whose first attempt may
already have taken effect. Mutations that fail transiently are not auto-retried;
they require authoritative reconciliation before any further action.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from pydantic import Field

from trading_desk.resilience.diagnostics import ResilienceModel


class OperationKind(StrEnum):
    READ_ONLY = "READ_ONLY"
    IDEMPOTENT_MUTATION = "IDEMPOTENT_MUTATION"
    AMBIGUOUS_MUTATION = "AMBIGUOUS_MUTATION"


class AttemptResult(StrEnum):
    SUCCESS = "SUCCESS"
    TRANSIENT_FAILURE = "TRANSIENT_FAILURE"
    AMBIGUOUS = "AMBIGUOUS"
    PERMANENT_FAILURE = "PERMANENT_FAILURE"


class RetryPolicy(ResilienceModel):
    max_attempts: int = Field(ge=1)
    base_delay_seconds: Decimal = Field(ge=0)
    backoff_factor: Decimal = Field(ge=1)
    max_delay_seconds: Decimal = Field(ge=0)


class RetryDecision(ResilienceModel):
    should_retry: bool
    delay_seconds: Decimal = Field(ge=0)
    halt_required: bool
    reason: str = Field(min_length=1)


def _backoff(policy: RetryPolicy, attempt: int) -> Decimal:
    raw = policy.base_delay_seconds * (policy.backoff_factor ** (attempt - 1))
    return min(raw, policy.max_delay_seconds)


def plan_retry(
    policy: RetryPolicy,
    *,
    kind: OperationKind,
    attempt: int,
    result: AttemptResult,
) -> RetryDecision:
    """Decide whether the just-finished attempt should be retried.

    ``attempt`` is the 1-based index of the attempt that just completed.
    """

    if attempt < 1:
        raise ValueError("attempt is 1-based and must be >= 1")

    if result is AttemptResult.SUCCESS:
        return RetryDecision(
            should_retry=False, delay_seconds=Decimal(0), halt_required=False, reason="SUCCEEDED"
        )

    if kind is OperationKind.AMBIGUOUS_MUTATION or result is AttemptResult.AMBIGUOUS:
        return RetryDecision(
            should_retry=False,
            delay_seconds=Decimal(0),
            halt_required=True,
            reason="AMBIGUOUS_OUTCOME_REQUIRES_RECONCILIATION",
        )

    if result is AttemptResult.PERMANENT_FAILURE:
        return RetryDecision(
            should_retry=False,
            delay_seconds=Decimal(0),
            halt_required=False,
            reason="PERMANENT_FAILURE",
        )

    # Only read-only operations are auto-retried on transient failure.
    if kind is not OperationKind.READ_ONLY:
        return RetryDecision(
            should_retry=False,
            delay_seconds=Decimal(0),
            halt_required=False,
            reason="MUTATION_REQUIRES_RECONCILIATION_NOT_RETRY",
        )

    if attempt >= policy.max_attempts:
        return RetryDecision(
            should_retry=False,
            delay_seconds=Decimal(0),
            halt_required=False,
            reason="RETRY_BUDGET_EXHAUSTED",
        )

    return RetryDecision(
        should_retry=True,
        delay_seconds=_backoff(policy, attempt),
        halt_required=False,
        reason="RETRY_SCHEDULED",
    )
