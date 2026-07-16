"""Explicit SQLite-consistent backups with checksums and retention."""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from trading_desk.journal.errors import JournalBackupError
from trading_desk.journal.models import BackupResult
from trading_desk.journal.sqlite import SQLiteJournalRepository


def create_backup(
    repository: SQLiteJournalRepository,
    destination: Path,
    *,
    retention_count: int | None = None,
) -> BackupResult:
    if not destination.exists() or not destination.is_dir():
        raise JournalBackupError("backup destination must be an existing directory")
    timestamp = datetime.now(UTC)
    filename = f"journal-{timestamp.strftime('%Y%m%dT%H%M%S%fZ')}.db"
    path = destination / filename
    try:
        target = sqlite3.connect(str(path))
        with target:
            repository.connection.backup(target)
        check = target.execute("PRAGMA quick_check").fetchone()
        target.close()
        verified = bool(check and str(check[0]).lower() == "ok")
        if not verified:
            path.unlink(missing_ok=True)
            raise JournalBackupError("backup verification failed")
    except JournalBackupError:
        raise
    except Exception as exc:
        path.unlink(missing_ok=True)
        raise JournalBackupError("journal backup failed") from exc
    checksum = _checksum(path)
    keep = retention_count or repository.configuration.backup_retention_count
    _apply_retention(destination, keep)
    return BackupResult(path=path, checksum=checksum, created_at=timestamp, verified=True)


def verify_backup(path: Path, checksum: str) -> bool:
    if not path.is_file() or _checksum(path) != checksum:
        return False
    try:
        connection = sqlite3.connect(str(path))
        result = connection.execute("PRAGMA quick_check").fetchone()
        connection.close()
        return bool(result and str(result[0]).lower() == "ok")
    except sqlite3.DatabaseError:
        return False


def _apply_retention(destination: Path, retention_count: int) -> None:
    if retention_count < 1:
        raise JournalBackupError("backup retention count must be positive")
    backups = sorted(destination.glob("journal-*.db"), key=lambda item: item.name, reverse=True)
    for expired in backups[retention_count:]:
        expired.unlink()


def _checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
