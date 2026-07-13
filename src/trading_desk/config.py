"""Typed application configuration with fail-closed trading defaults."""

from __future__ import annotations

from enum import StrEnum
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
    """Broker configuration.

    Milestone 1 intentionally supports only IG demo metadata. Real connection
    clients are not implemented here.
    """

    model_config = ConfigDict(frozen=True)

    broker_environment: BrokerEnvironment = BrokerEnvironment.DEMO
    base_url: str = IG_DEMO_BASE_URL
    api_key: SecretStr | None = None
    identifier: SecretStr | None = None
    password: SecretStr | None = None

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
