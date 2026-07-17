"""Stable deterministic alert derivation."""

from datetime import datetime

from trading_desk.operations.fingerprints import fingerprint
from trading_desk.operations.models import (
    AlertSeverity,
    OperationsAlert,
    RuntimeSubsystemHealth,
    SystemStatus,
)

ALERT_SEVERITY = {
    "SCHEDULER_STOPPED": AlertSeverity.ERROR,
    "SCHEDULER_STALE": AlertSeverity.WARNING,
    "MARKET_DATA_STALE": AlertSeverity.WARNING,
    "MARKET_CONTEXT_UNAVAILABLE": AlertSeverity.WARNING,
    "EVENT_CONTEXT_UNAVAILABLE": AlertSeverity.WARNING,
    "HOLIDAY_CONTEXT_UNAVAILABLE": AlertSeverity.WARNING,
    "BROKER_DISCONNECTED": AlertSeverity.ERROR,
    "BROKER_SESSION_EXPIRED": AlertSeverity.ERROR,
    "JOURNAL_INTEGRITY_FAILURE": AlertSeverity.CRITICAL,
    "JOURNAL_RECOVERY_REQUIRED": AlertSeverity.CRITICAL,
    "KILL_SWITCH_ACTIVE": AlertSeverity.CRITICAL,
    "DAILY_LOSS_LIMIT_REACHED": AlertSeverity.ERROR,
    "DRAWDOWN_LIMIT_REACHED": AlertSeverity.ERROR,
    "MAX_CONSECUTIVE_LOSSES_REACHED": AlertSeverity.ERROR,
    "AUTOMATED_EXECUTION_HALTED": AlertSeverity.CRITICAL,
    "BROKER_CONFIRMATION_UNKNOWN": AlertSeverity.ERROR,
    "RECONCILIATION_REQUIRED": AlertSeverity.CRITICAL,
    "RECONCILIATION_MISMATCH": AlertSeverity.CRITICAL,
    "UNEXPECTED_OPEN_POSITION": AlertSeverity.CRITICAL,
    "BACKUP_OVERDUE": AlertSeverity.WARNING,
    "AI_PROVIDER_FAILURE": AlertSeverity.WARNING,
}


def derive_alerts(
    states: tuple[RuntimeSubsystemHealth, ...], observed_at: datetime
) -> tuple[OperationsAlert, ...]:
    alerts: list[OperationsAlert] = []
    for state in states:
        if state.status is SystemStatus.HEALTHY:
            continue
        reasons = state.reason_codes or (f"{state.name.upper()}_UNAVAILABLE",)
        for reason in reasons:
            severity = ALERT_SEVERITY.get(reason, AlertSeverity.WARNING)
            fields = {
                "severity": severity,
                "category": state.name.upper(),
                "created_at": observed_at,
                "status": "ACTIVE",
                "title": reason.replace("_", " ").title(),
                "description": f"{state.name} reported {reason}",
                "source_record_ids": (),
                "reason_codes": (reason,),
                "acknowledgment_state": "UNACKNOWLEDGED",
            }
            identity = fingerprint(fields)
            alerts.append(
                OperationsAlert.model_validate(
                    {**fields, "alert_id": identity, "alert_fingerprint": identity}
                )
            )
    return tuple(sorted(alerts, key=lambda item: (item.severity.value, item.alert_id)))
