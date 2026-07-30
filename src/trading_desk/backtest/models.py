"""Strict immutable models for leakage-controlled simulation results."""

from __future__ import annotations

import math
from datetime import datetime
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from trading_desk.strategy.models import (
    Regime,
    StrategyAction,
    StrategyBarResolution,
    StrategyVariant,
)


class StrictBacktestModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class DatasetSplit(StrEnum):
    TRAIN = "TRAIN"
    VALIDATION = "VALIDATION"
    TEST = "TEST"


class FittingWindowPolicy(StrEnum):
    EXPANDING = "EXPANDING"
    ROLLING = "ROLLING"


class IntrabarAmbiguityPolicy(StrEnum):
    ADVERSE_FIRST = "ADVERSE_FIRST"
    FAVORABLE_FIRST = "FAVORABLE_FIRST"
    SKIP_AMBIGUOUS_BAR = "SKIP_AMBIGUOUS_BAR"


class FillSide(StrEnum):
    ENTRY = "ENTRY"
    EXIT = "EXIT"


class FillPriceMode(StrEnum):
    NEXT_OPEN = "NEXT_OPEN"
    NEXT_CLOSE = "NEXT_CLOSE"
    PROTECTIVE_STOP_LEVEL = "PROTECTIVE_STOP_LEVEL"
    PROFIT_TARGET_LEVEL = "PROFIT_TARGET_LEVEL"
    END_OF_BAR_EXIT = "END_OF_BAR_EXIT"


class ExitReason(StrEnum):
    STRATEGY_EXIT = "STRATEGY_EXIT"
    EXHAUSTION = "EXHAUSTION"
    PROTECTIVE_STOP = "PROTECTIVE_STOP"
    PROFIT_TARGET = "PROFIT_TARGET"
    MAXIMUM_HOLDING_PERIOD = "MAXIMUM_HOLDING_PERIOD"
    FORCED_END_OF_DATA_LIQUIDATION = "FORCED_END_OF_DATA_LIQUIDATION"


class UnresolvedPositionReason(StrEnum):
    NO_VALID_EXIT_QUOTE = "NO_VALID_EXIT_QUOTE"


class BenchmarkName(StrEnum):
    CASH = "CASH"
    BUY_AND_HOLD = "BUY_AND_HOLD"
    BASELINE_ONLY = "BASELINE_ONLY"


class MetricValue(StrictBacktestModel):
    available: bool
    value: float | None = None
    reason: str | None = None


class DataQualityFinding(StrictBacktestModel):
    code: str
    message: str
    blocking: bool = True
    row_number: int | None = Field(default=None, ge=1)


class BacktestBar(StrictBacktestModel):
    epic: str = Field(min_length=1, max_length=80)
    timestamp: datetime
    open_bid: float
    open_ask: float
    high_bid: float
    high_ask: float
    low_bid: float
    low_ask: float
    close_bid: float
    close_ask: float
    last_traded_volume: float | None = None
    market_status: str = "TRADEABLE"

    @model_validator(mode="after")
    def validate_prices(self) -> Self:
        if self.timestamp.tzinfo is None:
            raise ValueError("bar timestamps must include a timezone")
        prices = (
            self.open_bid,
            self.open_ask,
            self.high_bid,
            self.high_ask,
            self.low_bid,
            self.low_ask,
            self.close_bid,
            self.close_ask,
        )
        if any(not math.isfinite(value) or value <= 0 for value in prices):
            raise ValueError("bar prices must be finite and positive")
        for bid, ask in (
            (self.open_bid, self.open_ask),
            (self.high_bid, self.high_ask),
            (self.low_bid, self.low_ask),
            (self.close_bid, self.close_ask),
        ):
            if bid > ask:
                raise ValueError("bid cannot exceed ask")
        if self.high_bid < max(self.open_bid, self.close_bid, self.low_bid):
            raise ValueError("bid OHLC relationship is invalid")
        if self.high_ask < max(self.open_ask, self.close_ask, self.low_ask):
            raise ValueError("ask OHLC relationship is invalid")
        if self.low_bid > min(self.open_bid, self.close_bid, self.high_bid):
            raise ValueError("bid OHLC relationship is invalid")
        if self.low_ask > min(self.open_ask, self.close_ask, self.high_ask):
            raise ValueError("ask OHLC relationship is invalid")
        if self.last_traded_volume is not None and (
            not math.isfinite(self.last_traded_volume) or self.last_traded_volume < 0
        ):
            raise ValueError("volume must be finite and non-negative")
        return self


class BacktestDataManifest(StrictBacktestModel):
    source_filename: str
    content_sha256: str = Field(min_length=64, max_length=64)
    row_count: int = Field(ge=0)
    first_timestamp: datetime
    last_timestamp: datetime
    resolution: StrategyBarResolution
    findings: tuple[DataQualityFinding, ...] = ()


class BacktestDataset(StrictBacktestModel):
    bars: tuple[BacktestBar, ...]
    manifest: BacktestDataManifest


class SplitPeriod(StrictBacktestModel):
    name: DatasetSplit
    start_index: int = Field(ge=0)
    end_index: int = Field(ge=0)
    start_timestamp: datetime
    end_timestamp: datetime


class ChronologicalSplits(StrictBacktestModel):
    train: SplitPeriod
    validation: SplitPeriod
    test: SplitPeriod


class BacktestSignal(StrictBacktestModel):
    index: int = Field(ge=0)
    timestamp: datetime
    split: DatasetSplit
    variant: StrategyVariant
    action: StrategyAction
    regime: Regime
    strategy_configuration_fingerprint: str
    rejection_reasons: tuple[str, ...]


class SimulatedOrder(StrictBacktestModel):
    signal_index: int = Field(ge=0)
    earliest_fill_index: int = Field(ge=0)
    side: FillSide
    variant: StrategyVariant
    reason: str


class SimulatedFill(StrictBacktestModel):
    signal_index: int = Field(ge=0)
    fill_index: int = Field(ge=0)
    timestamp: datetime
    side: FillSide
    quote_price: float
    midpoint_price: float
    fill_price: float
    quantity: float = Field(gt=0)
    slippage_cost: float = Field(ge=0)
    commission_cost: float = Field(ge=0)
    variant: StrategyVariant
    fill_price_mode: FillPriceMode


class BacktestTrade(StrictBacktestModel):
    epic: str
    variant: StrategyVariant
    signal_regime: Regime
    entry_fill: SimulatedFill
    exit_fill: SimulatedFill
    exit_reason: ExitReason
    holding_bars: int = Field(ge=0)
    holding_days: float = Field(ge=0)
    gross_pnl: float
    spread_impact: float = Field(ge=0)
    slippage_cost: float = Field(ge=0)
    commission_cost: float = Field(ge=0)
    funding_cost: float = Field(ge=0)
    guaranteed_stop_premium: float = Field(ge=0)
    total_cost: float = Field(ge=0)
    net_pnl: float
    intrabar_ambiguous: bool = False
    ambiguity_policy: IntrabarAmbiguityPolicy


class UnresolvedPosition(StrictBacktestModel):
    epic: str
    variant: StrategyVariant
    signal_regime: Regime
    entry_fill: SimulatedFill
    reason: UnresolvedPositionReason
    evaluation_end_index: int = Field(ge=0)
    evaluation_end_timestamp: datetime
    unrealized_pnl: float
    entry_costs: float = Field(ge=0)


class EquityPoint(StrictBacktestModel):
    index: int = Field(ge=0)
    timestamp: datetime
    equity: float
    cash: float
    unrealized_pnl: float
    gross_exposure: float = Field(ge=0)
    accumulated_costs: float = Field(ge=0)


class DrawdownPoint(StrictBacktestModel):
    index: int = Field(ge=0)
    timestamp: datetime
    equity: float
    peak_equity: float
    drawdown: float = Field(ge=0)


class PerformanceMetrics(StrictBacktestModel):
    variant: StrategyVariant
    starting_equity: float
    ending_equity: float
    gross_return: float
    net_return: float
    realized_net_pnl: float
    unresolved_position_count: int = Field(ge=0)
    annualized_return: MetricValue
    peak_equity: float
    maximum_drawdown: float
    drawdown_duration_bars: int = Field(ge=0)
    trade_count: int = Field(ge=0)
    winning_trades: int = Field(ge=0)
    losing_trades: int = Field(ge=0)
    win_rate: MetricValue
    average_gross_win: MetricValue
    average_gross_loss: MetricValue
    average_net_win: MetricValue
    average_net_loss: MetricValue
    largest_win: MetricValue
    largest_loss: MetricValue
    expectancy: MetricValue
    payoff_ratio: MetricValue
    profit_factor: MetricValue
    average_holding_period: MetricValue
    maximum_holding_period: int = Field(ge=0)
    turnover: float = Field(ge=0)
    exposure_time: float = Field(ge=0, le=1)
    sharpe_ratio: MetricValue
    sortino_ratio: MetricValue
    calmar_ratio: MetricValue
    downside_deviation: MetricValue
    volatility: MetricValue


class BenchmarkResult(StrictBacktestModel):
    name: BenchmarkName
    starting_equity: float
    ending_equity: float
    net_return: float
    total_cost: float = Field(ge=0)


class RejectionSummary(StrictBacktestModel):
    reason: str
    count: int = Field(ge=1)


class RegimePerformance(StrictBacktestModel):
    regime: Regime
    signals: int = Field(ge=0)
    fills: int = Field(ge=0)
    trades: int = Field(ge=0)
    net_pnl: float
    win_rate: MetricValue
    average_trade: MetricValue
    costs: float = Field(ge=0)


class ValidationMetricSummary(StrictBacktestModel):
    net_return: float
    maximum_drawdown: float = Field(ge=0)
    trade_count: int = Field(ge=0)


class BacktestRun(StrictBacktestModel):
    run_fingerprint: str
    strategy_configuration_fingerprint: str
    variant: StrategyVariant
    evaluation_split: DatasetSplit
    manifest: BacktestDataManifest
    splits: ChronologicalSplits
    signals: tuple[BacktestSignal, ...]
    fills: tuple[SimulatedFill, ...]
    trades: tuple[BacktestTrade, ...]
    unresolved_positions: tuple[UnresolvedPosition, ...]
    equity_curve: tuple[EquityPoint, ...]
    drawdown_curve: tuple[DrawdownPoint, ...]
    metrics: PerformanceMetrics
    benchmarks: tuple[BenchmarkResult, ...]
    rejections: tuple[RejectionSummary, ...]
    regime_performance: tuple[RegimePerformance, ...]
    runtime_versions: tuple[tuple[str, str], ...]
    fitting_window_policy: FittingWindowPolicy
    forced_end_of_data_closures: int = Field(ge=0)


class ValidationComparison(StrictBacktestModel):
    report_fingerprint: str = Field(min_length=64, max_length=64)
    baseline_variant: StrategyVariant
    dataset_content_sha256: str = Field(min_length=64, max_length=64)
    dataset_source_filename: str
    splits: ChronologicalSplits
    validation_run_fingerprints: tuple[str, ...]
    variants: tuple[StrategyVariant, ...]
    validation_net_returns: tuple[float, ...]
    validation_maximum_drawdowns: tuple[float, ...]
    validation_trade_counts: tuple[int, ...]


class FinalTestReport(StrictBacktestModel):
    report_type: Literal["FINAL_TEST"] = "FINAL_TEST"
    selection_identifier: str = Field(min_length=64, max_length=64)
    selected_variant: StrategyVariant
    run: BacktestRun
