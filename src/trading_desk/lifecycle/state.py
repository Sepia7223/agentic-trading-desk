"""Atomic persistent lifecycle replay state and exclusive process lock."""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from trading_desk.lifecycle.errors import LifecycleStateError
from trading_desk.lifecycle.fingerprints import fingerprint
from trading_desk.lifecycle.idempotency import LifecycleIdempotencySnapshot
from trading_desk.lifecycle.models import LifecycleJournalRecord


class LifecyclePersistentState(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int = 1
    idempotency: LifecycleIdempotencySnapshot = Field(default_factory=LifecycleIdempotencySnapshot)
    journal_records: tuple[LifecycleJournalRecord, ...] = ()
    daily_close_counts: tuple[tuple[date, int], ...] = ()
    last_close_timestamp: datetime | None = None
    unresolved_close_states: tuple[str, ...] = ()
    reconciliation_mismatches: tuple[str, ...] = ()
    automatic_lifecycle_halt: bool = False
    halt_reason: str | None = None
    state_fingerprint: str = Field(min_length=64, max_length=64)

    @field_validator("last_close_timestamp")
    @classmethod
    def utc_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is not None and (
            value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value)
        ):
            raise ValueError("lifecycle state timestamp must be UTC")
        return value

    @model_validator(mode="after")
    def validate_integrity(self) -> Self:
        expected = fingerprint(self.model_dump(mode="python", exclude={"state_fingerprint"}))
        if self.state_fingerprint != expected:
            raise ValueError("lifecycle state fingerprint is invalid")
        previous: str | None = None
        for sequence, record in enumerate(self.journal_records, start=1):
            if record.sequence != sequence or record.previous_record_fingerprint != previous:
                raise ValueError("persisted lifecycle journal chain is invalid")
            previous = record.record_fingerprint
        return self


def initial_state() -> LifecyclePersistentState:
    fields = {
        "schema_version": 1,
        "idempotency": LifecycleIdempotencySnapshot(),
        "journal_records": (),
        "daily_close_counts": (),
        "last_close_timestamp": None,
        "unresolved_close_states": (),
        "reconciliation_mismatches": (),
        "automatic_lifecycle_halt": False,
        "halt_reason": None,
    }
    return LifecyclePersistentState.model_validate(
        {**fields, "state_fingerprint": fingerprint(fields)}
    )


def update_state(state: LifecyclePersistentState, **updates: object) -> LifecyclePersistentState:
    fields = state.model_dump(mode="python", exclude={"state_fingerprint"})
    fields.update(updates)
    return LifecyclePersistentState.model_validate(
        {**fields, "state_fingerprint": fingerprint(fields)}
    )


class LifecycleStateStore:
    _MAX_LOCK_AGE_SECONDS = 24 * 60 * 60

    def __init__(self, path: Path) -> None:
        self.path = path

    def acquire_lock(self) -> int:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock = self.path.with_suffix(self.path.suffix + ".lock")
        for attempt in range(2):
            try:
                descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(
                    descriptor,
                    json.dumps({"pid": os.getpid(), "created_at": time.time()}).encode(),
                )
                os.fsync(descriptor)
                return descriptor
            except FileExistsError:
                if attempt or not self._reclaimable(lock):
                    raise LifecycleStateError(
                        "lifecycle state is locked; refusing concurrent monitor"
                    ) from None
                lock.unlink(missing_ok=True)
        raise LifecycleStateError("lifecycle lock could not be acquired")

    def release_lock(self, descriptor: int) -> None:
        os.close(descriptor)
        self.path.with_suffix(self.path.suffix + ".lock").unlink(missing_ok=True)

    def load(self) -> LifecyclePersistentState:
        if not self.path.exists():
            return initial_state()
        try:
            return LifecyclePersistentState.model_validate_json(
                self.path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as error:
            raise LifecycleStateError("lifecycle state could not be validated") from error

    def save(self, state: LifecyclePersistentState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(state.model_dump_json(indent=2), encoding="utf-8")
        temporary.replace(self.path)

    def _reclaimable(self, lock: Path) -> bool:
        try:
            metadata = json.loads(lock.read_text(encoding="utf-8"))
            pid = int(metadata["pid"])
            created_at = float(metadata["created_at"])
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            return False
        return (time.time() - created_at) > self._MAX_LOCK_AGE_SECONDS or not _pid_exists(pid)


def _pid_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        return True
    return True
