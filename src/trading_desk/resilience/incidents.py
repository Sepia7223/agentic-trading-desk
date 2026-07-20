"""Structured, immutable, fingerprinted incident records.

Incident records are append-only evidence of resilience events (crash recovery,
reconciliation mismatch, corrupt state, stale lock, diagnostic failure, ambiguous
mutation). They carry only sanitized detail: a validator rejects any field that
would leak a credential or raw broker payload, so incident evidence is safe to
persist and commit.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Self

from pydantic import Field, field_validator, model_validator

from trading_desk.context.fingerprints import fingerprint
from trading_desk.resilience.diagnostics import ResilienceModel

_FORBIDDEN_DETAIL_KEYS = frozenset(
    {
        "password",
        "authorization",
        "token",
        "secret",
        "api_key",
        "apikey",
        "access_token",
        "refresh_token",
        "cst",
        "x-security-token",
        "identifier",
    }
)


class IncidentCategory(StrEnum):
    STARTUP_PREFLIGHT_FAILED = "STARTUP_PREFLIGHT_FAILED"
    CRASH_RECOVERY = "CRASH_RECOVERY"
    RECONCILIATION_MISMATCH = "RECONCILIATION_MISMATCH"
    CORRUPT_STATE_QUARANTINED = "CORRUPT_STATE_QUARANTINED"
    STALE_LOCK_CLEARED = "STALE_LOCK_CLEARED"
    DIAGNOSTIC_FAILURE = "DIAGNOSTIC_FAILURE"
    AMBIGUOUS_MUTATION_HALT = "AMBIGUOUS_MUTATION_HALT"
    BACKUP_RESTORED = "BACKUP_RESTORED"
    HOST_MIGRATION = "HOST_MIGRATION"


class IncidentSeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class IncidentRecord(ResilienceModel):
    incident_id: str = Field(min_length=64, max_length=64)
    category: IncidentCategory
    severity: IncidentSeverity
    detected_at: datetime
    source: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    safe_details: tuple[tuple[str, str], ...] = ()
    recommended_action: str = Field(min_length=1)
    requires_human_clearance: bool

    @field_validator("detected_at")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("incident timestamps must be timezone-aware UTC")
        return value.astimezone(UTC)

    @field_validator("safe_details")
    @classmethod
    def no_sensitive_details(
        cls, value: tuple[tuple[str, str], ...]
    ) -> tuple[tuple[str, str], ...]:
        for key, _ in value:
            if key.strip().lower() in _FORBIDDEN_DETAIL_KEYS:
                raise ValueError(f"incident detail key is not permitted: {key}")
        return value

    @model_validator(mode="after")
    def identity(self) -> Self:
        expected = fingerprint(self.model_dump(mode="python", exclude={"incident_id"}))
        if self.incident_id != expected:
            raise ValueError("incident record fingerprint mismatch")
        return self


def create_incident(
    *,
    category: IncidentCategory,
    severity: IncidentSeverity,
    detected_at: datetime,
    source: str,
    summary: str,
    recommended_action: str,
    requires_human_clearance: bool,
    safe_details: tuple[tuple[str, str], ...] = (),
) -> IncidentRecord:
    """Build a fingerprinted incident record with deterministic detail ordering."""

    ordered_details = tuple(sorted(safe_details))
    draft_fields = {
        "incident_id": "0" * 64,
        "category": category,
        "severity": severity,
        "detected_at": detected_at,
        "source": source,
        "summary": summary,
        "safe_details": ordered_details,
        "recommended_action": recommended_action,
        "requires_human_clearance": requires_human_clearance,
    }
    draft = IncidentRecord.model_construct(**draft_fields)  # type: ignore[arg-type]
    fields = draft.model_dump(mode="python", exclude={"incident_id"})
    return IncidentRecord.model_validate({**fields, "incident_id": fingerprint(fields)})
