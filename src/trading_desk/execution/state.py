"""Atomic local persistence for automated Demo integrity and replay state."""

from __future__ import annotations

import json
import os
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
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def exists(self) -> bool:
        return self.path.is_file()

    def acquire_lock(self) -> int:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        try:
            return os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            raise RuntimeError("automated Demo state is locked; refusing concurrent run") from None

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
