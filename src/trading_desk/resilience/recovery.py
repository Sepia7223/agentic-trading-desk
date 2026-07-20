"""Reconciliation-first recovery gate.

New entries are blocked until authoritative reconciliation succeeds; protective
lifecycle monitoring takes priority and runs whenever it is safe. Success is
never inferred from local intent — only an authoritative ``SUCCEEDED``
reconciliation, combined with a healthy preflight, enables new entries. A
reconciliation mismatch or unavailable authoritative state keeps the desk in a
protective-only posture with entries blocked.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import Field, model_validator

from trading_desk.context.fingerprints import fingerprint
from trading_desk.resilience.diagnostics import ResilienceModel
from trading_desk.resilience.preflight import OperatingState, PreflightReport


class ReconciliationStatus(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    SUCCEEDED = "SUCCEEDED"
    MISMATCH = "MISMATCH"
    UNAVAILABLE = "UNAVAILABLE"


class RecoveryPhase(StrEnum):
    HALTED = "HALTED"
    PROTECTIVE_ONLY = "PROTECTIVE_ONLY"
    RECONCILING = "RECONCILING"
    ENTRIES_ENABLED = "ENTRIES_ENABLED"


class RecoveryDecision(ResilienceModel):
    decision_id: str = Field(min_length=64, max_length=64)
    phase: RecoveryPhase
    new_entries_allowed: bool
    protective_monitoring_allowed: bool
    active_positions: int = Field(ge=0)
    reconciliation: ReconciliationStatus
    blocking_reasons: tuple[str, ...]

    @model_validator(mode="after")
    def identity(self) -> Self:
        expected = fingerprint(self.model_dump(mode="python", exclude={"decision_id"}))
        if self.decision_id != expected:
            raise ValueError("recovery decision fingerprint mismatch")
        return self

    @model_validator(mode="after")
    def entries_require_reconciliation(self) -> Self:
        if self.new_entries_allowed and self.reconciliation is not ReconciliationStatus.SUCCEEDED:
            raise ValueError("new entries require a succeeded reconciliation")
        return self


def evaluate_recovery(
    preflight: PreflightReport,
    reconciliation: ReconciliationStatus,
    *,
    active_positions: int,
) -> RecoveryDecision:
    """Compose preflight with reconciliation into a fail-closed recovery posture."""

    blocking: list[str] = list(preflight.blocking_reasons)
    monitoring = preflight.protective_monitoring_allowed

    if preflight.state is OperatingState.RECOVERY_REQUIRED or not monitoring:
        phase = RecoveryPhase.HALTED
        new_entries_allowed = False
        monitoring = False
        blocking.append("PROTECTIVE_MONITORING_UNAVAILABLE")
    elif reconciliation is ReconciliationStatus.SUCCEEDED and preflight.new_entries_allowed:
        phase = RecoveryPhase.ENTRIES_ENABLED
        new_entries_allowed = True
    elif reconciliation in {
        ReconciliationStatus.NOT_STARTED,
        ReconciliationStatus.IN_PROGRESS,
    }:
        phase = RecoveryPhase.RECONCILING
        new_entries_allowed = False
        blocking.append(f"RECONCILIATION_{reconciliation.value}")
    else:
        phase = RecoveryPhase.PROTECTIVE_ONLY
        new_entries_allowed = False
        if reconciliation is not ReconciliationStatus.SUCCEEDED:
            blocking.append(f"RECONCILIATION_{reconciliation.value}")
        else:
            blocking.append("PREFLIGHT_BLOCKS_ENTRIES")

    draft_fields = {
        "decision_id": "0" * 64,
        "phase": phase,
        "new_entries_allowed": new_entries_allowed,
        "protective_monitoring_allowed": monitoring,
        "active_positions": active_positions,
        "reconciliation": reconciliation,
        "blocking_reasons": tuple(dict.fromkeys(blocking)),
    }
    draft = RecoveryDecision.model_construct(**draft_fields)  # type: ignore[arg-type]
    fields = draft.model_dump(mode="python", exclude={"decision_id"})
    return RecoveryDecision.model_validate({**fields, "decision_id": fingerprint(fields)})
