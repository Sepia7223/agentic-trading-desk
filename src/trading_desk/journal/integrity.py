"""Typed verification of schema, chains, payloads, parents, and amendments."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from trading_desk.journal.fingerprints import decode_json, fingerprint
from trading_desk.journal.migrations import database_version
from trading_desk.journal.models import (
    IntegrityFinding,
    IntegrityReport,
    IntegrityStatus,
    JournalRecord,
    JournalRecordType,
)


def verify_connection(connection: sqlite3.Connection, supported_schema: int) -> IntegrityReport:
    findings: list[IntegrityFinding] = []
    version = database_version(connection)
    if version > supported_schema:
        return IntegrityReport(
            status=IntegrityStatus.UNSUPPORTED_SCHEMA,
            schema_version=version,
            records_checked=0,
            findings=(
                IntegrityFinding(
                    code="UNSUPPORTED_SCHEMA",
                    message="database schema is newer than this application supports",
                ),
            ),
            verified_at=datetime.now(UTC),
        )
    try:
        quick = connection.execute("PRAGMA quick_check").fetchone()
        if not quick or str(quick[0]).lower() != "ok":
            findings.append(
                IntegrityFinding(code="SQLITE_INTEGRITY", message="SQLite integrity check failed")
            )
        foreign = connection.execute("PRAGMA foreign_key_check").fetchall()
        if foreign:
            findings.append(
                IntegrityFinding(code="FOREIGN_KEY", message="foreign-key violations exist")
            )
        rows = connection.execute(
            "SELECT * FROM journal_records ORDER BY sequence_number"
        ).fetchall()
    except sqlite3.DatabaseError:
        return IntegrityReport(
            status=IntegrityStatus.RECOVERY_REQUIRED,
            schema_version=version,
            records_checked=0,
            findings=(
                IntegrityFinding(
                    code="DATABASE_CORRUPTION", message="journal cannot be read safely"
                ),
            ),
            verified_at=datetime.now(UTC),
        )
    previous: str | None = None
    source_ids: set[str] = set()
    journal_ids: set[str] = set()
    records: list[JournalRecord] = []
    for expected_sequence, row in enumerate(rows, start=1):
        record_id = str(row["journal_record_id"])
        if int(row["sequence_number"]) != expected_sequence:
            findings.append(_finding("INVALID_SEQUENCE", "sequence is not contiguous", record_id))
        if row["previous_record_fingerprint"] != previous:
            findings.append(
                _finding("BROKEN_CHAIN", "previous fingerprint does not match", record_id)
            )
        try:
            payload = decode_json(str(row["payload_json"]))
            if fingerprint(payload) != row["payload_fingerprint"]:
                findings.append(
                    _finding("PAYLOAD_MISMATCH", "payload fingerprint differs", record_id)
                )
            if fingerprint(payload) != row["source_fingerprint"]:
                findings.append(
                    _finding("SOURCE_MISMATCH", "source fingerprint differs", record_id)
                )
            record = _validate_row(row, payload)
            records.append(record)
        except Exception:
            findings.append(_finding("INVALID_RECORD", "record envelope is invalid", record_id))
        source_identity = f"{row['record_type']}:{row['source_record_id']}"
        if source_identity in source_ids:
            findings.append(
                _finding("DUPLICATE_SOURCE", "source identity is duplicated", record_id)
            )
        source_ids.add(source_identity)
        if record_id in journal_ids:
            findings.append(_finding("DUPLICATE_JOURNAL_ID", "journal ID is duplicated", record_id))
        journal_ids.add(record_id)
        previous = str(row["journal_record_fingerprint"])
    known_sources = {record.source_record_id for record in records}
    atomic_groups: dict[str, list[JournalRecord]] = {}
    for record in records:
        if record.atomic_group_id:
            atomic_groups.setdefault(record.atomic_group_id, []).append(record)
        for parent in record.source_parent_ids:
            if parent not in known_sources and not record.deferred_linkage:
                findings.append(
                    _finding("MISSING_PARENT", "source parent is missing", record.journal_record_id)
                )
        if record.record_type is JournalRecordType.AMENDMENT:
            target = record.payload.get("target_journal_record_id")
            if target not in journal_ids:
                findings.append(
                    _finding(
                        "ORPHAN_AMENDMENT", "amendment target is missing", record.journal_record_id
                    )
                )
    for group_id, group in atomic_groups.items():
        expected_size = group[0].atomic_group_size or 0
        indexes = {record.atomic_group_index for record in group}
        if len(group) != expected_size or indexes != set(range(1, expected_size + 1)):
            findings.append(
                IntegrityFinding(
                    code="INCOMPLETE_ATOMIC_GROUP",
                    message="atomic journal group is incomplete",
                    journal_record_id=group_id,
                )
            )
    status = (
        IntegrityStatus.INVALID
        if any(item.blocking for item in findings)
        else (IntegrityStatus.WARNINGS if findings else IntegrityStatus.VALID)
    )
    return IntegrityReport(
        status=status,
        schema_version=version,
        records_checked=len(rows),
        findings=tuple(findings),
        verified_at=datetime.now(UTC),
    )


def _validate_row(row: sqlite3.Row, payload: dict[str, object]) -> JournalRecord:
    return JournalRecord.model_validate(
        {
            "journal_record_id": row["journal_record_id"],
            "sequence_number": row["sequence_number"],
            "record_type": row["record_type"],
            "source_record_id": row["source_record_id"],
            "source_parent_ids": tuple(decode_json(row["source_parent_ids_json"])),
            "created_at": row["created_at"],
            "effective_at": row["effective_at"],
            "trading_day": row["trading_day"],
            "instrument": row["instrument"],
            "epic": row["epic"],
            "strategy_variant": row["strategy_variant"],
            "environment": row["environment"],
            "schema_version": row["schema_version"],
            "record_version": row["record_version"],
            "source_fingerprint": row["source_fingerprint"],
            "payload_fingerprint": row["payload_fingerprint"],
            "previous_record_fingerprint": row["previous_record_fingerprint"],
            "journal_record_fingerprint": row["journal_record_fingerprint"],
            "payload": payload,
            "deferred_linkage": bool(row["deferred_linkage"]),
            "atomic_group_id": row["atomic_group_id"],
            "atomic_group_index": row["atomic_group_index"],
            "atomic_group_size": row["atomic_group_size"],
        }
    )


def _finding(code: str, message: str, record_id: str) -> IntegrityFinding:
    return IntegrityFinding(code=code, message=message, journal_record_id=record_id)
