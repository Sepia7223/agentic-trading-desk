from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from pydantic import ValidationError

from journal_helpers import configuration
from trading_desk.journal.config import CURRENT_SCHEMA_VERSION, JournalConfiguration
from trading_desk.journal.errors import UnsupportedSchemaError
from trading_desk.journal.migrations import database_version
from trading_desk.journal.sqlite import SQLiteJournalRepository


def test_journal_configuration_safe_defaults(tmp_path: Path) -> None:
    config = configuration(tmp_path / "journal.db")
    assert config.journal_enabled
    assert config.enable_automatic_reviews
    assert config.verify_integrity_on_startup
    assert config.allow_amendments
    assert not config.allow_hard_delete
    assert not config.store_raw_provider_responses


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("maximum_batch_size", 0),
        ("backup_retention_count", 0),
        ("maximum_query_records", 0),
        ("allow_hard_delete", True),
        ("store_raw_provider_responses", True),
    ),
)
def test_journal_configuration_rejects_unsafe_values(
    tmp_path: Path, field: str, value: object
) -> None:
    with pytest.raises(ValidationError):
        configuration(tmp_path / "journal.db", **{field: value})


def test_journal_configuration_requires_explicit_sqlite_file(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        JournalConfiguration(database_path=tmp_path / "journal.txt")


def test_journal_configuration_is_immutable(tmp_path: Path) -> None:
    config = configuration(tmp_path / "journal.db")
    with pytest.raises(ValidationError):
        config.maximum_batch_size = 2  # type: ignore[misc]


def test_configuration_fingerprint_is_stable(tmp_path: Path) -> None:
    path = tmp_path / "journal.db"
    assert (
        configuration(path).configuration_fingerprint
        == configuration(path).configuration_fingerprint
    )


def test_schema_creation_is_idempotent_and_restart_safe(tmp_path: Path) -> None:
    path = tmp_path / "journal.db"
    with SQLiteJournalRepository(configuration(path)) as repository:
        assert repository.schema_version == CURRENT_SCHEMA_VERSION
    with SQLiteJournalRepository(configuration(path)) as repository:
        assert repository.schema_version == CURRENT_SCHEMA_VERSION


def test_schema_uses_foreign_keys_wal_and_full_synchronous(tmp_path: Path) -> None:
    with SQLiteJournalRepository(configuration(tmp_path / "journal.db")) as repository:
        assert repository.connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert repository.connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert repository.connection.execute("PRAGMA synchronous").fetchone()[0] == 2


def test_future_schema_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "future.db"
    connection = sqlite3.connect(path)
    connection.execute(f"PRAGMA user_version = {CURRENT_SCHEMA_VERSION + 1}")
    connection.close()
    with pytest.raises(UnsupportedSchemaError):
        SQLiteJournalRepository(configuration(path))


def test_schema_metadata_tracks_current_version(tmp_path: Path) -> None:
    with SQLiteJournalRepository(configuration(tmp_path / "journal.db")) as repository:
        assert database_version(repository.connection) == CURRENT_SCHEMA_VERSION
        row = repository.connection.execute(
            "SELECT value FROM journal_metadata WHERE key = 'schema_version'"
        ).fetchone()
        assert row[0] == str(CURRENT_SCHEMA_VERSION)


def test_parent_directory_is_not_created_implicitly(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="parent directory"):
        SQLiteJournalRepository(configuration(tmp_path / "absent" / "journal.db"))
