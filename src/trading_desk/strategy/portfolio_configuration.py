"""Immutable configuration and parameter governance for portfolio strategies."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from trading_desk.context.fingerprints import fingerprint


class GovernedStrategyConfiguration(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    schema_version: Literal["portfolio-strategy-config-v1"] = "portfolio-strategy-config-v1"
    minimum_history: int = Field(default=60, ge=30, le=2000)
    atr_window: int = Field(default=14, ge=5, le=100)
    maximum_spread_bps: Decimal = Field(default=Decimal("10"), gt=0)
    minimum_reward_to_risk: Decimal = Field(default=Decimal("1.5"), gt=1)
    maximum_signal_age_bars: int = Field(default=1, ge=1, le=5)
    long_only: Literal[True] = True
    parameter_definition_version: Literal["portfolio-parameters-v1"] = "portfolio-parameters-v1"

    @property
    def fingerprint(self) -> str:
        return fingerprint(self)


class TrendPullbackConfiguration(GovernedStrategyConfiguration):
    trend_window: int = Field(default=40, ge=20, le=200)
    pullback_lookback: int = Field(default=8, ge=3, le=30)
    minimum_normalized_slope: Decimal = Field(default=Decimal("0.03"), gt=0)
    minimum_retracement_atr: Decimal = Field(default=Decimal("0.25"), ge=0)
    maximum_retracement_atr: Decimal = Field(default=Decimal("3.0"), gt=0)
    maximum_entry_extension_atr: Decimal = Field(default=Decimal("0.75"), gt=0)
    recovery_fraction: Decimal = Field(default=Decimal("0.35"), gt=0, le=1)
    stop_buffer_atr: Decimal = Field(default=Decimal("0.25"), gt=0)
    target_r_multiple: Decimal = Field(default=Decimal("2"), ge=1)
    maximum_holding_bars: int = Field(default=24, ge=1)


class VolatilityBreakoutConfiguration(GovernedStrategyConfiguration):
    consolidation_window: int = Field(default=20, ge=8, le=100)
    volatility_window: int = Field(default=10, ge=5, le=50)
    maximum_consolidation_width_atr: Decimal = Field(default=Decimal("4"), gt=0)
    minimum_breakout_atr: Decimal = Field(default=Decimal("0.10"), ge=0)
    minimum_expansion_ratio: Decimal = Field(default=Decimal("1.15"), gt=1)
    maximum_chase_atr: Decimal = Field(default=Decimal("0.80"), gt=0)
    stop_buffer_atr: Decimal = Field(default=Decimal("0.20"), gt=0)
    target_r_multiple: Decimal = Field(default=Decimal("2"), ge=1)
    maximum_holding_bars: int = Field(default=16, ge=1)


class RangeMeanReversionConfiguration(GovernedStrategyConfiguration):
    range_window: int = Field(default=30, ge=12, le=150)
    trend_window: int = Field(default=20, ge=8, le=100)
    maximum_normalized_slope: Decimal = Field(default=Decimal("0.08"), ge=0)
    maximum_range_width_atr: Decimal = Field(default=Decimal("8"), gt=0)
    lower_entry_fraction: Decimal = Field(default=Decimal("0.25"), gt=0, lt=Decimal("0.5"))
    recovery_fraction: Decimal = Field(default=Decimal("0.10"), gt=0, le=1)
    stop_buffer_atr: Decimal = Field(default=Decimal("0.25"), gt=0)
    maximum_holding_bars: int = Field(default=20, ge=1)

    @model_validator(mode="after")
    def target_can_exceed_entry(self) -> Self:
        if self.lower_entry_fraction + self.recovery_fraction >= Decimal("0.5"):
            raise ValueError("range entry and recovery parameters leave no target distance")
        return self


class ParameterDefinition(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    name: str
    fixed: bool
    minimum: Decimal | None = None
    maximum: Decimal | None = None
    step: Decimal | None = None
    selection_objective: str = "balanced_expectancy_drawdown_stability"


def governed_parameter_definitions() -> tuple[ParameterDefinition, ...]:
    return (
        ParameterDefinition(name="long_only", fixed=True),
        ParameterDefinition(
            name="atr_window",
            fixed=False,
            minimum=Decimal("10"),
            maximum=Decimal("30"),
            step=Decimal("2"),
        ),
        ParameterDefinition(
            name="minimum_reward_to_risk",
            fixed=False,
            minimum=Decimal("1.25"),
            maximum=Decimal("3"),
            step=Decimal("0.25"),
        ),
        ParameterDefinition(
            name="maximum_spread_bps",
            fixed=False,
            minimum=Decimal("2"),
            maximum=Decimal("15"),
            step=Decimal("1"),
        ),
    )
