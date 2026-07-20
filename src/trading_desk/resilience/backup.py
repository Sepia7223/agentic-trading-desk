"""Durable state backups with fingerprint- and lineage-preserving restore.

A backup captures each source file byte-for-byte with its SHA-256 digest recorded
in a fingerprinted manifest. Because bytes are preserved exactly, a hash-chained
journal keeps its lineage across a backup/restore cycle. Restore verifies every
digest before writing anything and re-verifies after; a mismatch is quarantined
and reported rather than silently overwriting live state.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Self

from pydantic import Field, field_validator, model_validator

from trading_desk.context.fingerprints import fingerprint
from trading_desk.resilience.diagnostics import ResilienceModel


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _atomic_write(target: Path, data: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_bytes(data)
    temporary.replace(target)


class BackupEntry(ResilienceModel):
    relative_path: str = Field(min_length=1)
    sha256: str = Field(min_length=64, max_length=64)
    size_bytes: int = Field(ge=0)


class BackupManifest(ResilienceModel):
    manifest_id: str = Field(min_length=64, max_length=64)
    label: str = Field(min_length=1)
    created_at: datetime
    entries: tuple[BackupEntry, ...] = Field(min_length=1)

    @field_validator("created_at")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("backup timestamps must be timezone-aware UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def identity(self) -> Self:
        expected = fingerprint(self.model_dump(mode="python", exclude={"manifest_id"}))
        if self.manifest_id != expected:
            raise ValueError("backup manifest fingerprint mismatch")
        return self


class RestoreOutcome(ResilienceModel):
    restored: bool
    restored_paths: tuple[str, ...]
    mismatches: tuple[str, ...]
    quarantined: tuple[str, ...]
    reason: str = Field(min_length=1)


def _create_manifest(
    label: str, created_at: datetime, entries: tuple[BackupEntry, ...]
) -> BackupManifest:
    ordered = tuple(sorted(entries, key=lambda item: item.relative_path))
    draft_fields = {
        "manifest_id": "0" * 64,
        "label": label,
        "created_at": created_at,
        "entries": ordered,
    }
    draft = BackupManifest.model_construct(**draft_fields)  # type: ignore[arg-type]
    fields = draft.model_dump(mode="python", exclude={"manifest_id"})
    return BackupManifest.model_validate({**fields, "manifest_id": fingerprint(fields)})


class BackupService:
    """Create, verify, and restore a single fingerprinted backup directory."""

    def __init__(self, backup_dir: Path) -> None:
        self.backup_dir = backup_dir

    @property
    def manifest_path(self) -> Path:
        return self.backup_dir / "manifest.json"

    def create(self, sources: dict[str, Path], now: datetime, *, label: str) -> BackupManifest:
        if not sources:
            raise ValueError("a backup requires at least one source file")
        entries: list[BackupEntry] = []
        for relative_path, source in sorted(sources.items()):
            data = source.read_bytes()
            _atomic_write(self.backup_dir / relative_path, data)
            entries.append(
                BackupEntry(relative_path=relative_path, sha256=_sha256(data), size_bytes=len(data))
            )
        manifest = _create_manifest(label, now, tuple(entries))
        _atomic_write(self.manifest_path, manifest.model_dump_json(indent=2).encode("utf-8"))
        return manifest

    def load_manifest(self) -> BackupManifest:
        if not self.manifest_path.is_file():
            raise ValueError("backup manifest is missing")
        return BackupManifest.model_validate_json(self.manifest_path.read_text(encoding="utf-8"))

    def verify(self, manifest: BackupManifest) -> tuple[str, ...]:
        """Return the relative paths whose backed-up bytes do not match the manifest."""

        mismatches: list[str] = []
        for entry in manifest.entries:
            stored = self.backup_dir / entry.relative_path
            if not stored.is_file() or _sha256(stored.read_bytes()) != entry.sha256:
                mismatches.append(entry.relative_path)
        return tuple(mismatches)

    def restore(
        self,
        manifest: BackupManifest,
        destinations: dict[str, Path],
        *,
        quarantine_dir: Path | None = None,
        now: datetime | None = None,
    ) -> RestoreOutcome:
        """Restore only if every backed-up digest verifies; never overwrite blindly."""

        backup_mismatches = self.verify(manifest)
        if backup_mismatches:
            return RestoreOutcome(
                restored=False,
                restored_paths=(),
                mismatches=backup_mismatches,
                quarantined=(),
                reason="BACKUP_DIGEST_MISMATCH",
            )

        quarantined: list[str] = []
        if quarantine_dir is not None:
            stamp = (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%S%f")
            for entry in manifest.entries:
                destination = destinations.get(entry.relative_path)
                if destination is None or not destination.is_file():
                    continue
                current = destination.read_bytes()
                if _sha256(current) != entry.sha256:
                    aside = quarantine_dir / f"{entry.relative_path}.{stamp}.corrupt"
                    _atomic_write(aside, current)
                    quarantined.append(entry.relative_path)

        restored_paths: list[str] = []
        for entry in manifest.entries:
            destination = destinations.get(entry.relative_path)
            if destination is None:
                continue
            data = (self.backup_dir / entry.relative_path).read_bytes()
            _atomic_write(destination, data)
            if _sha256(destination.read_bytes()) != entry.sha256:
                return RestoreOutcome(
                    restored=False,
                    restored_paths=tuple(restored_paths),
                    mismatches=(entry.relative_path,),
                    quarantined=tuple(quarantined),
                    reason="POST_RESTORE_VERIFICATION_FAILED",
                )
            restored_paths.append(entry.relative_path)
        return RestoreOutcome(
            restored=True,
            restored_paths=tuple(restored_paths),
            mismatches=(),
            quarantined=tuple(quarantined),
            reason="RESTORE_VERIFIED",
        )
