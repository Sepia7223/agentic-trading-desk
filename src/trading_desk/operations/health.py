"""Fail-closed health aggregation from explicit read-only observations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from trading_desk.journal.models import IntegrityReport, IntegrityStatus
from trading_desk.operations.models import RuntimeSubsystemHealth, SystemStatus


def unknown_health(name: str, observed_at: datetime, reason: str) -> RuntimeSubsystemHealth:
    return RuntimeSubsystemHealth(
        name=name,
        status=SystemStatus.UNKNOWN,
        observed_at=observed_at,
        reason_codes=(reason,),
    )


def aggregate_status(states: tuple[RuntimeSubsystemHealth, ...]) -> SystemStatus:
    statuses = {item.status for item in states}
    if SystemStatus.RECOVERY_REQUIRED in statuses:
        return SystemStatus.RECOVERY_REQUIRED
    if SystemStatus.HALTED in statuses:
        return SystemStatus.HALTED
    if statuses <= {SystemStatus.HEALTHY}:
        return SystemStatus.HEALTHY
    if SystemStatus.STOPPED in statuses:
        return SystemStatus.STOPPED
    if statuses <= {SystemStatus.UNKNOWN}:
        return SystemStatus.UNKNOWN
    return SystemStatus.DEGRADED


@dataclass(frozen=True)
class StartupJournalHealth:
    """Immutable startup verification summary without a writable repository handle."""

    status: SystemStatus
    schema_version: int
    records_checked: int
    reason_codes: tuple[str, ...]

    @classmethod
    def from_integrity_report(cls, report: IntegrityReport) -> StartupJournalHealth:
        statuses = {
            IntegrityStatus.VALID: SystemStatus.HEALTHY,
            IntegrityStatus.WARNINGS: SystemStatus.DEGRADED,
            IntegrityStatus.INVALID: SystemStatus.HALTED,
            IntegrityStatus.RECOVERY_REQUIRED: SystemStatus.RECOVERY_REQUIRED,
            IntegrityStatus.UNSUPPORTED_SCHEMA: SystemStatus.RECOVERY_REQUIRED,
        }
        return cls(
            status=statuses[report.status],
            schema_version=report.schema_version,
            records_checked=report.records_checked,
            reason_codes=tuple(finding.code for finding in report.findings),
        )

    def journal_state(self, observed_at: datetime) -> RuntimeSubsystemHealth:
        return RuntimeSubsystemHealth(
            name="journal",
            status=self.status,
            observed_at=observed_at,
            reason_codes=self.reason_codes,
            safe_details={
                "schema_version": self.schema_version,
                "records_checked": self.records_checked,
            },
        )
