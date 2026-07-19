"""Append-only, hash-chained experiment registry with tamper detection."""

from __future__ import annotations

from pathlib import Path

from trading_desk.research.models import ExperimentRecord


class ResearchRegistryError(ValueError):
    """Raised when the experiment registry cannot be used safely."""


class ExperimentRegistry:
    """JSONL registry: every record links its predecessor's identifier.

    Records are immutable once appended; failed and cancelled experiments are
    retained exactly like completed ones. The chain is verified on every load
    and every append, so local edits or deletions are detected.
    """

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> tuple[ExperimentRecord, ...]:
        if not self.path.is_file():
            return ()
        records: list[ExperimentRecord] = []
        for line_number, line in enumerate(
            self.path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line.strip():
                continue
            try:
                record = ExperimentRecord.model_validate_json(line)
            except ValueError as error:
                raise ResearchRegistryError(
                    f"registry line {line_number} failed validation: {error}"
                ) from error
            expected_parent = records[-1].record_id if records else None
            if record.previous_record_id != expected_parent:
                raise ResearchRegistryError(f"registry chain break at line {line_number}")
            records.append(record)
        return tuple(records)

    def append(self, record: ExperimentRecord) -> None:
        existing = self.load()
        expected_parent = existing[-1].record_id if existing else None
        if record.previous_record_id != expected_parent:
            raise ResearchRegistryError("record does not extend the registry head")
        if any(item.record_id == record.record_id for item in existing):
            raise ResearchRegistryError("duplicate experiment record identity")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(record.model_dump_json() + "\n")

    def head(self) -> str | None:
        records = self.load()
        return records[-1].record_id if records else None
