"""Transactional journal schema creation and migration support."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from trading_desk.journal.errors import JournalSchemaError, UnsupportedSchemaError
from trading_desk.journal.fingerprints import fingerprint
from trading_desk.journal.schema import SCHEMA_V1, SCHEMA_VERSION

MIGRATIONS = {1: SCHEMA_V1}


def database_version(connection: sqlite3.Connection) -> int:
    row = connection.execute("PRAGMA user_version").fetchone()
    return int(row[0]) if row else 0


def migrate(connection: sqlite3.Connection, target_version: int = SCHEMA_VERSION) -> int:
    current = database_version(connection)
    if current > target_version:
        raise UnsupportedSchemaError(
            f"journal schema {current} is newer than supported schema {target_version}"
        )
    if target_version > SCHEMA_VERSION:
        raise UnsupportedSchemaError(f"journal schema {target_version} is unsupported")
    try:
        for version in range(current + 1, target_version + 1):
            script = MIGRATIONS.get(version)
            if script is None:
                raise JournalSchemaError(f"no migration is available for schema {version}")
            connection.execute("BEGIN IMMEDIATE")
            for statement in _statements(script):
                connection.execute(statement)
            connection.execute(f"PRAGMA user_version = {version}")
            connection.execute(
                "INSERT OR REPLACE INTO journal_migrations(version, applied_at, checksum) "
                "VALUES (?, ?, ?)",
                (version, datetime.now(UTC).isoformat(), fingerprint(script)),
            )
            connection.commit()
    except Exception as exc:
        connection.rollback()
        if isinstance(exc, (JournalSchemaError, UnsupportedSchemaError)):
            raise
        raise JournalSchemaError("journal migration failed and was rolled back") from exc
    return database_version(connection)


def _statements(script: str) -> tuple[str, ...]:
    return tuple(statement.strip() for statement in script.split(";") if statement.strip())
