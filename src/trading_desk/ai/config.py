"""Immutable disabled-by-default AI Analyst configuration."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from trading_desk.ai.fingerprints import model_fingerprint


class AIAnalystConfiguration(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    schema_version: Literal["ai-analyst-v1"] = "ai-analyst-v1"
    provider_name: str = Field(default="disabled", min_length=1, max_length=80)
    model_name: str = Field(default="none", min_length=1, max_length=120)
    analysis_enabled: bool = False
    maximum_input_characters: int = Field(default=20_000, ge=100, le=1_000_000)
    maximum_records_per_request: int = Field(default=50, ge=1, le=1000)
    maximum_output_characters: int = Field(default=10_000, ge=100, le=100_000)
    temperature: Decimal = Field(default=Decimal("0"), ge=0, le=1)
    timeout_seconds: Decimal = Field(default=Decimal("30"), gt=0, le=300)
    maximum_retries: int = Field(default=0, ge=0, le=1)
    allow_network_provider: bool = False
    allow_news_context: bool = False
    allow_historical_similarity_context: bool = True
    redact_account_identifiers: Literal[True] = True
    redact_broker_identifiers: Literal[True] = True
    include_strategy_details: bool = True
    include_risk_details: bool = True
    include_portfolio_details: bool = True
    include_human_notes: bool = False
    store_raw_provider_response: Literal[False] = False

    @model_validator(mode="before")
    @classmethod
    def reject_binary_floats(cls, value: object) -> object:
        if isinstance(value, dict) and any(isinstance(item, float) for item in value.values()):
            raise ValueError("binary floating point is prohibited in AI configuration")
        return value

    @field_validator("provider_name", "model_name")
    @classmethod
    def safe_name(cls, value: str) -> str:
        if any(char in value for char in "\r\n\t"):
            raise ValueError("provider and model names must be single-line")
        return value

    @model_validator(mode="after")
    def validate_provider_state(self) -> Self:
        if self.allow_network_provider and not self.analysis_enabled:
            raise ValueError("network provider cannot be enabled while analysis is disabled")
        if self.provider_name == "disabled" and self.analysis_enabled:
            raise ValueError("enabled analysis requires an explicit provider")
        return self

    @property
    def fingerprint(self) -> str:
        return model_fingerprint(self)
