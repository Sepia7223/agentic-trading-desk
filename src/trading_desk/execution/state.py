"""Atomic local persistence for automated Demo integrity and replay state."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator

from trading_desk.execution.automated import AutomatedDemoState
from trading_desk.execution.fingerprints import fingerprint
from trading_desk.execution.idempotency import IdempotencySnapshot
from trading_desk.execution.models import ExecutionJournalRecord


class AutomatedDemoSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    state: AutomatedDemoState
    idempotency: IdempotencySnapshot
    journal_records: tuple[ExecutionJournalRecord, ...]
    snapshot_fingerprint: str

    @model_validator(mode="after")
    def validate_integrity(self) -> Self:
        previous: str | None = None
        for sequence, record in enumerate(self.journal_records, start=1):
            if record.sequence != sequence or record.previous_record_fingerprint != previous:
                raise ValueError("persisted execution journal chain is invalid")
            previous = record.record_fingerprint
        expected = fingerprint(self.model_dump(mode="python", exclude={"snapshot_fingerprint"}))
        if self.snapshot_fingerprint != expected:
            raise ValueError("automated Demo snapshot fingerprint is invalid")
        return self


class AutomatedDemoStateStore:
    _MAX_LOCK_AGE_SECONDS = 24 * 60 * 60

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def exists(self) -> bool:
        return self.path.is_file()

    def acquire_lock(self) -> int:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        for attempt in range(2):
            try:
                descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                metadata = json.dumps({"pid": os.getpid(), "created_at": time.time()})
                os.write(descriptor, metadata.encode("utf-8"))
                os.fsync(descriptor)
                return descriptor
            except FileExistsError:
                if attempt or not self._lock_is_reclaimable(lock_path):
                    raise RuntimeError(
                        "automated Demo state is locked; refusing concurrent run"
                    ) from None
                lock_path.unlink(missing_ok=True)
        raise RuntimeError("automated Demo state lock could not be acquired")

    def _lock_is_reclaimable(self, lock_path: Path) -> bool:
        try:
            metadata = json.loads(lock_path.read_text(encoding="utf-8"))
            pid = int(metadata["pid"])
            created_at = float(metadata["created_at"])
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            return True
        return (time.time() - created_at) > self._MAX_LOCK_AGE_SECONDS or not _pid_exists(pid)

    def release_lock(self, descriptor: int) -> None:
        lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        os.close(descriptor)
        lock_path.unlink(missing_ok=True)

    def load(self) -> AutomatedDemoSnapshot:
        return AutomatedDemoSnapshot.model_validate_json(self.path.read_text(encoding="utf-8"))

    def save(
        self,
        state: AutomatedDemoState,
        idempotency: IdempotencySnapshot,
        records: tuple[ExecutionJournalRecord, ...],
    ) -> AutomatedDemoSnapshot:
        fields = {
            "state": state,
            "idempotency": idempotency,
            "journal_records": records,
        }
        snapshot = AutomatedDemoSnapshot.model_validate(
            {**fields, "snapshot_fingerprint": fingerprint(fields)}
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(snapshot.model_dump(mode="json"), indent=2), encoding="utf-8"
        )
        temporary.replace(self.path)
        return snapshot


def _pid_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True
