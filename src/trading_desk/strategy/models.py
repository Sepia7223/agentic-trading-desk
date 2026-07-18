"""Strict immutable models for regime-aware deterministic strategy analysis."""

from __future__ import annotations

import math
from datetime import datetime
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictStrategyModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class StrategyAction(StrEnum):
    LONG_CANDIDATE = "LONG_CANDIDATE"
    WATCH = "WATCH"
    NO_TRADE = "NO_TRADE"


class StrategyVariant(StrEnum):
    BASELINE_ONLY = "BASELINE_ONLY"
    BASELINE_KALMAN = "BASELINE_KALMAN"
    BASELINE_HMM = "BASELINE_HMM"
    BASELINE_KALMAN_HMM = "BASELINE_KALMAN_HMM"


class StrategyBarResolution(StrEnum):
    MINUTE_5 = "MINUTE_5"
    MINUTE_15 = "MINUTE_15"
    DAY = "DAY"
    HOUR = "HOUR"
    HOUR_4 = "HOUR_4"


class MacroState(StrEnum):
    UNKNOWN = "UNKNOWN"
    ADVERSE = "ADVERSE"
    NEUTRAL = "NEUTRAL"
    FAVORABLE = "FAVORABLE"


class ExecutionTimingPolicy(StrEnum):
    NEXT_VALID_BAR = "NEXT_VALID_BAR"


class Regime(StrEnum):
    BULL_LOW_VOL = "BULL_LOW_VOL"
    TRANSITIONAL = "TRANSITIONAL"
    BEAR_HIGH_VOL = "BEAR_HIGH_VOL"
    UNKNOWN = "UNKNOWN"


class FindingCode(StrEnum):
    INSUFFICIENT_BARS = "INSUFFICIENT_BARS"
    SERIES_LENGTH_MISMATCH = "SERIES_LENGTH_MISMATCH"
    TIMESTAMPS_NOT_INCREASING = "TIMESTAMPS_NOT_INCREASING"
    NON_FINITE_VALUE = "NON_FINITE_VALUE"
    NON_POSITIVE_PRICE = "NON_POSITIVE_PRICE"
    INVALID_BID_ASK = "INVALID_BID_ASK"
    STALE_DATA = "STALE_DATA"
    FUTURE_DATA = "FUTURE_DATA"
    MARKET_NOT_TRADEABLE = "MARKET_NOT_TRADEABLE"
    SPREAD_TOO_WIDE = "SPREAD_TOO_WIDE"
    EXCESSIVE_TIME_GAP = "EXCESSIVE_TIME_GAP"
    INVALID_IG_BARS = "INVALID_IG_BARS"
    HOLDING_STATE_UNKNOWN = "HOLDING_STATE_UNKNOWN"
    MODEL_NOT_READY = "MODEL_NOT_READY"
    UNKNOWN_BAR_CADENCE = "UNKNOWN_BAR_CADENCE"


class StrategyMarketData(StrictStrategyModel):
    epic: str = Field(min_length=1, max_length=80)
    instrument_name: str = Field(min_length=1, max_length=200)
    timestamps: tuple[datetime, ...]
    open_midpoints: tuple[float, ...]
    high_midpoints: tuple[float, ...]
    low_midpoints: tuple[float, ...]
    close_midpoints: tuple[float, ...]
    bids: tuple[float | None, ...]
    asks: tuple[float | None, ...]
    spreads: tuple[float, ...]
    spread_bps: tuple[float, ...]
    volume: tuple[float | None, ...] | None = None
    market_status: str
    data_retrieval_time: datetime
    bar_resolution: StrategyBarResolution | None = None
    source_bar_count: int = Field(ge=0)
    excluded_invalid_bars: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_series_shape(self) -> Self:
        expected = len(self.timestamps)
        series = (
            self.open_midpoints,
            self.high_midpoints,
            self.low_midpoints,
            self.close_midpoints,
            self.bids,
            self.asks,
            self.spreads,
            self.spread_bps,
        )
        if any(len(values) != expected for values in series):
            raise ValueError("all market-data series must have equal lengths")
        if self.volume is not None and len(self.volume) != expected:
            raise ValueError("volume series length must match prices")
        if self.source_bar_count < expected + self.excluded_invalid_bars:
            raise ValueError("source bar count is inconsistent")
        if any(
            left >= right for left, right in zip(self.timestamps, self.timestamps[1:], strict=False)
        ):
            raise ValueError("timestamps must be unique and increasing")

        required_prices = (
            self.open_midpoints,
            self.high_midpoints,
            self.low_midpoints,
            self.close_midpoints,
        )
        if any(
            not math.isfinite(value) or value <= 0 for values in required_prices for value in values
        ):
            raise ValueError("required prices must be finite and positive")
        for index in range(expected):
            if self.high_midpoints[index] < self.low_midpoints[index]:
                raise ValueError("high price cannot be below low price")
            for value in (self.open_midpoints[index], self.close_midpoints[index]):
                if not self.low_midpoints[index] <= value <= self.high_midpoints[index]:
                    raise ValueError("open and close must fall within high/low")
            bid, ask = self.bids[index], self.asks[index]
            if bid is not None and (not math.isfinite(bid) or bid <= 0):
                raise ValueError("bid values must be finite and positive")
            if ask is not None and (not math.isfinite(ask) or ask <= 0):
                raise ValueError("ask values must be finite and positive")
            if bid is not None and ask is not None and bid > ask:
                raise ValueError("bid cannot exceed ask")
            spread = self.spreads[index]
            if not math.isfinite(spread) or spread < 0:
                raise ValueError("spreads must be finite and non-negative")
            normalized_spread = self.spread_bps[index]
            if not math.isfinite(normalized_spread) or normalized_spread < 0:
                raise ValueError("spread basis points must be finite and non-negative")
        if self.volume is not None:
            for volume_value in self.volume:
                if volume_value is not None and (
                    not math.isfinite(volume_value) or volume_value < 0
                ):
                    raise ValueError("volume must be finite and non-negative")
        if self.data_retrieval_time.tzinfo is None:
            raise ValueError("data retrieval time must be timezone-aware")
        if any(timestamp.tzinfo is None for timestamp in self.timestamps):
            raise ValueError("market timestamps must be timezone-aware")
        return self

    def sliced_through(self, cutoff_index: int) -> StrategyMarketData:
        if not 0 <= cutoff_index < len(self.timestamps):
            raise IndexError("cutoff index is outside market data")
        stop = cutoff_index + 1
        return self.model_copy(
            update={
                "timestamps": self.timestamps[:stop],
                "open_midpoints": self.open_midpoints[:stop],
                "high_midpoints": self.high_midpoints[:stop],
                "low_midpoints": self.low_midpoints[:stop],
                "close_midpoints": self.close_midpoints[:stop],
                "bids": self.bids[:stop],
                "asks": self.asks[:stop],
                "spreads": self.spreads[:stop],
                "spread_bps": self.spread_bps[:stop],
                "volume": self.volume[:stop] if self.volume is not None else None,
                "source_bar_count": stop,
                "excluded_invalid_bars": 0,
                "data_retrieval_time": self.timestamps[cutoff_index],
            }
        )


class StrategyContext(StrictStrategyModel):
    holding: bool | None
    macro_score: int | None = Field(default=None, ge=-2, le=2)
    current_spread: float = Field(ge=0)
    current_spread_bps: float = Field(ge=0)
    market_status: str
    current_time: datetime
    account_exposure_summary: str | None = None

    @model_validator(mode="after")
    def validate_context(self) -> Self:
        if not math.isfinite(self.current_spread) or not math.isfinite(self.current_spread_bps):
            raise ValueError("current spread values must be finite")
        if self.current_time.tzinfo is None:
            raise ValueError("current time must be timezone-aware")
        return self


class ValidationFinding(StrictStrategyModel):
    code: FindingCode
    message: str
    blocking: bool = True


class DataValidationResult(StrictStrategyModel):
    valid: bool
    findings: tuple[ValidationFinding, ...]


class MarketDataBuildResult(StrictStrategyModel):
    data: StrategyMarketData | None
    findings: tuple[ValidationFinding, ...]


class BaselineResult(StrictStrategyModel):
    trend_score: int
    trend_detail: str
    momentum_score: int
    momentum_detail: str
    macro_score: int | None
    total_pillar_score: int
    original_decision: str
    original_flags: tuple[str, ...]
    exhaustion_flags: tuple[str, ...]
    bearish_flags: tuple[str, ...]
    rebound_flags: tuple[str, ...]
    death_cross: bool
    relentless_bearish: bool


class KalmanStep(StrictStrategyModel):
    filtered_level: float
    filtered_slope: float
    predicted_level: float
    innovation: float
    innovation_variance: float
    normalized_innovation: float
    level_uncertainty: float
    slope_uncertainty: float
    normalized_slope: float
    normalized_slope_uncertainty: float


class KalmanTrendResult(StrictStrategyModel):
    ready: bool
    reason: str | None = None
    current_filtered_level: float | None = None
    current_slope: float | None = None
    current_slope_uncertainty: float | None = None
    current_normalized_slope: float | None = None
    current_normalized_slope_uncertainty: float | None = None
    normalized_price_deviation: float | None = None
    observations_used: int
    steps: tuple[KalmanStep, ...] = ()


class RegimeProbability(StrictStrategyModel):
    regime: Regime
    probability: float = Field(ge=0, le=1)


class StateMapping(StrictStrategyModel):
    hidden_state: int = Field(ge=0)
    regime: Regime


class StateMappingStatistic(StrictStrategyModel):
    hidden_state: int = Field(ge=0)
    mean_return: float
    mean_volatility: float
    mean_trend: float
    effective_observations: float = Field(ge=0)
    bull_score: float
    bear_score: float
    transitional_score: float


class FeatureStatistics(StrictStrategyModel):
    names: tuple[str, ...]
    means: tuple[float, ...]
    scales: tuple[float, ...]


class HMMRegimeResult(StrictStrategyModel):
    ready: bool
    reason: str | None = None
    current_regime: Regime = Regime.UNKNOWN
    probabilities: tuple[RegimeProbability, ...]
    selected_regime_probability: float = 0.0
    uncertainty: float = 1.0
    state_mapping: tuple[StateMapping, ...] = ()
    converged: bool = False
    observations_used: int = 0
    feature_statistics: FeatureStatistics | None = None
    probability_method: str = "endpoint_smoothed_posterior"
    mapping_statistics: tuple[StateMappingStatistic, ...] = ()
    fitting_warnings: tuple[str, ...] = ()
    endpoint_hidden_state_probabilities: tuple[float, ...] = ()

    def probability_for(self, regime: Regime) -> float:
        return next((item.probability for item in self.probabilities if item.regime is regime), 0.0)


class GateResult(StrictStrategyModel):
    name: str
    passed: bool
    reason: str


class ModelVersion(StrictStrategyModel):
    component: str
    version: str


class TradeCandidate(StrictStrategyModel):
    epic: str
    instrument_name: str
    evaluation_timestamp: datetime
    signal_timestamp: datetime
    data_cutoff_timestamp: datetime
    earliest_eligible_execution_timestamp: datetime | None
    execution_timing_policy: ExecutionTimingPolicy
    strategy_variant: StrategyVariant
    action: StrategyAction
    baseline_trend_score: int
    baseline_momentum_score: int
    macro_score: int | None
    macro_state: MacroState
    total_baseline_score: int
    current_regime: Regime
    regime_probabilities: tuple[RegimeProbability, ...]
    regime_uncertainty: float
    kalman_level: float | None
    kalman_slope: float | None
    kalman_slope_uncertainty: float | None
    kalman_normalized_slope: float | None
    kalman_normalized_slope_uncertainty: float | None
    normalized_price_deviation: float | None
    current_spread: float
    current_spread_bps: float
    validation_findings: tuple[ValidationFinding, ...]
    mandatory_gates: tuple[GateResult, ...]
    deterministic_reasons: tuple[str, ...]
    rejection_reasons: tuple[str, ...]
    model_versions: tuple[ModelVersion, ...]
    configuration_fingerprint: str
