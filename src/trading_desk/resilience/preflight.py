"""Startup preflight: aggregate diagnostics into a fail-closed go/no-go decision.

The preflight report decides the operating state and, critically, whether new
entries and protective monitoring may run. New entries are permitted only from a
fully healthy state; any degraded or failed critical dependency blocks new
entries while still allowing protective lifecycle monitoring where it is safe.
Durable-store corruption forces a recovery-required state in which nothing runs
until a human-cleared restore.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import Field, model_validator

from trading_desk.context.fingerprints import fingerprint
from trading_desk.resilience.diagnostics import (
    DiagnosticCheck,
    DiagnosticResult,
    DiagnosticStatus,
    ResilienceModel,
)


class OperatingState(StrEnum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    HALTED = "HALTED"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"


_INTEGRITY_CHECKS = frozenset({DiagnosticCheck.JOURNAL_INTEGRITY, DiagnosticCheck.STATE_INTEGRITY})
_CRITICAL_CHECKS = frozenset(
    {
        DiagnosticCheck.CLOCK_DRIFT,
        DiagnosticCheck.TIMEZONE,
        DiagnosticCheck.DISK_SPACE,
        DiagnosticCheck.CONNECTIVITY,
        DiagnosticCheck.JOURNAL_INTEGRITY,
        DiagnosticCheck.STATE_INTEGRITY,
    }
)


class PreflightReport(ResilienceModel):
    report_id: str = Field(min_length=64, max_length=64)
    state: OperatingState
    new_entries_allowed: bool
    protective_monitoring_allowed: bool
    results: tuple[DiagnosticResult, ...] = Field(min_length=1)
    blocking_reasons: tuple[str, ...]

    @model_validator(mode="after")
    def identity(self) -> Self:
        expected = fingerprint(self.model_dump(mode="python", exclude={"report_id"}))
        if self.report_id != expected:
            raise ValueError("preflight report fingerprint mismatch")
        return self


def _blocking(results: tuple[DiagnosticResult, ...]) -> tuple[str, ...]:
    return tuple(
        f"{item.check.value}:{item.reason}"
        for item in results
        if item.status is not DiagnosticStatus.OK
    )


def run_preflight(results: tuple[DiagnosticResult, ...]) -> PreflightReport:
    """Aggregate diagnostics into a deterministic, fingerprinted go/no-go report."""

    if not results:
        raise ValueError("preflight requires at least one diagnostic result")

    ordered = tuple(sorted(results, key=lambda item: (item.check.value, item.reason)))
    by_check = {item.check: item for item in ordered}
    connectivity = by_check.get(DiagnosticCheck.CONNECTIVITY)
    connectivity_ok = connectivity is not None and connectivity.status is DiagnosticStatus.OK

    integrity_failed = any(
        item.check in _INTEGRITY_CHECKS and item.status is DiagnosticStatus.FAILED
        for item in ordered
    )
    critical_failed = any(
        item.check in _CRITICAL_CHECKS and item.status is DiagnosticStatus.FAILED
        for item in ordered
    )
    any_degraded = any(item.status is DiagnosticStatus.DEGRADED for item in ordered)
    any_failed = any(item.status is DiagnosticStatus.FAILED for item in ordered)

    if integrity_failed:
        state = OperatingState.RECOVERY_REQUIRED
        new_entries_allowed = False
        protective_monitoring_allowed = False
    elif critical_failed:
        state = OperatingState.HALTED
        new_entries_allowed = False
        protective_monitoring_allowed = connectivity_ok
    elif any_degraded or any_failed:
        state = OperatingState.DEGRADED
        new_entries_allowed = False
        protective_monitoring_allowed = connectivity_ok
    else:
        state = OperatingState.HEALTHY
        new_entries_allowed = True
        protective_monitoring_allowed = True

    draft_fields = {
        "report_id": "0" * 64,
        "state": state,
        "new_entries_allowed": new_entries_allowed,
        "protective_monitoring_allowed": protective_monitoring_allowed,
        "results": ordered,
        "blocking_reasons": _blocking(ordered),
    }
    draft = PreflightReport.model_construct(**draft_fields)  # type: ignore[arg-type]
    fields = draft.model_dump(mode="python", exclude={"report_id"})
    return PreflightReport.model_validate({**fields, "report_id": fingerprint(fields)})
