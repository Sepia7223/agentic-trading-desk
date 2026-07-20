"""Milestone 16: bounded retry, reconciliation-first recovery, RTO/RPO."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from trading_desk.resilience import (
    AttemptResult,
    OperationKind,
    ReconciliationStatus,
    RecoveryObjective,
    RecoveryPhase,
    RetryPolicy,
    assess_objectives,
    evaluate_recovery,
    plan_retry,
    run_preflight,
)
from trading_desk.resilience.diagnostics import (
    DiagnosticCheck,
    evaluate_clock_drift,
    evaluate_connectivity,
    evaluate_disk_space,
    evaluate_integrity,
    evaluate_memory,
    evaluate_timezone,
)

GB = 1024**3
POLICY = RetryPolicy(
    max_attempts=4,
    base_delay_seconds=Decimal("0.5"),
    backoff_factor=Decimal("2"),
    max_delay_seconds=Decimal("5"),
)


def _preflight(*, connectivity: bool, drift: str = "0.1", state_ok: bool = True):  # type: ignore[no-untyped-def]
    return run_preflight(
        (
            evaluate_clock_drift(Decimal(drift)),
            evaluate_timezone("UTC"),
            evaluate_disk_space(50 * GB, required_bytes=2 * GB, degraded_bytes=10 * GB),
            evaluate_memory(8 * GB, required_bytes=1 * GB, degraded_bytes=2 * GB),
            evaluate_connectivity(connectivity),
            evaluate_integrity(
                DiagnosticCheck.JOURNAL_INTEGRITY, present=True, fingerprint_verified=True
            ),
            evaluate_integrity(
                DiagnosticCheck.STATE_INTEGRITY, present=True, fingerprint_verified=state_ok
            ),
        )
    )


def test_read_only_transient_failures_retry_with_bounded_backoff() -> None:
    first = plan_retry(
        POLICY, kind=OperationKind.READ_ONLY, attempt=1, result=AttemptResult.TRANSIENT_FAILURE
    )
    assert first.should_retry is True
    assert first.delay_seconds == Decimal("0.5")
    second = plan_retry(
        POLICY, kind=OperationKind.READ_ONLY, attempt=2, result=AttemptResult.TRANSIENT_FAILURE
    )
    assert second.delay_seconds == Decimal("1.0")
    third = plan_retry(
        POLICY, kind=OperationKind.READ_ONLY, attempt=3, result=AttemptResult.TRANSIENT_FAILURE
    )
    assert third.delay_seconds == Decimal("2.0")


def test_backoff_is_capped_at_max_delay() -> None:
    policy = RetryPolicy(
        max_attempts=10,
        base_delay_seconds=Decimal("1"),
        backoff_factor=Decimal("3"),
        max_delay_seconds=Decimal("5"),
    )
    decision = plan_retry(
        policy, kind=OperationKind.READ_ONLY, attempt=5, result=AttemptResult.TRANSIENT_FAILURE
    )
    assert decision.delay_seconds == Decimal("5")


def test_retry_budget_is_bounded() -> None:
    decision = plan_retry(
        POLICY, kind=OperationKind.READ_ONLY, attempt=4, result=AttemptResult.TRANSIENT_FAILURE
    )
    assert decision.should_retry is False
    assert decision.reason == "RETRY_BUDGET_EXHAUSTED"


def test_ambiguous_mutation_is_never_retried_and_halts() -> None:
    decision = plan_retry(
        POLICY,
        kind=OperationKind.AMBIGUOUS_MUTATION,
        attempt=1,
        result=AttemptResult.TRANSIENT_FAILURE,
    )
    assert decision.should_retry is False
    assert decision.halt_required is True
    assert decision.reason == "AMBIGUOUS_OUTCOME_REQUIRES_RECONCILIATION"


def test_ambiguous_result_on_any_kind_halts() -> None:
    decision = plan_retry(
        POLICY, kind=OperationKind.READ_ONLY, attempt=1, result=AttemptResult.AMBIGUOUS
    )
    assert decision.should_retry is False
    assert decision.halt_required is True


def test_mutation_transient_failure_requires_reconciliation_not_retry() -> None:
    decision = plan_retry(
        POLICY,
        kind=OperationKind.IDEMPOTENT_MUTATION,
        attempt=1,
        result=AttemptResult.TRANSIENT_FAILURE,
    )
    assert decision.should_retry is False
    assert decision.reason == "MUTATION_REQUIRES_RECONCILIATION_NOT_RETRY"


def test_success_needs_no_retry() -> None:
    decision = plan_retry(
        POLICY, kind=OperationKind.READ_ONLY, attempt=1, result=AttemptResult.SUCCESS
    )
    assert decision.should_retry is False
    assert decision.reason == "SUCCEEDED"


def test_entries_enabled_only_after_successful_reconciliation() -> None:
    healthy = _preflight(connectivity=True)
    decision = evaluate_recovery(healthy, ReconciliationStatus.SUCCEEDED, active_positions=0)
    assert decision.phase is RecoveryPhase.ENTRIES_ENABLED
    assert decision.new_entries_allowed is True
    assert decision.protective_monitoring_allowed is True


def test_reconciling_blocks_entries_but_monitors() -> None:
    healthy = _preflight(connectivity=True)
    for status in (ReconciliationStatus.NOT_STARTED, ReconciliationStatus.IN_PROGRESS):
        decision = evaluate_recovery(healthy, status, active_positions=2)
        assert decision.phase is RecoveryPhase.RECONCILING
        assert decision.new_entries_allowed is False
        assert decision.protective_monitoring_allowed is True


def test_reconciliation_mismatch_stays_protective_only() -> None:
    healthy = _preflight(connectivity=True)
    decision = evaluate_recovery(healthy, ReconciliationStatus.MISMATCH, active_positions=1)
    assert decision.phase is RecoveryPhase.PROTECTIVE_ONLY
    assert decision.new_entries_allowed is False
    assert any("MISMATCH" in reason for reason in decision.blocking_reasons)


def test_lost_connectivity_halts_recovery() -> None:
    halted = _preflight(connectivity=False)
    decision = evaluate_recovery(halted, ReconciliationStatus.SUCCEEDED, active_positions=3)
    assert decision.phase is RecoveryPhase.HALTED
    assert decision.new_entries_allowed is False
    assert decision.protective_monitoring_allowed is False


def test_corrupt_state_recovery_required_never_enables_entries() -> None:
    corrupt = _preflight(connectivity=True, state_ok=False)
    decision = evaluate_recovery(corrupt, ReconciliationStatus.SUCCEEDED, active_positions=0)
    assert decision.phase is RecoveryPhase.HALTED
    assert decision.new_entries_allowed is False


def test_recovery_decision_cannot_claim_entries_without_reconciliation() -> None:
    healthy = _preflight(connectivity=True)
    decision = evaluate_recovery(healthy, ReconciliationStatus.SUCCEEDED, active_positions=0)
    forged = decision.model_dump(mode="python")
    forged["reconciliation"] = ReconciliationStatus.MISMATCH.value
    with pytest.raises(ValidationError):
        type(decision).model_validate(forged)


def test_recovery_decision_is_deterministic() -> None:
    healthy = _preflight(connectivity=True)
    a = evaluate_recovery(healthy, ReconciliationStatus.IN_PROGRESS, active_positions=1)
    b = evaluate_recovery(healthy, ReconciliationStatus.IN_PROGRESS, active_positions=1)
    assert a.decision_id == b.decision_id


def test_rpo_met_only_when_cadence_and_backup_age_satisfy_objective() -> None:
    objective = RecoveryObjective(rto_seconds=900, rpo_seconds=3600, backup_interval_seconds=1800)
    good = assess_objectives(objective, last_backup_age_seconds=1200, observed_recovery_seconds=600)
    assert good.rpo_met is True
    assert good.rto_met is True
    assert good.cadence_supports_rpo is True


def test_rpo_fails_when_backup_is_stale_or_cadence_too_slow() -> None:
    stale = assess_objectives(
        RecoveryObjective(rto_seconds=900, rpo_seconds=3600, backup_interval_seconds=1800),
        last_backup_age_seconds=7200,
        observed_recovery_seconds=600,
    )
    assert stale.rpo_met is False
    assert "LAST_BACKUP_OLDER_THAN_RPO" in stale.reasons

    slow_cadence = assess_objectives(
        RecoveryObjective(rto_seconds=900, rpo_seconds=1800, backup_interval_seconds=3600),
        last_backup_age_seconds=600,
        observed_recovery_seconds=600,
    )
    assert slow_cadence.cadence_supports_rpo is False
    assert slow_cadence.rpo_met is False


def test_unmeasured_recovery_is_not_assumed_met() -> None:
    assessment = assess_objectives(
        RecoveryObjective(rto_seconds=900, rpo_seconds=3600, backup_interval_seconds=1800),
        last_backup_age_seconds=None,
        observed_recovery_seconds=None,
    )
    assert assessment.rto_met is False
    assert assessment.rpo_met is False
    assert "RECOVERY_TIME_UNMEASURED" in assessment.reasons
    assert "BACKUP_AGE_UNKNOWN" in assessment.reasons
