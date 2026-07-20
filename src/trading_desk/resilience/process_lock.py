"""Exclusive process ownership with deterministic stale-lock handling.

A single desk process owns a durable lock file carrying its identity and a
heartbeat. A fresh, live lock held by another process refuses acquisition
(fail-closed on ambiguity). The same process re-acquiring is idempotent and
restart-safe. A lock whose heartbeat has expired — or whose owner is known dead —
is treated as stale and taken over, emitting a stale-lock incident. Ownership is
never inferred; staleness is decided from the injected clock and liveness signal.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Self

from pydantic import Field, field_validator, model_validator

from trading_desk.context.fingerprints import fingerprint
from trading_desk.resilience.diagnostics import ResilienceModel
from trading_desk.resilience.incidents import (
    IncidentCategory,
    IncidentRecord,
    IncidentSeverity,
    create_incident,
)


class LockOutcome(StrEnum):
    ACQUIRED = "ACQUIRED"
    REACQUIRED = "REACQUIRED"
    REFUSED_HELD = "REFUSED_HELD"
    TAKEOVER_STALE = "TAKEOVER_STALE"


class ProcessLock(ResilienceModel):
    lock_fingerprint: str = Field(min_length=64, max_length=64)
    pid: int = Field(gt=0)
    hostname: str = Field(min_length=1)
    started_at: datetime
    heartbeat_at: datetime

    @field_validator("started_at", "heartbeat_at")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("process lock timestamps must be timezone-aware UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def identity(self) -> Self:
        expected = fingerprint(self.model_dump(mode="python", exclude={"lock_fingerprint"}))
        if self.lock_fingerprint != expected:
            raise ValueError("process lock fingerprint mismatch")
        return self


class LockAcquisition(ResilienceModel):
    outcome: LockOutcome
    lock: ProcessLock
    previous: ProcessLock | None
    incident: IncidentRecord | None


def _make_lock(
    pid: int, hostname: str, started_at: datetime, heartbeat_at: datetime
) -> ProcessLock:
    draft_fields = {
        "lock_fingerprint": "0" * 64,
        "pid": pid,
        "hostname": hostname,
        "started_at": started_at,
        "heartbeat_at": heartbeat_at,
    }
    draft = ProcessLock.model_construct(**draft_fields)  # type: ignore[arg-type]
    fields = draft.model_dump(mode="python", exclude={"lock_fingerprint"})
    return ProcessLock.model_validate({**fields, "lock_fingerprint": fingerprint(fields)})


class ProcessLockError(RuntimeError):
    pass


class ProcessLockStore:
    """Durable single-owner lock backed by a fingerprinted JSON file."""

    def __init__(self, path: Path, *, heartbeat_ttl: timedelta = timedelta(minutes=2)) -> None:
        self.path = path
        self.heartbeat_ttl = heartbeat_ttl

    def read(self) -> ProcessLock | None:
        if not self.path.is_file():
            return None
        try:
            return ProcessLock.model_validate_json(self.path.read_text(encoding="utf-8"))
        except ValueError as error:
            raise ProcessLockError("persisted process lock is corrupt") from error

    def _write(self, lock: ProcessLock) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(lock.model_dump_json(indent=2), encoding="utf-8")
        temporary.replace(self.path)

    def acquire(
        self,
        *,
        pid: int,
        hostname: str,
        now: datetime,
        owner_alive: bool | None = None,
    ) -> LockAcquisition:
        existing = self.read()
        if existing is None:
            lock = _make_lock(pid, hostname, now, now)
            self._write(lock)
            return LockAcquisition(
                outcome=LockOutcome.ACQUIRED, lock=lock, previous=None, incident=None
            )

        if existing.pid == pid and existing.hostname == hostname:
            lock = _make_lock(pid, hostname, existing.started_at, now)
            self._write(lock)
            return LockAcquisition(
                outcome=LockOutcome.REACQUIRED, lock=lock, previous=existing, incident=None
            )

        expired = now - existing.heartbeat_at > self.heartbeat_ttl
        stale = expired or owner_alive is False
        if not stale:
            return LockAcquisition(
                outcome=LockOutcome.REFUSED_HELD,
                lock=existing,
                previous=existing,
                incident=None,
            )

        lock = _make_lock(pid, hostname, now, now)
        self._write(lock)
        incident = create_incident(
            category=IncidentCategory.STALE_LOCK_CLEARED,
            severity=IncidentSeverity.WARNING,
            detected_at=now,
            source="process_lock",
            summary="took over a stale process lock",
            recommended_action="confirm the prior owner is not running before continuing",
            requires_human_clearance=False,
            safe_details=(
                ("previous_pid", str(existing.pid)),
                ("previous_host", existing.hostname),
                ("reason", "HEARTBEAT_EXPIRED" if expired else "OWNER_REPORTED_DEAD"),
            ),
        )
        return LockAcquisition(
            outcome=LockOutcome.TAKEOVER_STALE, lock=lock, previous=existing, incident=incident
        )

    def refresh(self, *, pid: int, hostname: str, now: datetime) -> ProcessLock:
        existing = self.read()
        if existing is None or existing.pid != pid or existing.hostname != hostname:
            raise ProcessLockError("cannot refresh a lock this process does not own")
        lock = _make_lock(pid, hostname, existing.started_at, now)
        self._write(lock)
        return lock

    def release(self, *, pid: int, hostname: str) -> None:
        existing = self.read()
        if existing is None:
            return
        if existing.pid != pid or existing.hostname != hostname:
            raise ProcessLockError("cannot release a lock this process does not own")
        self.path.unlink()
