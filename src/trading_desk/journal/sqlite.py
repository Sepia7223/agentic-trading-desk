"""SQLite implementation of the append-only journal repository."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from trading_desk.journal.config import JournalConfiguration
from trading_desk.journal.errors import (
    JournalDuplicateError,
    JournalIntegrityError,
    JournalParentMissingError,
    JournalReadOnlyRecoveryError,
)
from trading_desk.journal.fingerprints import (
    canonical_json,
    decode_json,
    reject_raw_provider_data,
)
from trading_desk.journal.integrity import verify_connection
from trading_desk.journal.migrations import database_version, migrate
from trading_desk.journal.models import (
    IntegrityReport,
    IntegrityStatus,
    JournalLineage,
    JournalQuery,
    JournalQueryResult,
    JournalRecord,
    JournalRecordType,
)

_REQUIRES_PARENT = frozenset(
    {
        JournalRecordType.APPROVED_TRADE_INTENT,
        JournalRecordType.RISK_DECISION,
        JournalRecordType.PAPER_FILL,
        JournalRecordType.PAPER_CLOSED_TRADE,
        JournalRecordType.PAPER_UNRESOLVED_POSITION,
        JournalRecordType.EXECUTION_REQUEST,
        JournalRecordType.EXECUTION_PREFLIGHT,
        JournalRecordType.OPERATOR_CONFIRMATION,
        JournalRecordType.BROKER_SUBMISSION,
        JournalRecordType.BROKER_CONFIRMATION,
        JournalRecordType.EXECUTION_RECONCILIATION,
        JournalRecordType.EXECUTION_FAILURE,
        JournalRecordType.AI_ANALYSIS,
        JournalRecordType.POST_TRADE_REVIEW,
        JournalRecordType.AMENDMENT,
    }
)
_DEFERRED_ALLOWED = frozenset(
    {
        JournalRecordType.BROKER_CONFIRMATION,
        JournalRecordType.EXECUTION_RECONCILIATION,
        JournalRecordType.AI_ANALYSIS,
        JournalRecordType.INTEGRITY_EVENT,
    }
)


class SQLiteJournalRepository:
    """Durable repository with append-only operations and deterministic reads."""

    def __init__(self, configuration: JournalConfiguration) -> None:
        self.configuration = configuration
        self._connection = _connect(configuration.database_path)
        self._closed = False
        self._recovery_read_only = False
        self._configure_connection()
        migrate(self._connection, configuration.schema_version)
        self._write_metadata()
        if configuration.verify_integrity_on_startup:
            report = self.verify()
            if report.status in {
                IntegrityStatus.INVALID,
                IntegrityStatus.RECOVERY_REQUIRED,
                IntegrityStatus.UNSUPPORTED_SCHEMA,
            }:
                self._recovery_read_only = True

    @property
    def schema_version(self) -> int:
        return database_version(self._connection)

    @property
    def recovery_read_only(self) -> bool:
        return self._recovery_read_only

    @property
    def connection(self) -> sqlite3.Connection:
        """Internal-support connection for backup and integrity services."""
        return self._connection

    def _configure_connection(self) -> None:
        self._connection.execute(
            f"PRAGMA busy_timeout = {self.configuration.busy_timeout_seconds * 1000}"
        )
        self._connection.execute(
            f"PRAGMA foreign_keys = {'ON' if self.configuration.enforce_foreign_keys else 'OFF'}"
        )
        if self.configuration.use_wal and self.configuration.database_path != Path(":memory:"):
            self._connection.execute("PRAGMA journal_mode = WAL")
        self._connection.execute(
            f"PRAGMA synchronous = {self.configuration.synchronous_mode.value}"
        )

    def _write_metadata(self) -> None:
        entries = (
            ("schema_version", str(self.configuration.schema_version)),
            ("configuration_fingerprint", self.configuration.configuration_fingerprint),
        )
        self._connection.executemany(
            "INSERT OR IGNORE INTO journal_metadata(key, value) VALUES (?, ?)", entries
        )
        self._connection.commit()

    def next_sequence(self) -> int:
        row = self._connection.execute(
            "SELECT COALESCE(MAX(sequence_number), 0) + 1 FROM journal_records"
        ).fetchone()
        return int(row[0])

    def latest_fingerprint(self) -> str | None:
        row = self._connection.execute(
            "SELECT journal_record_fingerprint FROM journal_records "
            "ORDER BY sequence_number DESC LIMIT 1"
        ).fetchone()
        return str(row[0]) if row else None

    def append(self, record: JournalRecord) -> JournalRecord:
        return self.append_batch((record,))[0]

    def append_batch(self, records: Sequence[JournalRecord]) -> tuple[JournalRecord, ...]:
        self._require_writable()
        items = tuple(records)
        if not items:
            return ()
        if len(items) > self.configuration.maximum_batch_size:
            raise ValueError("journal batch exceeds configured maximum")
        self._validate_batch_chain(items)
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            available_sources = self._existing_source_ids() | {
                item.source_record_id for item in items
            }
            for record in items:
                self._insert_record(record, available_sources)
            self._resolve_deferred_links()
            self._connection.commit()
        except sqlite3.IntegrityError as exc:
            self._connection.rollback()
            message = str(exc).lower()
            if "unique" in message:
                raise JournalDuplicateError("journal or source identity already exists") from exc
            raise JournalIntegrityError("journal batch violated database integrity") from exc
        except Exception:
            self._connection.rollback()
            raise
        return items

    def _validate_batch_chain(self, records: tuple[JournalRecord, ...]) -> None:
        sequence = self.next_sequence()
        previous = self.latest_fingerprint()
        for record in records:
            if record.sequence_number != sequence:
                raise JournalIntegrityError("journal sequence is not monotonic")
            if record.previous_record_fingerprint != previous:
                raise JournalIntegrityError("journal fingerprint chain does not continue")
            sequence += 1
            previous = record.journal_record_fingerprint

    def _insert_record(self, record: JournalRecord, available_sources: set[str]) -> None:
        if not self.configuration.store_raw_provider_responses:
            reject_raw_provider_data(record.payload)
        if record.record_type in _REQUIRES_PARENT and not record.source_parent_ids:
            raise JournalParentMissingError("journal record requires at least one source parent")
        missing = tuple(
            parent for parent in record.source_parent_ids if parent not in available_sources
        )
        if missing and not record.deferred_linkage:
            raise JournalParentMissingError("required journal source parent does not exist")
        if record.deferred_linkage and record.record_type not in _DEFERRED_ALLOWED:
            raise JournalParentMissingError(
                "deferred linkage is not permitted for this record type"
            )
        values = (
            record.sequence_number,
            record.journal_record_id,
            record.record_type.value,
            record.source_record_id,
            canonical_json(record.source_parent_ids),
            record.created_at.isoformat(),
            record.effective_at.isoformat(),
            record.trading_day.isoformat(),
            record.instrument,
            record.epic,
            record.strategy_variant,
            record.environment,
            record.schema_version,
            record.record_version,
            record.source_fingerprint,
            record.payload_fingerprint,
            record.previous_record_fingerprint,
            record.journal_record_fingerprint,
            canonical_json(record.payload),
            int(record.deferred_linkage),
            record.atomic_group_id,
            record.atomic_group_index,
            record.atomic_group_size,
        )
        self._connection.execute(
            "INSERT INTO journal_records VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            values,
        )
        for parent in record.source_parent_ids:
            parent_row = self._connection.execute(
                "SELECT journal_record_id FROM journal_records WHERE source_record_id = ? "
                "ORDER BY sequence_number LIMIT 1",
                (parent,),
            ).fetchone()
            self._connection.execute(
                "INSERT INTO journal_parent_links VALUES (?, ?, ?, ?)",
                (
                    record.journal_record_id,
                    parent,
                    str(parent_row[0]) if parent_row else None,
                    int(parent_row is None),
                ),
            )

    def _resolve_deferred_links(self) -> None:
        self._connection.execute(
            "UPDATE journal_parent_links SET parent_journal_record_id = "
            "(SELECT journal_record_id FROM journal_records r "
            "WHERE r.source_record_id = journal_parent_links.parent_source_record_id "
            "ORDER BY sequence_number LIMIT 1), deferred = 0 "
            "WHERE parent_journal_record_id IS NULL AND EXISTS "
            "(SELECT 1 FROM journal_records r "
            "WHERE r.source_record_id = journal_parent_links.parent_source_record_id)"
        )

    def _existing_source_ids(self) -> set[str]:
        return {
            str(row[0])
            for row in self._connection.execute("SELECT source_record_id FROM journal_records")
        }

    def get(self, journal_record_id: str) -> JournalRecord | None:
        row = self._connection.execute(
            "SELECT * FROM journal_records WHERE journal_record_id = ?", (journal_record_id,)
        ).fetchone()
        return _row_to_record(row) if row else None

    def get_by_source_id(self, source_record_id: str) -> tuple[JournalRecord, ...]:
        rows = self._connection.execute(
            "SELECT * FROM journal_records WHERE source_record_id = ? ORDER BY sequence_number",
            (source_record_id,),
        ).fetchall()
        return tuple(_row_to_record(row) for row in rows)

    def query(self, query: JournalQuery) -> JournalQueryResult:
        if query.limit > self.configuration.maximum_query_records:
            raise ValueError("query limit exceeds configured maximum")
        clauses, parameters = _sql_filters(query)
        rows = self._connection.execute(
            f"SELECT * FROM journal_records {clauses} ORDER BY sequence_number", parameters
        ).fetchall()
        records = tuple(
            record for row in rows if _payload_matches(record := _row_to_record(row), query)
        )
        total = len(records)
        page = records[query.offset : query.offset + query.limit]
        next_offset = query.offset + len(page) if query.offset + len(page) < total else None
        return JournalQueryResult(
            records=page,
            total_matches=total,
            next_offset=next_offset,
            query_fingerprint=query.query_fingerprint,
        )

    def lineage(self, source_record_id: str) -> JournalLineage:
        pending = [source_record_id]
        seen_sources: set[str] = set()
        found: dict[str, JournalRecord] = {}
        missing: set[str] = set()
        while pending:
            current = pending.pop()
            if current in seen_sources:
                continue
            seen_sources.add(current)
            direct = self.get_by_source_id(current)
            if not direct:
                by_journal = self.get(current)
                direct = (by_journal,) if by_journal else ()
            if not direct:
                missing.add(current)
                continue
            for record in direct:
                found[record.journal_record_id] = record
                pending.extend(record.source_parent_ids)
                child_rows = self._connection.execute(
                    "SELECT r.source_record_id FROM journal_parent_links p "
                    "JOIN journal_records r ON r.journal_record_id = p.child_journal_record_id "
                    "WHERE p.parent_source_record_id = ?",
                    (record.source_record_id,),
                ).fetchall()
                pending.extend(str(row[0]) for row in child_rows)
        ordered = tuple(sorted(found.values(), key=lambda item: item.sequence_number))
        return JournalLineage(
            requested_id=source_record_id,
            records=ordered,
            missing_parent_ids=tuple(sorted(missing - {source_record_id})),
        )

    def verify(self) -> IntegrityReport:
        return verify_connection(self._connection, self.configuration.schema_version)

    def close(self) -> None:
        if not self._closed:
            self._connection.close()
            self._closed = True

    def __enter__(self) -> SQLiteJournalRepository:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _require_writable(self) -> None:
        if self._closed:
            raise JournalIntegrityError("journal repository is closed")
        if self._recovery_read_only:
            raise JournalReadOnlyRecoveryError("journal is in read-only recovery mode")


def _connect(path: Path) -> sqlite3.Connection:
    if path != Path(":memory:") and not path.parent.exists():
        raise ValueError("journal database parent directory must already exist")
    connection = sqlite3.connect(str(path), isolation_level=None)
    connection.row_factory = sqlite3.Row
    return connection


def _row_to_record(row: sqlite3.Row) -> JournalRecord:
    return JournalRecord.model_validate(
        {
            "sequence_number": row["sequence_number"],
            "journal_record_id": row["journal_record_id"],
            "record_type": row["record_type"],
            "source_record_id": row["source_record_id"],
            "source_parent_ids": tuple(decode_json(row["source_parent_ids_json"])),
            "created_at": datetime.fromisoformat(row["created_at"]),
            "effective_at": datetime.fromisoformat(row["effective_at"]),
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
            "payload": decode_json(row["payload_json"]),
            "deferred_linkage": bool(row["deferred_linkage"]),
            "atomic_group_id": row["atomic_group_id"],
            "atomic_group_index": row["atomic_group_index"],
            "atomic_group_size": row["atomic_group_size"],
        }
    )


def _sql_filters(query: JournalQuery) -> tuple[str, tuple[object, ...]]:
    clauses: list[str] = []
    parameters: list[object] = []
    direct = {
        "record_type": query.record_type.value if query.record_type else None,
        "instrument": query.instrument,
        "epic": query.epic,
        "strategy_variant": query.strategy_variant,
        "environment": query.environment,
        "source_record_id": query.source_record_id,
    }
    for column, value in direct.items():
        if value is not None:
            clauses.append(f"{column} = ?")
            parameters.append(value)
    if query.start_at is not None:
        clauses.append("effective_at >= ?")
        parameters.append(query.start_at.isoformat())
    effective_end = min(
        (item for item in (query.end_at, query.cutoff_at) if item is not None), default=None
    )
    if effective_end is not None:
        clauses.append("effective_at <= ?")
        parameters.append(effective_end.isoformat())
    return ("WHERE " + " AND ".join(clauses) if clauses else "", tuple(parameters))


def _payload_matches(record: JournalRecord, query: JournalQuery) -> bool:
    payload = record.payload
    equal = (
        (query.regime, _find(payload, "regime", "current_regime", "entry_regime")),
        (query.risk_status, _find(payload, "risk_status", "status")),
        (query.risk_reason_code, _find(payload, "risk_reason_code", "reason_code", "reason_codes")),
        (query.execution_status, _find(payload, "execution_status", "status")),
        (
            query.process_classification.value if query.process_classification else None,
            _find(payload, "process_classification"),
        ),
        (
            query.financial_outcome.value if query.financial_outcome else None,
            _find(payload, "financial_outcome"),
        ),
        (query.candidate_id, _find(payload, "candidate_id")),
        (query.risk_decision_id, _find(payload, "risk_decision_id", "decision_id")),
        (query.trade_id, _find(payload, "trade_id")),
        (
            query.configuration_fingerprint,
            _find(
                payload,
                "configuration_fingerprint",
                "strategy_configuration_fingerprint",
                "risk_configuration_fingerprint",
            ),
        ),
    )
    for expected, actual in equal:
        if expected is None:
            continue
        if isinstance(actual, (list, tuple)):
            if expected not in actual:
                return False
        elif actual != expected:
            return False
    pnl = _decimal(_find(payload, "net_pnl", "realized_pnl", "gross_pnl"))
    drawdown = _decimal(_find(payload, "drawdown", "maximum_drawdown"))
    return _in_range(pnl, query.minimum_pnl, query.maximum_pnl) and _in_range(
        drawdown, query.minimum_drawdown, query.maximum_drawdown
    )


def _find(payload: dict[str, object], *keys: str) -> Any:
    for key in keys:
        if key in payload:
            return payload[key]
    for value in payload.values():
        if isinstance(value, dict):
            found = _find(value, *keys)
            if found is not None:
                return found
    return None


def _decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _in_range(value: Any, minimum: Any, maximum: Any) -> bool:
    if minimum is not None and (value is None or value < minimum):
        return False
    return not (maximum is not None and (value is None or value > maximum))
