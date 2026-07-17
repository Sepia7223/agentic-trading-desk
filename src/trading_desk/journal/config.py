"""Immutable safe configuration for the local durable journal."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from trading_desk.journal.fingerprints import fingerprint

CURRENT_SCHEMA_VERSION = 3


class SQLiteSynchronousMode(StrEnum):
    NORMAL = "NORMAL"
    FULL = "FULL"


class JournalConfiguration(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    database_path: Path
    journal_enabled: bool = True
    schema_version: int = CURRENT_SCHEMA_VERSION
    use_wal: bool = True
    enforce_foreign_keys: bool = True
    synchronous_mode: SQLiteSynchronousMode = SQLiteSynchronousMode.FULL
    busy_timeout_seconds: int = Field(default=10, ge=1, le=120)
    maximum_batch_size: int = Field(default=100, ge=1, le=10_000)
    maximum_query_records: int = Field(default=1_000, ge=1, le=100_000)
    store_ai_structured_responses: bool = True
    store_raw_provider_responses: bool = False
    store_sanitized_broker_payloads: bool = True
    enable_automatic_reviews: bool = True
    enable_daily_reviews: bool = True
    enable_weekly_reviews: bool = True
    enable_monthly_reviews: bool = True
    enable_backups: bool = False
    backup_directory: Path | None = None
    backup_retention_count: int = Field(default=7, ge=1, le=365)
    verify_integrity_on_startup: bool = True
    allow_amendments: bool = True
    allow_hard_delete: bool = False

    @field_validator("database_path")
    @classmethod
    def require_explicit_database_file(cls, value: Path) -> Path:
        if not str(value).strip() or value.name in {"", ".", ".."}:
            raise ValueError("an explicit journal database file path is required")
        if value == Path(":memory:"):
            return value
        if value.suffix.lower() not in {".db", ".sqlite", ".sqlite3"}:
            raise ValueError("journal database must use a SQLite file extension")
        return value

    @model_validator(mode="after")
    def enforce_safety(self) -> Self:
        if self.schema_version != CURRENT_SCHEMA_VERSION:
            raise ValueError("configuration must target the current journal schema")
        if self.allow_hard_delete:
            raise ValueError("hard deletion is unavailable")
        if self.store_raw_provider_responses:
            raise ValueError("raw provider response storage is prohibited")
        if self.enable_backups and self.backup_directory is None:
            raise ValueError("backup directory is required when backups are enabled")
        return self

    @property
    def configuration_fingerprint(self) -> str:
        return fingerprint(self.model_dump(mode="python"))
