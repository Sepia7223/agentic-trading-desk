"""Bounded deterministic JSONL, CSV, and Markdown journal exports."""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from trading_desk.journal.config import JournalConfiguration
from trading_desk.journal.errors import JournalExportError
from trading_desk.journal.fingerprints import to_primitive
from trading_desk.journal.models import ExportFormat, ExportResult, JournalQuery, JournalRecord

if TYPE_CHECKING:
    from trading_desk.ports.journal import JournalReader


def export_records(
    reader: JournalReader,
    configuration: JournalConfiguration,
    query: JournalQuery,
    *,
    output_path: Path,
    export_format: ExportFormat,
) -> ExportResult:
    if not output_path.parent.exists():
        raise JournalExportError("export parent directory must already exist")
    result = reader.query(query)
    timestamp = datetime.now(UTC)
    metadata = {
        "schema_version": configuration.schema_version,
        "configuration_fingerprint": configuration.configuration_fingerprint,
        "query_fingerprint": result.query_fingerprint,
        "export_timestamp": timestamp.isoformat(),
        "source_record_count": len(result.records),
    }
    try:
        if export_format is ExportFormat.JSONL:
            _jsonl(output_path, metadata, result.records)
        elif export_format is ExportFormat.CSV:
            _csv(output_path, metadata, result.records)
        else:
            _markdown(output_path, metadata, result.records)
    except Exception as exc:
        output_path.unlink(missing_ok=True)
        raise JournalExportError("sanitized journal export failed") from exc
    checksum = hashlib.sha256(output_path.read_bytes()).hexdigest()
    return ExportResult(
        path=output_path,
        format=export_format,
        schema_version=configuration.schema_version,
        configuration_fingerprint=configuration.configuration_fingerprint,
        query_fingerprint=result.query_fingerprint,
        export_timestamp=timestamp,
        source_record_count=len(result.records),
        checksum=checksum,
    )


def _jsonl(path: Path, metadata: dict[str, object], records: tuple[JournalRecord, ...]) -> None:
    lines = [json.dumps({"metadata": metadata}, sort_keys=True)]
    lines.extend(
        json.dumps(to_primitive(record), sort_keys=True, separators=(",", ":"))
        for record in records
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _csv(path: Path, metadata: dict[str, object], records: tuple[JournalRecord, ...]) -> None:
    fields = (
        "schema_version",
        "configuration_fingerprint",
        "query_fingerprint",
        "export_timestamp",
        "source_record_count",
        "journal_record_id",
        "record_type",
        "source_record_id",
        "effective_at",
        "instrument",
        "epic",
        "environment",
        "payload_fingerprint",
    )
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for record in records:
            writer.writerow(
                {
                    **{key: metadata[key] for key in fields[:5]},
                    "journal_record_id": record.journal_record_id,
                    "record_type": record.record_type.value,
                    "source_record_id": record.source_record_id,
                    "effective_at": record.effective_at.isoformat(),
                    "instrument": record.instrument,
                    "epic": record.epic,
                    "environment": record.environment,
                    "payload_fingerprint": record.payload_fingerprint,
                }
            )


def _markdown(path: Path, metadata: dict[str, object], records: tuple[JournalRecord, ...]) -> None:
    lines = [
        "# Journal Export",
        "",
        *(f"- {key}: `{value}`" for key, value in metadata.items()),
        "",
        "| Sequence | Type | Source | Effective At | Instrument |",
        "|---:|---|---|---|---|",
    ]
    lines.extend(
        f"| {record.sequence_number} | {record.record_type.value} | "
        f"{record.source_record_id} | {record.effective_at.isoformat()} | "
        f"{record.instrument or ''} |"
        for record in records
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
