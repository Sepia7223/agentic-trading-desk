"""Milestone 16: fail-closed startup preflight, diagnostics, and incidents."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from trading_desk.resilience import (
    DiagnosticCheck,
    DiagnosticStatus,
    IncidentCategory,
    IncidentRecord,
    IncidentSeverity,
    OperatingState,
    create_incident,
    evaluate_clock_drift,
    evaluate_connectivity,
    evaluate_disk_space,
    evaluate_integrity,
    evaluate_memory,
    evaluate_timezone,
    run_preflight,
)

GB = 1024**3
NOW = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)


def healthy_results():  # type: ignore[no-untyped-def]
    return (
        evaluate_clock_drift(Decimal("0.2")),
        evaluate_timezone("UTC"),
        evaluate_disk_space(50 * GB, required_bytes=2 * GB, degraded_bytes=10 * GB),
        evaluate_memory(8 * GB, required_bytes=1 * GB, degraded_bytes=2 * GB),
        evaluate_connectivity(True),
        evaluate_integrity(
            DiagnosticCheck.JOURNAL_INTEGRITY, present=True, fingerprint_verified=True
        ),
        evaluate_integrity(
            DiagnosticCheck.STATE_INTEGRITY, present=True, fingerprint_verified=True
        ),
    )


def test_unknown_readings_fail_closed() -> None:
    assert evaluate_clock_drift(None).status is DiagnosticStatus.FAILED
    assert evaluate_timezone(None).status is DiagnosticStatus.FAILED
    assert (
        evaluate_disk_space(None, required_bytes=1, degraded_bytes=2).status
        is DiagnosticStatus.FAILED
    )
    assert (
        evaluate_memory(None, required_bytes=1, degraded_bytes=2).status is DiagnosticStatus.FAILED
    )
    assert evaluate_connectivity(None).status is DiagnosticStatus.FAILED
    assert (
        evaluate_integrity(
            DiagnosticCheck.STATE_INTEGRITY, present=True, fingerprint_verified=None
        ).status
        is DiagnosticStatus.FAILED
    )


def test_thresholds_produce_degraded_and_failed_bands() -> None:
    assert evaluate_clock_drift(Decimal("2")).status is DiagnosticStatus.DEGRADED
    assert evaluate_clock_drift(Decimal("9")).status is DiagnosticStatus.FAILED
    assert evaluate_timezone("America/La_Paz").status is DiagnosticStatus.FAILED
    assert (
        evaluate_disk_space(5 * GB, required_bytes=2 * GB, degraded_bytes=10 * GB).status
        is DiagnosticStatus.DEGRADED
    )
    assert (
        evaluate_disk_space(1 * GB, required_bytes=2 * GB, degraded_bytes=10 * GB).status
        is DiagnosticStatus.FAILED
    )


def test_absent_store_is_ok_on_clean_host() -> None:
    result = evaluate_integrity(
        DiagnosticCheck.JOURNAL_INTEGRITY, present=False, fingerprint_verified=None
    )
    assert result.status is DiagnosticStatus.OK
    assert result.reason == "STORE_ABSENT_CLEAN_HOST"


def test_healthy_preflight_permits_entries_and_monitoring() -> None:
    report = run_preflight(healthy_results())
    assert report.state is OperatingState.HEALTHY
    assert report.new_entries_allowed is True
    assert report.protective_monitoring_allowed is True
    assert report.blocking_reasons == ()


def test_degraded_blocks_entries_but_allows_monitoring_when_connected() -> None:
    results = (
        evaluate_clock_drift(Decimal("2")),  # DEGRADED
        evaluate_timezone("UTC"),
        evaluate_disk_space(50 * GB, required_bytes=2 * GB, degraded_bytes=10 * GB),
        evaluate_memory(8 * GB, required_bytes=1 * GB, degraded_bytes=2 * GB),
        evaluate_connectivity(True),
        evaluate_integrity(
            DiagnosticCheck.JOURNAL_INTEGRITY, present=True, fingerprint_verified=True
        ),
        evaluate_integrity(
            DiagnosticCheck.STATE_INTEGRITY, present=True, fingerprint_verified=True
        ),
    )
    report = run_preflight(results)
    assert report.state is OperatingState.DEGRADED
    assert report.new_entries_allowed is False
    assert report.protective_monitoring_allowed is True
    assert any("CLOCK_DRIFT" in reason for reason in report.blocking_reasons)


def test_lost_connectivity_halts_and_blocks_monitoring() -> None:
    results = (
        evaluate_clock_drift(Decimal("0.1")),
        evaluate_timezone("UTC"),
        evaluate_disk_space(50 * GB, required_bytes=2 * GB, degraded_bytes=10 * GB),
        evaluate_memory(8 * GB, required_bytes=1 * GB, degraded_bytes=2 * GB),
        evaluate_connectivity(False),  # FAILED critical
        evaluate_integrity(
            DiagnosticCheck.JOURNAL_INTEGRITY, present=True, fingerprint_verified=True
        ),
        evaluate_integrity(
            DiagnosticCheck.STATE_INTEGRITY, present=True, fingerprint_verified=True
        ),
    )
    report = run_preflight(results)
    assert report.state is OperatingState.HALTED
    assert report.new_entries_allowed is False
    assert report.protective_monitoring_allowed is False


def test_corrupt_state_forces_recovery_required_and_stops_everything() -> None:
    results = (
        evaluate_clock_drift(Decimal("0.1")),
        evaluate_timezone("UTC"),
        evaluate_disk_space(50 * GB, required_bytes=2 * GB, degraded_bytes=10 * GB),
        evaluate_memory(8 * GB, required_bytes=1 * GB, degraded_bytes=2 * GB),
        evaluate_connectivity(True),
        evaluate_integrity(
            DiagnosticCheck.JOURNAL_INTEGRITY, present=True, fingerprint_verified=True
        ),
        evaluate_integrity(
            DiagnosticCheck.STATE_INTEGRITY, present=True, fingerprint_verified=False
        ),
    )
    report = run_preflight(results)
    assert report.state is OperatingState.RECOVERY_REQUIRED
    assert report.new_entries_allowed is False
    assert report.protective_monitoring_allowed is False
    assert any("FINGERPRINT_MISMATCH_CORRUPT" in reason for reason in report.blocking_reasons)


def test_preflight_is_deterministic_and_order_independent() -> None:
    results = healthy_results()
    forward = run_preflight(results)
    shuffled = run_preflight(tuple(reversed(results)))
    assert forward.report_id == shuffled.report_id


def test_preflight_requires_at_least_one_result() -> None:
    with pytest.raises(ValueError):
        run_preflight(())


def test_preflight_fingerprint_rejects_tampering() -> None:
    report = run_preflight(healthy_results())
    payload = report.model_dump(mode="python")
    payload["new_entries_allowed"] = not payload["new_entries_allowed"]
    with pytest.raises(ValidationError):
        type(report).model_validate(payload)


def test_incident_records_are_fingerprinted_and_reject_secret_details() -> None:
    incident = create_incident(
        category=IncidentCategory.CORRUPT_STATE_QUARANTINED,
        severity=IncidentSeverity.CRITICAL,
        detected_at=NOW,
        source="startup_preflight",
        summary="state fingerprint mismatch on restart",
        recommended_action="restore from last verified backup",
        requires_human_clearance=True,
        safe_details=(("store", "portfolio-state.json"), ("host", "mini-pc")),
    )
    assert len(incident.incident_id) == 64
    assert incident.safe_details == (("host", "mini-pc"), ("store", "portfolio-state.json"))
    with pytest.raises(ValidationError):
        create_incident(
            category=IncidentCategory.CRASH_RECOVERY,
            severity=IncidentSeverity.WARNING,
            detected_at=NOW,
            source="recovery",
            summary="leak attempt",
            recommended_action="none",
            requires_human_clearance=False,
            safe_details=(("password", "hunter2"),),
        )


def test_incident_requires_utc_timestamp() -> None:
    with pytest.raises(ValidationError):
        create_incident(
            category=IncidentCategory.CRASH_RECOVERY,
            severity=IncidentSeverity.INFO,
            detected_at=datetime(2026, 5, 1, 12, 0),
            source="recovery",
            summary="naive timestamp",
            recommended_action="none",
            requires_human_clearance=False,
        )


def test_incident_fingerprint_rejects_tampering() -> None:
    incident = create_incident(
        category=IncidentCategory.STALE_LOCK_CLEARED,
        severity=IncidentSeverity.INFO,
        detected_at=NOW,
        source="lock",
        summary="stale lock removed",
        recommended_action="none",
        requires_human_clearance=False,
    )
    payload = incident.model_dump(mode="python")
    payload["severity"] = IncidentSeverity.CRITICAL.value
    with pytest.raises(ValidationError):
        IncidentRecord.model_validate(payload)


def test_resilience_package_has_no_operational_or_mutation_dependencies() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "trading_desk" / "resilience"
    forbidden = re.compile(
        r"from trading_desk\.(ig|execution|lifecycle|api|operations|risk|portfolio|opportunity)"
        r"|import httpx|import requests"
    )
    for path in root.glob("*.py"):
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith(("import ", "from ")):
                assert not forbidden.search(stripped), f"{path.name}: {stripped}"
