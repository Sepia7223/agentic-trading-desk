"""Milestone 16: fingerprint-preserving backup/restore and exclusive locking."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from trading_desk.resilience import (
    BackupService,
    LockOutcome,
    ProcessLockError,
    ProcessLockStore,
)

NOW = datetime(2026, 6, 1, 9, 0, tzinfo=UTC)


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_backup_manifest_records_digests_and_restores_byte_for_byte(tmp_path: Path) -> None:
    journal = _write(tmp_path / "src" / "journal.jsonl", '{"chain":"genesis"}\n{"chain":"h1"}\n')
    state = _write(tmp_path / "src" / "portfolio-state.json", '{"reservations":[]}')
    service = BackupService(tmp_path / "backup")
    manifest = service.create(
        {"journal.jsonl": journal, "portfolio-state.json": state},
        NOW,
        label="nightly",
    )
    assert len(manifest.entries) == 2
    assert service.verify(manifest) == ()

    # corrupt the live files, then restore.
    journal.write_text("CORRUPTED", encoding="utf-8")
    state.write_text("CORRUPTED", encoding="utf-8")
    outcome = service.restore(
        manifest,
        {"journal.jsonl": journal, "portfolio-state.json": state},
        quarantine_dir=tmp_path / "quarantine",
        now=NOW,
    )
    assert outcome.restored is True
    assert journal.read_text(encoding="utf-8") == '{"chain":"genesis"}\n{"chain":"h1"}\n'
    assert set(outcome.quarantined) == {"journal.jsonl", "portfolio-state.json"}
    # the corrupt live state was preserved aside, not deleted.
    assert list((tmp_path / "quarantine").glob("*.corrupt"))


def test_restore_refuses_when_backup_bytes_are_corrupt(tmp_path: Path) -> None:
    source = _write(tmp_path / "src" / "state.json", "authoritative")
    service = BackupService(tmp_path / "backup")
    manifest = service.create({"state.json": source}, NOW, label="pre-change")
    # corrupt the backup copy after the manifest was fingerprinted.
    (service.backup_dir / "state.json").write_text("tampered", encoding="utf-8")
    assert service.verify(manifest) == ("state.json",)
    destination = _write(tmp_path / "dest" / "state.json", "live")
    outcome = service.restore(manifest, {"state.json": destination})
    assert outcome.restored is False
    assert outcome.reason == "BACKUP_DIGEST_MISMATCH"
    # the live destination is untouched because restore refused.
    assert destination.read_text(encoding="utf-8") == "live"


def test_manifest_reload_preserves_fingerprint(tmp_path: Path) -> None:
    source = _write(tmp_path / "src" / "j.jsonl", "line\n")
    service = BackupService(tmp_path / "backup")
    created = service.create({"j.jsonl": source}, NOW, label="x")
    reloaded = service.load_manifest()
    assert reloaded.manifest_id == created.manifest_id
    assert reloaded == created


def test_lock_acquired_on_clean_host(tmp_path: Path) -> None:
    store = ProcessLockStore(tmp_path / "desk.lock")
    result = store.acquire(pid=1000, hostname="mini-pc", now=NOW)
    assert result.outcome is LockOutcome.ACQUIRED
    assert result.incident is None
    assert store.read() is not None


def test_same_process_reacquire_is_idempotent(tmp_path: Path) -> None:
    store = ProcessLockStore(tmp_path / "desk.lock")
    store.acquire(pid=1000, hostname="mini-pc", now=NOW)
    again = store.acquire(pid=1000, hostname="mini-pc", now=NOW + timedelta(seconds=30))
    assert again.outcome is LockOutcome.REACQUIRED
    assert again.lock.started_at == NOW
    assert again.lock.heartbeat_at == NOW + timedelta(seconds=30)


def test_fresh_lock_held_by_other_process_refuses(tmp_path: Path) -> None:
    store = ProcessLockStore(tmp_path / "desk.lock", heartbeat_ttl=timedelta(minutes=2))
    store.acquire(pid=1000, hostname="laptop", now=NOW)
    contender = store.acquire(
        pid=2000, hostname="mini-pc", now=NOW + timedelta(seconds=30), owner_alive=True
    )
    assert contender.outcome is LockOutcome.REFUSED_HELD
    assert contender.lock.pid == 1000  # unchanged owner


def test_expired_heartbeat_is_taken_over_with_incident(tmp_path: Path) -> None:
    store = ProcessLockStore(tmp_path / "desk.lock", heartbeat_ttl=timedelta(minutes=2))
    store.acquire(pid=1000, hostname="laptop", now=NOW)
    takeover = store.acquire(pid=2000, hostname="mini-pc", now=NOW + timedelta(minutes=5))
    assert takeover.outcome is LockOutcome.TAKEOVER_STALE
    assert takeover.lock.pid == 2000
    assert takeover.incident is not None
    assert takeover.incident.category.value == "STALE_LOCK_CLEARED"
    assert ("reason", "HEARTBEAT_EXPIRED") in takeover.incident.safe_details


def test_dead_owner_is_taken_over_even_if_heartbeat_fresh(tmp_path: Path) -> None:
    store = ProcessLockStore(tmp_path / "desk.lock", heartbeat_ttl=timedelta(minutes=2))
    store.acquire(pid=1000, hostname="laptop", now=NOW)
    takeover = store.acquire(
        pid=2000, hostname="mini-pc", now=NOW + timedelta(seconds=10), owner_alive=False
    )
    assert takeover.outcome is LockOutcome.TAKEOVER_STALE
    assert takeover.incident is not None
    assert ("reason", "OWNER_REPORTED_DEAD") in takeover.incident.safe_details


def test_corrupt_lock_file_raises_rather_than_being_ignored(tmp_path: Path) -> None:
    lock_path = tmp_path / "desk.lock"
    _write(lock_path, "{ not valid json")
    store = ProcessLockStore(lock_path)
    with pytest.raises(ProcessLockError):
        store.read()


def test_cannot_refresh_or_release_a_lock_owned_by_another(tmp_path: Path) -> None:
    store = ProcessLockStore(tmp_path / "desk.lock")
    store.acquire(pid=1000, hostname="laptop", now=NOW)
    with pytest.raises(ProcessLockError):
        store.refresh(pid=2000, hostname="mini-pc", now=NOW + timedelta(seconds=5))
    with pytest.raises(ProcessLockError):
        store.release(pid=2000, hostname="mini-pc")
