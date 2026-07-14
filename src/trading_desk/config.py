"""Typed application configuration with fail-closed trading defaults."""

from __future__ import annotations

import os
from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path
from typing import Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

IG_DEMO_BASE_URL = "https://demo-api.ig.com/gateway/deal"


class BrokerEnvironment(StrEnum):
    """Supported broker environments."""

    DEMO = "DEMO"


class OperatingMode(StrEnum):
    """Runtime operating modes."""

    READ_ONLY = "READ_ONLY"


class BrokerSettings(BaseModel):
    """Configuration for the read-only IG demo adapter.

    Only the canonical demo gateway is accepted. Live trading and automatic
    execution remain disabled by the separate immutable safety boundary.
    """

    model_config = ConfigDict(frozen=True)

    broker_environment: BrokerEnvironment = BrokerEnvironment.DEMO
    base_url: str = IG_DEMO_BASE_URL
    api_key: SecretStr | None = None
    identifier: SecretStr | None = None
    password: SecretStr | None = None
    request_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    max_historical_price_points: int = Field(default=1000, ge=1, le=10000)

    @field_validator("base_url")
    @classmethod
    def allow_only_exact_demo_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        try:
            port = parsed.port
        except ValueError as error:
            raise ValueError("IG base_url must be the exact IG demo endpoint") from error

        is_exact_demo_endpoint = (
            parsed.scheme == "https"
            and parsed.hostname == "demo-api.ig.com"
            and port in (None, 443)
            and parsed.path == "/gateway/deal"
            and parsed.username is None
            and parsed.password is None
            and not parsed.query
            and not parsed.fragment
        )
        if not is_exact_demo_endpoint:
            raise ValueError("IG base_url must be the exact IG demo endpoint")
        return IG_DEMO_BASE_URL


class SafetySettings(BaseModel):
    """Hard-coded runtime safety defaults."""

    model_config = ConfigDict(frozen=True)

    operating_mode: OperatingMode = OperatingMode.READ_ONLY
    live_trading_allowed: bool = Field(default=False)
    automatic_execution_enabled: bool = Field(default=False)

    @model_validator(mode="after")
    def reject_enabled_trading(self) -> Self:
        if self.live_trading_allowed:
            raise ValueError("live trading is disabled")
        if self.automatic_execution_enabled:
            raise ValueError("automatic execution is disabled")
        return self


class AISettings(BaseModel):
    """Runtime AI provider configuration.

    This model intentionally contains no broker credentials.
    """

    model_config = ConfigDict(frozen=True)

    provider: str = "openai"
    model: str | None = None
    api_key: SecretStr | None = None


class AppSettings(BaseModel):
    """Top-level immutable application settings."""

    model_config = ConfigDict(frozen=True)

    broker: BrokerSettings = Field(default_factory=BrokerSettings)
    safety: SafetySettings = Field(default_factory=SafetySettings)
    ai: AISettings = Field(default_factory=AISettings)
    database_url: str = "sqlite:///trading_desk.sqlite3"

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
        env_file: str | Path | None = ".env",
    ) -> AppSettings:
        """Load settings explicitly without reading credentials during import."""

        values: dict[str, str] = {}
        if env_file is not None:
            values.update(_read_env_file(Path(env_file)))
        values.update(os.environ if environment is None else environment)

        broker_values = {
            "broker_environment": values.get("BROKER_ENVIRONMENT", BrokerEnvironment.DEMO),
            "base_url": values.get("IG_BASE_URL", IG_DEMO_BASE_URL),
            "identifier": values.get("IG_IDENTIFIER") or None,
            "password": values.get("IG_PASSWORD") or None,
            "api_key": values.get("IG_API_KEY") or None,
            "request_timeout_seconds": values.get("IG_REQUEST_TIMEOUT_SECONDS", "10"),
            "max_historical_price_points": values.get("IG_MAX_HISTORICAL_PRICE_POINTS", "1000"),
        }
        safety_values = {
            "operating_mode": values.get("OPERATING_MODE", OperatingMode.READ_ONLY),
            "live_trading_allowed": values.get("LIVE_TRADING_ALLOWED", "false"),
            "automatic_execution_enabled": values.get("AUTOMATIC_EXECUTION_ENABLED", "false"),
        }
        ai_values = {
            "api_key": values.get("OPENAI_API_KEY") or None,
            "model": values.get("OPENAI_MODEL") or None,
        }
        return cls(
            broker=BrokerSettings.model_validate(broker_values),
            safety=SafetySettings.model_validate(safety_values),
            ai=AISettings.model_validate(ai_values),
            database_url=values.get("DATABASE_URL", "sqlite:///trading_desk.sqlite3"),
        )


def _read_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise ValueError(f"invalid environment entry on line {line_number}")
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            raise ValueError(f"invalid environment key on line {line_number}")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values
