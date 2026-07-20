"""Fail-closed startup and dependency-health diagnostics.

Each evaluator turns a raw injected reading into a typed :class:`DiagnosticResult`.
Readings are injected (never taken by these pure functions) so the threshold and
fail-closed logic is deterministic and fully testable. An unknown reading — a
``None`` where a measurement was expected — always fails closed to ``FAILED``
rather than being treated as healthy.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from trading_desk.context.fingerprints import fingerprint


class ResilienceModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


class DiagnosticStatus(StrEnum):
    OK = "OK"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"


class DiagnosticCheck(StrEnum):
    CLOCK_DRIFT = "CLOCK_DRIFT"
    TIMEZONE = "TIMEZONE"
    DISK_SPACE = "DISK_SPACE"
    MEMORY = "MEMORY"
    CONNECTIVITY = "CONNECTIVITY"
    JOURNAL_INTEGRITY = "JOURNAL_INTEGRITY"
    STATE_INTEGRITY = "STATE_INTEGRITY"
    PROCESS_LOCK = "PROCESS_LOCK"


class DiagnosticResult(ResilienceModel):
    check: DiagnosticCheck
    status: DiagnosticStatus
    reason: str = Field(min_length=1)
    observed: str = ""

    @property
    def fingerprint(self) -> str:
        return fingerprint(self)


def _result(
    check: DiagnosticCheck, status: DiagnosticStatus, reason: str, observed: str = ""
) -> DiagnosticResult:
    return DiagnosticResult(check=check, status=status, reason=reason, observed=observed)


def evaluate_clock_drift(
    offset_seconds: Decimal | None,
    *,
    degraded_tolerance: Decimal = Decimal("1"),
    failed_tolerance: Decimal = Decimal("5"),
) -> DiagnosticResult:
    """Host clock offset from an authoritative time source, in seconds."""

    check = DiagnosticCheck.CLOCK_DRIFT
    if offset_seconds is None:
        return _result(check, DiagnosticStatus.FAILED, "CLOCK_OFFSET_UNKNOWN")
    magnitude = abs(offset_seconds)
    observed = f"{offset_seconds}s"
    if magnitude > failed_tolerance:
        return _result(check, DiagnosticStatus.FAILED, "CLOCK_DRIFT_EXCEEDED", observed)
    if magnitude > degraded_tolerance:
        return _result(check, DiagnosticStatus.DEGRADED, "CLOCK_DRIFT_ELEVATED", observed)
    return _result(check, DiagnosticStatus.OK, "CLOCK_WITHIN_TOLERANCE", observed)


def evaluate_timezone(timezone_name: str | None, *, expected: str = "UTC") -> DiagnosticResult:
    check = DiagnosticCheck.TIMEZONE
    if not timezone_name:
        return _result(check, DiagnosticStatus.FAILED, "TIMEZONE_UNKNOWN")
    if timezone_name != expected:
        return _result(check, DiagnosticStatus.FAILED, "TIMEZONE_NOT_UTC", timezone_name)
    return _result(check, DiagnosticStatus.OK, "TIMEZONE_UTC", timezone_name)


def evaluate_disk_space(
    free_bytes: int | None,
    *,
    required_bytes: int,
    degraded_bytes: int,
) -> DiagnosticResult:
    """Free disk space against a hard floor and a degraded warning band."""

    check = DiagnosticCheck.DISK_SPACE
    if free_bytes is None:
        return _result(check, DiagnosticStatus.FAILED, "DISK_FREE_UNKNOWN")
    observed = f"{free_bytes}B"
    if free_bytes < required_bytes:
        return _result(check, DiagnosticStatus.FAILED, "DISK_BELOW_REQUIRED", observed)
    if free_bytes < degraded_bytes:
        return _result(check, DiagnosticStatus.DEGRADED, "DISK_LOW", observed)
    return _result(check, DiagnosticStatus.OK, "DISK_SUFFICIENT", observed)


def evaluate_memory(
    available_bytes: int | None,
    *,
    required_bytes: int,
    degraded_bytes: int,
) -> DiagnosticResult:
    check = DiagnosticCheck.MEMORY
    if available_bytes is None:
        return _result(check, DiagnosticStatus.FAILED, "MEMORY_UNKNOWN")
    observed = f"{available_bytes}B"
    if available_bytes < required_bytes:
        return _result(check, DiagnosticStatus.FAILED, "MEMORY_BELOW_REQUIRED", observed)
    if available_bytes < degraded_bytes:
        return _result(check, DiagnosticStatus.DEGRADED, "MEMORY_LOW", observed)
    return _result(check, DiagnosticStatus.OK, "MEMORY_SUFFICIENT", observed)


def evaluate_connectivity(reachable: bool | None, *, endpoint: str = "broker") -> DiagnosticResult:
    check = DiagnosticCheck.CONNECTIVITY
    if reachable is None:
        return _result(check, DiagnosticStatus.FAILED, "CONNECTIVITY_UNKNOWN", endpoint)
    if not reachable:
        return _result(check, DiagnosticStatus.FAILED, "ENDPOINT_UNREACHABLE", endpoint)
    return _result(check, DiagnosticStatus.OK, "ENDPOINT_REACHABLE", endpoint)


def evaluate_integrity(
    check: Literal[DiagnosticCheck.JOURNAL_INTEGRITY, DiagnosticCheck.STATE_INTEGRITY],
    *,
    present: bool,
    fingerprint_verified: bool | None,
) -> DiagnosticResult:
    """Durable-store integrity: a present store must verify its fingerprint.

    An absent store is OK on a clean host (nothing to recover). A present store
    whose verification result is unknown fails closed, and a failed verification
    is a corrupt-state condition requiring quarantine, never a silent overwrite.
    """

    if not present:
        return _result(check, DiagnosticStatus.OK, "STORE_ABSENT_CLEAN_HOST")
    if fingerprint_verified is None:
        return _result(check, DiagnosticStatus.FAILED, "INTEGRITY_UNKNOWN")
    if not fingerprint_verified:
        return _result(check, DiagnosticStatus.FAILED, "FINGERPRINT_MISMATCH_CORRUPT")
    return _result(check, DiagnosticStatus.OK, "FINGERPRINT_VERIFIED")
