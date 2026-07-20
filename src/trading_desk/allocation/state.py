"""Restart-safe persistence for portfolio decisions and reservations.

The store is append-only at batch granularity: a batch is persisted with its
decisions exactly once, re-persisting the identical batch is a no-op, and a
conflicting payload for an existing batch identity fails closed. Restart
reconstructs reservations from the persisted decisions without creating new
ones, so a crash between evaluation and Risk submission can never duplicate
proposals.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from trading_desk.allocation.models import PortfolioDecision, PortfolioDecisionType
from trading_desk.context.fingerprints import fingerprint


class PortfolioStateError(ValueError):
    """Raised when persisted portfolio state cannot be used safely."""


class PersistedBatch(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    schema_version: Literal["portfolio-batch-v1"] = "portfolio-batch-v1"
    batch_id: str = Field(min_length=64, max_length=64)
    state_snapshot_id: str = Field(min_length=64, max_length=64)
    configuration_fingerprint: str = Field(min_length=64, max_length=64)
    correlation_matrix_fingerprint: str | None = Field(default=None, min_length=64, max_length=64)
    decisions: tuple[PortfolioDecision, ...] = Field(min_length=1)
    batch_fingerprint: str = Field(min_length=64, max_length=64)

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if any(item.batch_id != self.batch_id for item in self.decisions):
            raise ValueError("persisted decisions must belong to the batch")
        expected = fingerprint(self.model_dump(mode="python", exclude={"batch_fingerprint"}))
        if self.batch_fingerprint != expected:
            raise ValueError("persisted batch fingerprint mismatch")
        return self


def create_persisted_batch(**values: object) -> PersistedBatch:
    draft_fields = {**values, "batch_fingerprint": "0" * 64}
    draft = PersistedBatch.model_construct(**draft_fields)  # type: ignore[arg-type]
    fields = draft.model_dump(mode="python", exclude={"batch_fingerprint"})
    return PersistedBatch.model_validate({**fields, "batch_fingerprint": fingerprint(fields)})


class PortfolioStateStore:
    """Atomic JSON store of persisted batches keyed by batch identity."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def _load_raw(self) -> dict[str, dict[str, object]]:
        if not self.path.is_file():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise PortfolioStateError(f"portfolio state store is corrupt: {error}") from error
        if not isinstance(payload, dict):
            raise PortfolioStateError("portfolio state store has an invalid shape")
        return payload

    def load(self) -> tuple[PersistedBatch, ...]:
        batches: list[PersistedBatch] = []
        for batch_id, raw in sorted(self._load_raw().items()):
            batch = PersistedBatch.model_validate(raw)
            if batch.batch_id != batch_id:
                raise PortfolioStateError("portfolio state store key mismatch")
            batches.append(batch)
        return tuple(batches)

    def persist(self, batch: PersistedBatch) -> bool:
        """Persist one batch; returns False when it was already stored.

        Identical re-persistence is idempotent; a different payload under the
        same batch identity is tampering or a logic fault and fails closed.
        """

        raw = self._load_raw()
        existing = raw.get(batch.batch_id)
        incoming = json.loads(batch.model_dump_json())
        if existing is not None:
            if existing != incoming:
                raise PortfolioStateError("conflicting payload for an already persisted batch")
            return False
        raw[batch.batch_id] = incoming
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(raw, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, self.path)
        return True

    def open_reservations(self) -> tuple[PortfolioDecision, ...]:
        """Accepted decisions reconstructed for restart-safe reservation state."""

        accepted: list[PortfolioDecision] = []
        for batch in self.load():
            accepted.extend(
                item for item in batch.decisions if item.decision is PortfolioDecisionType.ACCEPT
            )
        return tuple(accepted)
