"""Sanitized journal-to-operations projections."""

from __future__ import annotations

import re
from collections.abc import Mapping

from trading_desk.journal.models import JournalRecord
from trading_desk.operations.models import RecordProjection

_SECRET_KEYS = re.compile(
    r"(?i)(password|api[_-]?key|access[_-]?token|refresh[_-]?token|authorization|cst|"
    r"x-security-token|headers|raw_response)"
)
_PATH = re.compile(r"(?:[A-Za-z]:[\\/]|/(?:Users|home|etc|var|tmp)/|\\\\)")


def project_record(record: JournalRecord) -> RecordProjection:
    return RecordProjection(
        journal_record_id=record.journal_record_id,
        source_record_id=record.source_record_id,
        source_parent_ids=record.source_parent_ids,
        atomic_group_id=record.atomic_group_id,
        record_type=record.record_type.value,
        effective_at=record.effective_at,
        instrument=record.instrument,
        epic=record.epic,
        strategy_variant=record.strategy_variant,
        environment=record.environment,
        payload=sanitize_mapping(record.payload),
        record_fingerprint=record.journal_record_fingerprint,
    )


def safe_reference(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return "***" if len(text) <= 4 else f"***{text[-4:]}"


def sanitize_mapping(value: Mapping[str, object]) -> dict[str, object]:
    return {
        str(key): _sanitize(item)
        for key, item in value.items()
        if not _SECRET_KEYS.search(str(key))
    }


def _sanitize(value: object) -> object:
    if isinstance(value, Mapping):
        return sanitize_mapping(value)
    if isinstance(value, (tuple, list)):
        return tuple(_sanitize(item) for item in value)
    if isinstance(value, str) and _PATH.search(value):
        return "[REDACTED]"
    return value
