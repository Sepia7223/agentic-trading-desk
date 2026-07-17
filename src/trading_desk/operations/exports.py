"""In-memory bounded exports of sanitized read-only projections."""

import csv
import io
from enum import StrEnum

from trading_desk.operations.models import RecordProjection


class OperationsExportFormat(StrEnum):
    JSONL = "jsonl"
    CSV = "csv"
    MARKDOWN = "markdown"


def export_records(
    records: tuple[RecordProjection, ...], export_format: OperationsExportFormat
) -> tuple[str, str, str]:
    if export_format is OperationsExportFormat.JSONL:
        content = "\n".join(item.model_dump_json() for item in records) + ("\n" if records else "")
        return content, "application/x-ndjson", "operations-export.jsonl"
    if export_format is OperationsExportFormat.CSV:
        stream = io.StringIO(newline="")
        writer = csv.writer(stream)
        writer.writerow(
            ("effective_at", "record_type", "source_record_id", "instrument", "environment")
        )
        for item in records:
            writer.writerow(
                (
                    item.effective_at.isoformat(),
                    _cell(item.record_type),
                    _cell(item.source_record_id),
                    _cell(item.instrument or ""),
                    _cell(item.environment),
                )
            )
        return stream.getvalue(), "text/csv; charset=utf-8", "operations-export.csv"
    lines = [
        "# Operations Center Export",
        "",
        "Read-only sanitized journal projections.",
        "",
        "| UTC timestamp | Type | Source | Instrument | Environment |",
        "|---|---|---|---|---|",
    ]
    lines.extend(
        f"| {_markdown(item.effective_at.isoformat())} | {_markdown(item.record_type)} | "
        f"{_markdown(item.source_record_id)} | {_markdown(item.instrument or '')} | "
        f"{_markdown(item.environment)} |"
        for item in records
    )
    return "\n".join(lines) + "\n", "text/markdown; charset=utf-8", "operations-export.md"


def _cell(value: str) -> str:
    return f"'{value}" if value.startswith(("=", "+", "-", "@")) else value


def _markdown(value: str) -> str:
    return value.replace("|", "\\|").replace("\r", " ").replace("\n", " ")
