"""Operational resilience and disaster recovery (Milestone 16).

Fail-closed startup preflight, dependency-health diagnostics, and structured
incident evidence. This package holds no trading authority and performs no
broker, execution, or lifecycle mutation; it decides whether the desk may start,
whether new entries are permitted, and records resilience events as immutable
evidence.
"""

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
from trading_desk.resilience.preflight import (
    OperatingState,
    PreflightReport,
    run_preflight,
)

__all__ = [
    "DiagnosticCheck",
    "DiagnosticResult",
    "DiagnosticStatus",
    "IncidentCategory",
    "IncidentRecord",
    "IncidentSeverity",
    "OperatingState",
    "PreflightReport",
    "create_incident",
    "evaluate_clock_drift",
    "evaluate_connectivity",
    "evaluate_disk_space",
    "evaluate_integrity",
    "evaluate_memory",
    "evaluate_timezone",
    "run_preflight",
]
