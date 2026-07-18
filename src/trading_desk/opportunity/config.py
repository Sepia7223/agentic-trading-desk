"""Immutable Demo-only Opportunity Engine configuration and market universe."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from trading_desk.context.models import ContextTimeframe
from trading_desk.opportunity.fingerprints import fingerprint


class OpportunityConfigurationModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    @model_validator(mode="before")
    @classmethod
    def reject_binary_floats(cls, value: object) -> object:
        if _contains_float(value):
            raise ValueError("binary floating point is prohibited in opportunity configuration")
        return value


class MarketDefinition(OpportunityConfigurationModel):
    instrument_id: str = Field(pattern=r"[A-Z]{3}/[A-Z]{3}")
    epic: str = Field(pattern=r"[A-Za-z0-9._]{6,30}")
    asset_class: Literal["FOREX"] = "FOREX"
    base_currency: str = Field(pattern=r"[A-Z]{3}")
    quote_currency: str = Field(pattern=r"[A-Z]{3}")
    minimum_trade_size: Decimal = Field(gt=0)
    decimal_precision: int = Field(ge=1, le=8)
    pip_or_point_value: Decimal = Field(gt=0)
    supported_timeframes: tuple[ContextTimeframe, ...]
    enabled_strategy_families: tuple[
        Literal[
            "TREND_REGIME",
            "TREND_PULLBACK",
            "VOLATILITY_BREAKOUT",
            "RANGE_MEAN_REVERSION",
        ],
        ...,
    ]
    maximum_acceptable_spread: Decimal = Field(gt=0)
    session_policy: str = Field(min_length=1, max_length=80)
    correlation_groups: tuple[str, ...]
    enabled: bool = True

    @model_validator(mode="after")
    def validate_pair(self) -> Self:
        if self.base_currency == self.quote_currency:
            raise ValueError("market currencies must differ")
        if self.instrument_id != f"{self.base_currency}/{self.quote_currency}":
            raise ValueError("instrument ID must match base and quote currencies")
        if not self.supported_timeframes or len(set(self.supported_timeframes)) != len(
            self.supported_timeframes
        ):
            raise ValueError("market timeframes must be non-empty and unique")
        allowed = {
            ContextTimeframe.MINUTE_5,
            ContextTimeframe.MINUTE_15,
            ContextTimeframe.HOUR,
        }
        if not set(self.supported_timeframes).issubset(allowed):
            raise ValueError("market timeframe is outside the bounded opportunity set")
        if not self.enabled_strategy_families:
            raise ValueError("market requires at least one strategy family")
        if not self.correlation_groups or len(set(self.correlation_groups)) != len(
            self.correlation_groups
        ):
            raise ValueError("correlation groups must be non-empty and unique")
        return self


class OpportunityEngineConfiguration(OpportunityConfigurationModel):
    enabled: bool = False
    environment: Literal["DEMO"] = "DEMO"
    maximum_candidates_per_cycle: int = Field(default=100, ge=1, le=500)
    maximum_candidates_sent_to_risk: int = Field(default=3, ge=1, le=10)
    minimum_net_expected_value: Decimal = Field(default=Decimal("0"), ge=0)
    exploratory_score_threshold: Decimal = Field(default=Decimal("55"), ge=0, le=100)
    standard_score_threshold: Decimal = Field(default=Decimal("70"), ge=0, le=100)
    strong_score_threshold: Decimal = Field(default=Decimal("85"), ge=0, le=100)
    maximum_candidate_age_seconds: int = Field(default=60, ge=1, le=3600)
    correlation_filter_enabled: bool = True
    maximum_correlated_positions: int = Field(default=1, ge=1, le=10)
    maximum_existing_positions: int = Field(default=3, ge=1, le=20)
    recent_reentry_cooldown_seconds: int = Field(default=3600, ge=0, le=604800)
    score_weights: tuple[tuple[str, Decimal], ...] = (
        ("net_expected_value", Decimal("0.20")),
        ("signal_confidence", Decimal("0.15")),
        ("regime_compatibility", Decimal("0.10")),
        ("reward_to_risk", Decimal("0.10")),
        ("liquidity", Decimal("0.08")),
        ("volatility", Decimal("0.06")),
        ("session", Decimal("0.06")),
        ("data_quality", Decimal("0.10")),
        ("event_safety", Decimal("0.05")),
        ("cost_efficiency", Decimal("0.05")),
        ("uncertainty", Decimal("0.05")),
    )

    @model_validator(mode="after")
    def validate_thresholds_and_weights(self) -> Self:
        if not (
            self.exploratory_score_threshold
            < self.standard_score_threshold
            < self.strong_score_threshold
        ):
            raise ValueError("opportunity score thresholds must increase strictly")
        keys = [key for key, _ in self.score_weights]
        if len(keys) != len(set(keys)) or sum(value for _, value in self.score_weights) != 1:
            raise ValueError("score weights must be unique and sum exactly to one")
        return self

    @property
    def configuration_fingerprint(self) -> str:
        return fingerprint(self)


class DemoExplorationConfiguration(OpportunityConfigurationModel):
    enabled: bool = False
    environment: Literal["DEMO"] = "DEMO"
    minimum_evaluations_per_day: int = Field(default=100, ge=1)
    target_closed_trades_per_30_days: int = Field(default=100, ge=1)
    preferred_closed_trades_per_30_days: int = Field(default=250, ge=1)
    maximum_trades_per_day: int = Field(default=20, ge=1, le=100)
    maximum_concurrent_positions: int = Field(default=3, ge=1, le=20)
    maximum_correlated_positions: int = Field(default=1, ge=1, le=10)
    exploratory_risk_multiplier: Decimal = Field(default=Decimal("0.25"), gt=0, le=1)
    standard_risk_multiplier: Decimal = Field(default=Decimal("0.50"), gt=0, le=1)
    strong_risk_multiplier: Decimal = Field(default=Decimal("1.00"), gt=0, le=1)

    @model_validator(mode="after")
    def validate_policy(self) -> Self:
        if self.preferred_closed_trades_per_30_days < self.target_closed_trades_per_30_days:
            raise ValueError("preferred trade objective cannot be below target")
        if not (
            self.exploratory_risk_multiplier
            <= self.standard_risk_multiplier
            <= self.strong_risk_multiplier
        ):
            raise ValueError("risk recommendations must increase with confidence")
        return self

    @property
    def configuration_fingerprint(self) -> str:
        return fingerprint(self)


class DemoCampaignConfiguration(OpportunityConfigurationModel):
    enabled: bool = False
    environment: Literal["DEMO"] = "DEMO"
    duration_days: int = Field(default=30, ge=1, le=365)
    starting_balance_reference: Decimal = Field(default=Decimal("20000"), gt=0)
    stretch_return_target_percent: Decimal = Field(default=Decimal("100"), gt=0)
    maximum_daily_loss_percent: Decimal = Field(default=Decimal("1.0"), gt=0, le=100)
    maximum_weekly_drawdown_percent: Decimal = Field(default=Decimal("3.0"), gt=0, le=100)
    maximum_campaign_drawdown_percent: Decimal = Field(default=Decimal("8.0"), gt=0, le=100)
    maximum_consecutive_losses: int = Field(default=10, ge=1)
    maximum_execution_incidents: int = Field(default=1, ge=0)
    maximum_reconciliation_incidents: int = Field(default=1, ge=0)
    minimum_uptime_percent: Decimal = Field(default=Decimal("95"), ge=0, le=100)
    minimum_closed_trade_target: int = Field(default=100, ge=1)
    preferred_closed_trade_target: int = Field(default=250, ge=1)

    @model_validator(mode="after")
    def validate_limits(self) -> Self:
        if not (
            self.maximum_daily_loss_percent
            <= self.maximum_weekly_drawdown_percent
            <= self.maximum_campaign_drawdown_percent
        ):
            raise ValueError("campaign loss limits must increase by horizon")
        if self.preferred_closed_trade_target < self.minimum_closed_trade_target:
            raise ValueError("preferred campaign target cannot be below minimum")
        return self

    @property
    def configuration_fingerprint(self) -> str:
        return fingerprint(self)


def default_market_universe() -> tuple[MarketDefinition, ...]:
    epics = {
        "EUR/USD": "CS.D.EURUSD.CFD.IP",
        "GBP/USD": "CS.D.GBPUSD.CFD.IP",
        "USD/JPY": "CS.D.USDJPY.CFD.IP",
        "AUD/USD": "CS.D.AUDUSD.CFD.IP",
        "USD/CAD": "CS.D.USDCAD.CFD.IP",
        "EUR/JPY": "CS.D.EURJPY.CFD.IP",
    }
    values = []
    for instrument, epic in epics.items():
        base, quote = instrument.split("/")
        groups = (f"{base}_LONG", f"{quote}_SHORT")
        values.append(
            MarketDefinition(
                instrument_id=instrument,
                epic=epic,
                base_currency=base,
                quote_currency=quote,
                minimum_trade_size=Decimal("0.5"),
                decimal_precision=5 if quote != "JPY" else 3,
                pip_or_point_value=Decimal("0.0001") if quote != "JPY" else Decimal("0.01"),
                supported_timeframes=(
                    ContextTimeframe.MINUTE_5,
                    ContextTimeframe.MINUTE_15,
                    ContextTimeframe.HOUR,
                ),
                enabled_strategy_families=(
                    "TREND_REGIME",
                    "TREND_PULLBACK",
                    "VOLATILITY_BREAKOUT",
                    "RANGE_MEAN_REVERSION",
                ),
                maximum_acceptable_spread=Decimal("12"),
                session_policy="FX_CONTINUOUS_EX_ROLLOVER",
                correlation_groups=groups,
            )
        )
    return tuple(values)


class MarketUniverse(OpportunityConfigurationModel):
    markets: tuple[MarketDefinition, ...] = Field(default_factory=default_market_universe)

    @model_validator(mode="after")
    def validate_unique(self) -> Self:
        if not self.markets:
            raise ValueError("market universe cannot be empty")
        instruments = [item.instrument_id for item in self.markets]
        epics = [item.epic for item in self.markets]
        if len(instruments) != len(set(instruments)):
            raise ValueError("market instrument IDs must be unique")
        if len(epics) != len(set(epics)):
            raise ValueError("market epics must be unique")
        return self

    def require_enabled(self, instrument_id: str) -> MarketDefinition:
        market = next((item for item in self.markets if item.instrument_id == instrument_id), None)
        if market is None or not market.enabled:
            raise ValueError("instrument is not enabled in the governed universe")
        return market

    @property
    def configuration_fingerprint(self) -> str:
        return fingerprint(self)


def _contains_float(value: object) -> bool:
    if isinstance(value, float):
        return True
    if isinstance(value, dict):
        return any(_contains_float(item) for item in value.values())
    if isinstance(value, (tuple, list)):
        return any(_contains_float(item) for item in value)
    return False
