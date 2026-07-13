"""Typed application configuration with fail-closed trading defaults."""

from __future__ import annotations

from enum import StrEnum
from typing import Self
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator


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
    base_url: str = "https://demo-api.ig.com/gateway/deal"
    api_key: SecretStr | None = None
    identifier: SecretStr | None = None
    password: SecretStr | None = None

    @model_validator(mode="after")
    def reject_production_ig_url(self) -> Self:
        parsed = urlparse(self.base_url)
        host = parsed.netloc.lower()
        normalized = self.base_url.lower()
        if host == "api.ig.com" or "live-api.ig.com" in host or "/prod" in normalized:
            raise ValueError("production IG URLs are not allowed")
        if "demo" not in host:
            raise ValueError("IG base_url must point to a demo environment")
        return self


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
