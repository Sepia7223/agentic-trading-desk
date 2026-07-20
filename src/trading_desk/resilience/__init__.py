"""Operational resilience and disaster recovery (Milestone 16).

Fail-closed startup preflight, dependency-health diagnostics, and structured
incident evidence. This package holds no trading authority and performs no
broker, execution, or lifecycle mutation; it decides whether the desk may start,
whether new entries are permitted, and records resilience events as immutable
evidence.
"""

from trading_desk.resilience.backup import (
    BackupEntry,
    BackupManifest,
    BackupService,
    RestoreOutcome,
)
from trading_desk.resilience.diagnostics import (
    DiagnosticCheck,
    DiagnosticResult,
    DiagnosticStatus,
    evaluate_clock_drift,
    evaluate_connectivity,
    evaluate_disk_space,
    evaluate_integrity,
    evaluate_memory,
    evaluate_timezone,
)
from trading_desk.resilience.incidents import (
    IncidentCategory,
    IncidentRecord,
    IncidentSeverity,
    create_incident,
)
from trading_desk.resilience.objectives import (
    ObjectiveAssessment,
    RecoveryObjective,
    assess_objectives,
)
from trading_desk.resilience.preflight import (
    OperatingState,
    PreflightReport,
    run_preflight,
)
from trading_desk.resilience.process_lock import (
    LockAcquisition,
    LockOutcome,
    ProcessLock,
    ProcessLockError,
    ProcessLockStore,
)
from trading_desk.resilience.recovery import (
    ReconciliationStatus,
    RecoveryDecision,
    RecoveryPhase,
    evaluate_recovery,
)
from trading_desk.resilience.retry import (
    AttemptResult,
    OperationKind,
    RetryDecision,
    RetryPolicy,
    plan_retry,
)

__all__ = [
    "AttemptResult",
    "BackupEntry",
    "BackupManifest",
    "BackupService",
    "DiagnosticCheck",
    "DiagnosticResult",
    "DiagnosticStatus",
    "IncidentCategory",
    "IncidentRecord",
    "IncidentSeverity",
    "LockAcquisition",
    "LockOutcome",
    "ObjectiveAssessment",
    "OperatingState",
    "OperationKind",
    "PreflightReport",
    "ProcessLock",
    "ProcessLockError",
    "ProcessLockStore",
    "ReconciliationStatus",
    "RecoveryDecision",
    "RecoveryObjective",
    "RecoveryPhase",
    "RestoreOutcome",
    "RetryDecision",
    "RetryPolicy",
    "assess_objectives",
    "create_incident",
    "evaluate_clock_drift",
    "evaluate_connectivity",
    "evaluate_disk_space",
    "evaluate_integrity",
    "evaluate_memory",
    "evaluate_recovery",
    "evaluate_timezone",
    "plan_retry",
    "run_preflight",
]
