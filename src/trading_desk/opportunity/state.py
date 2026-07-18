"""Atomic restart-safe Opportunity cycle state and exclusive lock."""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from trading_desk.opportunity.errors import OpportunityStateError
from trading_desk.opportunity.fingerprints import fingerprint


class OpportunityPersistentState(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: int = 1
    completed_cycle_ids: tuple[str, ...] = ()
    completed_evaluation_keys: tuple[str, ...] = ()
    candidate_fingerprints: tuple[str, ...] = ()
    last_completed_bars: tuple[tuple[str, str, datetime], ...] = ()
    recently_closed_positions: tuple[tuple[str, datetime], ...] = ()
    fair_schedule_cursor: int = 0
    missed_evaluation_count: int = 0
    last_cycle_timestamp: datetime | None = None
    entries_halted: bool = False
    halt_reasons: tuple[str, ...] = ()
    configuration_fingerprint: str | None = None
    state_fingerprint: str = Field(min_length=64, max_length=64)

    @field_validator("last_cycle_timestamp")
    @classmethod
    def utc(cls, value: datetime | None) -> datetime | None:
        if value is not None and (
            value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value)
        ):
            raise ValueError("opportunity state timestamp must be UTC")
        return value

    @model_validator(mode="after")
    def identity(self) -> Self:
        expected = fingerprint(self.model_dump(mode="python", exclude={"state_fingerprint"}))
        if self.state_fingerprint != expected:
            raise ValueError("opportunity state fingerprint mismatch")
        return self


def initial_state() -> OpportunityPersistentState:
    fields = {
        "schema_version": 1,
        "completed_cycle_ids": (),
        "completed_evaluation_keys": (),
        "candidate_fingerprints": (),
        "last_completed_bars": (),
        "recently_closed_positions": (),
        "fair_schedule_cursor": 0,
        "missed_evaluation_count": 0,
        "last_cycle_timestamp": None,
        "entries_halted": False,
        "halt_reasons": (),
        "configuration_fingerprint": None,
    }
    return OpportunityPersistentState.model_validate(
        {**fields, "state_fingerprint": fingerprint(fields)}
    )


def update_state(
    state: OpportunityPersistentState, **updates: object
) -> OpportunityPersistentState:
    fields = state.model_dump(mode="python", exclude={"state_fingerprint"})
    fields.update(updates)
    return OpportunityPersistentState.model_validate(
        {**fields, "state_fingerprint": fingerprint(fields)}
    )


class OpportunityStateStore:
    _MAX_LOCK_AGE_SECONDS = 3600

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
                    raise OpportunityStateError("opportunity cycle lock is active") from None
                lock.unlink(missing_ok=True)
        raise OpportunityStateError("opportunity lock could not be acquired")

    def release_lock(self, descriptor: int) -> None:
        os.close(descriptor)
        self.path.with_suffix(self.path.suffix + ".lock").unlink(missing_ok=True)

    def load(self) -> OpportunityPersistentState:
        if not self.path.exists():
            return initial_state()
        try:
            return OpportunityPersistentState.model_validate_json(
                self.path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as error:
            raise OpportunityStateError("opportunity state could not be validated") from error

    def save(self, state: OpportunityPersistentState) -> None:
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
        return time.time() - created_at > self._MAX_LOCK_AGE_SECONDS or not _pid_exists(pid)


def _pid_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        return True
    return True
