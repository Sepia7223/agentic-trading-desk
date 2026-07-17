"""Immutable loopback-only Operations Center configuration."""

from __future__ import annotations

import ipaddress
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from trading_desk.operations.fingerprints import fingerprint


class OperationsConfiguration(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1024, le=65535)
    environment: Literal["IG DEMO"] = "IG DEMO"
    read_only: Literal[True] = True
    allow_remote_bind: Literal[False] = False
    websocket_enabled: bool = True
    maximum_websocket_clients: int = Field(default=10, ge=1, le=100)
    maximum_query_records: int = Field(default=500, ge=1, le=10_000)
    maximum_replay_records: int = Field(default=2_000, ge=1, le=50_000)
    heartbeat_timeout_seconds: int = Field(default=90, ge=5, le=3600)
    scheduler_stale_after_seconds: int = Field(default=300, ge=5, le=86_400)
    market_data_stale_after_seconds: int = Field(default=300, ge=5, le=86_400)
    broker_stale_after_seconds: int = Field(default=120, ge=5, le=3600)
    journal_check_interval_seconds: int = Field(default=60, ge=5, le=3600)
    show_safe_account_alias: bool = True
    show_truncated_deal_references: bool = True
    enable_ai_panels: bool = True
    enable_replay: bool = True
    enable_exports: bool = True
    enable_search: bool = True
    frontend_directory: Path | None = None

    @model_validator(mode="after")
    def loopback_only(self) -> Self:
        try:
            address = ipaddress.ip_address(self.host)
        except ValueError:
            if self.host.lower() != "localhost":
                raise ValueError("Operations Center host must be loopback") from None
        else:
            if not address.is_loopback:
                raise ValueError("remote Operations Center binding is prohibited")
        if self.maximum_replay_records < self.maximum_query_records:
            raise ValueError("replay limit must not be below query limit")
        return self

    @property
    def configuration_fingerprint(self) -> str:
        return fingerprint(self.model_dump(mode="python"))
