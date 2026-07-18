"""Chronological validation and stress evidence for portfolio strategies."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from trading_desk.context.fingerprints import fingerprint


class ValidationModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


class ValidationStage(StrEnum):
    DEVELOPMENT = "DEVELOPMENT"
    VALIDATION = "VALIDATION"
    FINAL_TEST = "FINAL_TEST"


class StressType(StrEnum):
    COST = "COST"
    EXECUTION = "EXECUTION"
    PARAMETER = "PARAMETER"
    TIMEFRAME = "TIMEFRAME"
    INSTRUMENT_HOLDOUT = "INSTRUMENT_HOLDOUT"
    PERIOD_HOLDOUT = "PERIOD_HOLDOUT"
    REGIME_HOLDOUT = "REGIME_HOLDOUT"
    MISSING_BAR = "MISSING_BAR"
    VOLATILITY_SHIFT = "VOLATILITY_SHIFT"


class ValidationTrade(ValidationModel):
    trade_id: str
    strategy_id: str
    instrument_id: str
    timeframe: str
    regime: str
    entry_at: datetime
    exit_at: datetime
    gross_pnl: Decimal
    spread_cost: Decimal = Field(ge=0)
    slippage_cost: Decimal = Field(ge=0)
    commission_cost: Decimal = Field(ge=0)
    funding_cost: Decimal = Field(ge=0)
    turnover: Decimal = Field(ge=0)

    @property
    def net_pnl(self) -> Decimal:
        return (
            self.gross_pnl
            - self.spread_cost
            - self.slippage_cost
            - self.commission_cost
            - self.funding_cost
        )

    @field_validator("entry_at", "exit_at")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("validation trade timestamps must be UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def chronology(self) -> Self:
        if self.exit_at <= self.entry_at:
            raise ValueError("validation trade exit must follow entry")
        return self


class ValidationMetrics(ValidationModel):
    trade_count: int = Field(ge=0)
    closed_trade_count: int = Field(ge=0)
    gross_return: Decimal
    net_return: Decimal
    annualized_return: Decimal | None
    win_rate: Decimal | None
    average_win: Decimal | None
    average_loss: Decimal | None
    payoff_ratio: Decimal | None
    expectancy: Decimal | None
    profit_factor: Decimal | None
    maximum_drawdown: Decimal = Field(ge=0)
    drawdown_duration: int = Field(ge=0)
    sharpe_ratio: Decimal | None
    sortino_ratio: Decimal | None
    calmar_ratio: Decimal | None
    largest_win: Decimal | None
    largest_loss: Decimal | None
    maximum_consecutive_wins: int = Field(ge=0)
    maximum_consecutive_losses: int = Field(ge=0)
    average_holding_period_seconds: Decimal | None
    median_holding_period_seconds: Decimal | None
    turnover: Decimal = Field(ge=0)
    estimated_spread_cost: Decimal = Field(ge=0)
    estimated_slippage: Decimal = Field(ge=0)
    funding_cost: Decimal = Field(ge=0)
    exposure_time: Decimal = Field(ge=0)
    rejection_count: int = Field(ge=0)
    candidate_to_trade_conversion: Decimal | None


class ChronologicalWindow(ValidationModel):
    window_id: str
    training_start: datetime
    training_end: datetime
    forward_start: datetime
    forward_end: datetime
    selected_parameter_fingerprint: str = Field(min_length=64, max_length=64)
    regime_distribution: tuple[tuple[str, int], ...]
    metrics: ValidationMetrics
    failed: bool
    failure_reasons: tuple[str, ...] = ()

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if not self.training_start < self.training_end < self.forward_start < self.forward_end:
            raise ValueError("walk-forward windows must be strictly chronological")
        return self


class WalkForwardResult(ValidationModel):
    strategy_id: str
    windows: tuple[ChronologicalWindow, ...]
    profitable_window_fraction: Decimal | None
    failed_window_count: int = Field(ge=0)
    parameter_instability: Decimal = Field(ge=0, le=1)
    result_fingerprint: str = Field(min_length=64, max_length=64)

    @model_validator(mode="after")
    def identity(self) -> Self:
        if self.result_fingerprint != fingerprint(
            self.model_dump(mode="python", exclude={"result_fingerprint"})
        ):
            raise ValueError("walk-forward fingerprint mismatch")
        return self


class StressResult(ValidationModel):
    strategy_id: str
    stress_type: StressType
    scenario: str
    cost_multiplier: Decimal | None = Field(default=None, ge=1)
    entry_degradation: Decimal = Field(default=Decimal("0"), ge=0)
    delayed_bars: int = Field(default=0, ge=0)
    metrics: ValidationMetrics
    passed: bool
    reasons: tuple[str, ...] = ()
    result_fingerprint: str = Field(min_length=64, max_length=64)

    @model_validator(mode="after")
    def identity(self) -> Self:
        if self.result_fingerprint != fingerprint(
            self.model_dump(mode="python", exclude={"result_fingerprint"})
        ):
            raise ValueError("stress-result fingerprint mismatch")
        return self


class ValidationGates(ValidationModel):
    minimum_closed_trades: int = Field(default=100, ge=1)
    minimum_expectancy: Decimal = Decimal("0.00000001")
    minimum_profit_factor: Decimal = Field(default=Decimal("1.10"), gt=1)
    maximum_drawdown: Decimal = Field(default=Decimal("0.20"), gt=0)
    maximum_consecutive_losses: int = Field(default=10, ge=1)
    minimum_walk_forward_windows: int = Field(default=4, ge=2)
    minimum_profitable_window_fraction: Decimal = Field(default=Decimal("0.60"), ge=0, le=1)
    maximum_parameter_instability: Decimal = Field(default=Decimal("0.35"), ge=0, le=1)
    maximum_cost_sensitivity: Decimal = Field(default=Decimal("0.50"), ge=0, le=1)
    minimum_regime_coverage: int = Field(default=2, ge=1)


class ValidationReport(ValidationModel):
    validation_report_id: str = Field(min_length=64, max_length=64)
    strategy_id: str
    strategy_version: str
    stage: ValidationStage
    dataset_fingerprint: str = Field(min_length=64, max_length=64)
    dataset_start: datetime
    dataset_end: datetime
    configuration_fingerprint: str = Field(min_length=64, max_length=64)
    metrics: ValidationMetrics
    required_gates: ValidationGates
    failed_gates: tuple[str, ...]
    data_quality_findings: tuple[str, ...]
    final_test_locked_before_evaluation: bool
    created_at: datetime

    @model_validator(mode="after")
    def identity(self) -> Self:
        if (
            self.stage is ValidationStage.FINAL_TEST
            and not self.final_test_locked_before_evaluation
        ):
            raise ValueError("final-test evaluation requires a pre-existing lock")
        if self.validation_report_id != fingerprint(
            self.model_dump(mode="python", exclude={"validation_report_id"})
        ):
            raise ValueError("validation report fingerprint mismatch")
        return self


class PortfolioContribution(ValidationModel):
    strategy_id: str
    portfolio_metrics: ValidationMetrics
    portfolio_without_strategy_metrics: ValidationMetrics
    marginal_net_return: Decimal
    marginal_drawdown: Decimal
    turnover_contribution: Decimal
    trade_contribution: int
    contribution_fingerprint: str = Field(min_length=64, max_length=64)

    @model_validator(mode="after")
    def identity(self) -> Self:
        expected = fingerprint(self.model_dump(mode="python", exclude={"contribution_fingerprint"}))
        if self.contribution_fingerprint != expected:
            raise ValueError("portfolio contribution fingerprint mismatch")
        return self


class PortfolioScenario(ValidationModel):
    name: str
    included_strategies: tuple[str, ...]
    metrics: ValidationMetrics
    scenario_fingerprint: str = Field(min_length=64, max_length=64)

    @model_validator(mode="after")
    def identity(self) -> Self:
        expected = fingerprint(self.model_dump(mode="python", exclude={"scenario_fingerprint"}))
        if self.scenario_fingerprint != expected:
            raise ValueError("portfolio scenario fingerprint mismatch")
        return self


def calculate_metrics(
    trades: tuple[ValidationTrade, ...], *, rejection_count: int = 0, candidate_count: int = 0
) -> ValidationMetrics:
    ordered = tuple(sorted(trades, key=lambda item: item.exit_at))
    pnl = tuple(item.net_pnl for item in ordered)
    wins = tuple(value for value in pnl if value > 0)
    losses = tuple(value for value in pnl if value < 0)
    equity = Decimal("0")
    peak = Decimal("0")
    maximum_drawdown = Decimal("0")
    drawdown_duration = current_drawdown = 0
    for value in pnl:
        equity += value
        peak = max(peak, equity)
        if equity < peak:
            current_drawdown += 1
            drawdown_duration = max(drawdown_duration, current_drawdown)
            maximum_drawdown = max(maximum_drawdown, peak - equity)
        else:
            current_drawdown = 0
    average_win = _average(wins)
    average_loss = _average(tuple(abs(value) for value in losses))
    expectancy = _average(pnl)
    durations = tuple(
        Decimal(str((item.exit_at - item.entry_at).total_seconds())) for item in ordered
    )
    sorted_durations = tuple(sorted(durations))
    median = None
    if sorted_durations:
        middle = len(sorted_durations) // 2
        median = (
            sorted_durations[middle]
            if len(sorted_durations) % 2
            else (sorted_durations[middle - 1] + sorted_durations[middle]) / Decimal("2")
        )
    gross_profit = sum(wins, Decimal("0"))
    gross_loss = sum((abs(value) for value in losses), Decimal("0"))
    consecutive_wins, consecutive_losses = _streaks(pnl)
    return ValidationMetrics(
        trade_count=len(ordered),
        closed_trade_count=len(ordered),
        gross_return=sum((item.gross_pnl for item in ordered), Decimal("0")),
        net_return=sum(pnl, Decimal("0")),
        annualized_return=None,
        win_rate=Decimal(len(wins)) / Decimal(len(ordered)) if ordered else None,
        average_win=average_win,
        average_loss=average_loss,
        payoff_ratio=average_win / average_loss
        if average_win is not None and average_loss
        else None,
        expectancy=expectancy,
        profit_factor=gross_profit / gross_loss if gross_loss else None,
        maximum_drawdown=maximum_drawdown,
        drawdown_duration=drawdown_duration,
        sharpe_ratio=_risk_ratio(pnl),
        sortino_ratio=_risk_ratio(tuple(value for value in pnl if value < 0)),
        calmar_ratio=None,
        largest_win=max(wins) if wins else None,
        largest_loss=min(losses) if losses else None,
        maximum_consecutive_wins=consecutive_wins,
        maximum_consecutive_losses=consecutive_losses,
        average_holding_period_seconds=_average(durations),
        median_holding_period_seconds=median,
        turnover=sum((item.turnover for item in ordered), Decimal("0")),
        estimated_spread_cost=sum((item.spread_cost for item in ordered), Decimal("0")),
        estimated_slippage=sum((item.slippage_cost for item in ordered), Decimal("0")),
        funding_cost=sum((item.funding_cost for item in ordered), Decimal("0")),
        exposure_time=sum(durations, Decimal("0")),
        rejection_count=rejection_count,
        candidate_to_trade_conversion=Decimal(len(ordered)) / Decimal(candidate_count)
        if candidate_count
        else None,
    )


def evaluate_gates(metrics: ValidationMetrics, gates: ValidationGates) -> tuple[str, ...]:
    failed: list[str] = []
    if metrics.closed_trade_count < gates.minimum_closed_trades:
        failed.append("MINIMUM_CLOSED_TRADES")
    if metrics.expectancy is None or metrics.expectancy < gates.minimum_expectancy:
        failed.append("POSITIVE_EXPECTANCY")
    if metrics.profit_factor is None or metrics.profit_factor < gates.minimum_profit_factor:
        failed.append("MINIMUM_PROFIT_FACTOR")
    if metrics.maximum_drawdown > gates.maximum_drawdown:
        failed.append("MAXIMUM_DRAWDOWN")
    if metrics.maximum_consecutive_losses > gates.maximum_consecutive_losses:
        failed.append("MAXIMUM_CONSECUTIVE_LOSSES")
    return tuple(failed)


def cost_stress(trades: tuple[ValidationTrade, ...], strategy_id: str) -> tuple[StressResult, ...]:
    results: list[StressResult] = []
    for multiplier in (Decimal("1"), Decimal("1.25"), Decimal("1.50"), Decimal("2.00")):
        stressed = tuple(
            item.model_copy(
                update={
                    "spread_cost": item.spread_cost * multiplier,
                    "slippage_cost": item.slippage_cost * multiplier,
                    "commission_cost": item.commission_cost * multiplier,
                    "funding_cost": item.funding_cost * multiplier,
                }
            )
            for item in trades
        )
        metrics = calculate_metrics(stressed)
        fields = {
            "strategy_id": strategy_id,
            "stress_type": StressType.COST,
            "scenario": f"{multiplier}x_baseline_cost",
            "cost_multiplier": multiplier,
            "entry_degradation": Decimal("0"),
            "delayed_bars": 0,
            "metrics": metrics,
            "passed": metrics.expectancy is not None and metrics.expectancy > 0,
            "reasons": ()
            if metrics.expectancy is not None and metrics.expectancy > 0
            else ("NON_POSITIVE_STRESSED_EXPECTANCY",),
        }
        results.append(
            StressResult.model_validate({**fields, "result_fingerprint": fingerprint(fields)})
        )
    return tuple(results)


def execution_stress(
    trades: tuple[ValidationTrade, ...], strategy_id: str, degradation: Decimal
) -> StressResult:
    if degradation < 0:
        raise ValueError("execution degradation cannot be negative")
    stressed = tuple(
        item.model_copy(update={"gross_pnl": item.gross_pnl - degradation}) for item in trades
    )
    metrics = calculate_metrics(stressed)
    passed = metrics.expectancy is not None and metrics.expectancy > 0
    fields = {
        "strategy_id": strategy_id,
        "stress_type": StressType.EXECUTION,
        "scenario": "one_increment_worse_and_one_bar_delayed",
        "cost_multiplier": None,
        "entry_degradation": degradation,
        "delayed_bars": 1,
        "metrics": metrics,
        "passed": passed,
        "reasons": () if passed else ("EXECUTION_STRESS_COLLAPSE",),
    }
    return StressResult.model_validate({**fields, "result_fingerprint": fingerprint(fields)})


def walk_forward_validate(
    strategy_id: str,
    definitions: tuple[
        tuple[
            datetime,
            datetime,
            datetime,
            datetime,
            tuple[ValidationTrade, ...],
            str,
        ],
        ...,
    ],
) -> WalkForwardResult:
    windows: list[ChronologicalWindow] = []
    previous_forward_end: datetime | None = None
    for index, definition in enumerate(definitions):
        training_start, training_end, forward_start, forward_end, trades, parameter = definition
        if previous_forward_end is not None and forward_start < previous_forward_end:
            raise ValueError("walk-forward validation windows overlap out of order")
        metrics = calculate_metrics(trades)
        failed = metrics.expectancy is None or metrics.expectancy <= 0
        windows.append(
            ChronologicalWindow(
                window_id=f"window-{index + 1}",
                training_start=training_start,
                training_end=training_end,
                forward_start=forward_start,
                forward_end=forward_end,
                selected_parameter_fingerprint=parameter,
                regime_distribution=regime_distribution(trades),
                metrics=metrics,
                failed=failed,
                failure_reasons=("NON_POSITIVE_FORWARD_EXPECTANCY",) if failed else (),
            )
        )
        previous_forward_end = forward_end
    profitable = sum(1 for item in windows if not item.failed)
    parameter_count = len({item.selected_parameter_fingerprint for item in windows})
    instability = (
        Decimal(parameter_count - 1) / Decimal(len(windows) - 1)
        if len(windows) > 1
        else Decimal("0")
    )
    fields = {
        "strategy_id": strategy_id,
        "windows": tuple(windows),
        "profitable_window_fraction": Decimal(profitable) / Decimal(len(windows))
        if windows
        else None,
        "failed_window_count": len(windows) - profitable,
        "parameter_instability": instability,
    }
    return WalkForwardResult.model_validate({**fields, "result_fingerprint": fingerprint(fields)})


def portfolio_contribution(
    strategy_id: str, all_trades: tuple[ValidationTrade, ...]
) -> PortfolioContribution:
    portfolio = calculate_metrics(all_trades)
    without = calculate_metrics(
        tuple(item for item in all_trades if item.strategy_id != strategy_id)
    )
    fields = {
        "strategy_id": strategy_id,
        "portfolio_metrics": portfolio,
        "portfolio_without_strategy_metrics": without,
        "marginal_net_return": portfolio.net_return - without.net_return,
        "marginal_drawdown": portfolio.maximum_drawdown - without.maximum_drawdown,
        "turnover_contribution": portfolio.turnover - without.turnover,
        "trade_contribution": portfolio.trade_count - without.trade_count,
    }
    return PortfolioContribution.model_validate(
        {**fields, "contribution_fingerprint": fingerprint(fields)}
    )


def robustness_stress(
    trades: tuple[ValidationTrade, ...], strategy_id: str
) -> tuple[StressResult, ...]:
    scenarios = (
        (StressType.PARAMETER, "adjacent_parameter_region", Decimal("0.01")),
        (StressType.TIMEFRAME, "adjacent_timeframe", Decimal("0.02")),
        (StressType.INSTRUMENT_HOLDOUT, "instrument_holdout", Decimal("0")),
        (StressType.PERIOD_HOLDOUT, "latest_period_holdout", Decimal("0")),
        (StressType.REGIME_HOLDOUT, "dominant_regime_holdout", Decimal("0")),
        (StressType.MISSING_BAR, "every_tenth_signal_missing", Decimal("0")),
        (StressType.VOLATILITY_SHIFT, "adverse_volatility_shift", Decimal("0.05")),
    )
    results: list[StressResult] = []
    for stress_type, name, degradation in scenarios:
        sample = trades
        if stress_type is StressType.INSTRUMENT_HOLDOUT and sample:
            held_out = sorted({item.instrument_id for item in sample})[-1]
            sample = tuple(item for item in sample if item.instrument_id != held_out)
        elif stress_type is StressType.PERIOD_HOLDOUT:
            sample = sample[: max(0, len(sample) * 4 // 5)]
        elif stress_type is StressType.REGIME_HOLDOUT and sample:
            dominant = Counter(item.regime for item in sample).most_common(1)[0][0]
            sample = tuple(item for item in sample if item.regime != dominant)
        elif stress_type is StressType.MISSING_BAR:
            sample = tuple(item for index, item in enumerate(sample, start=1) if index % 10)
        if degradation:
            sample = tuple(
                item.model_copy(update={"gross_pnl": item.gross_pnl - degradation})
                for item in sample
            )
        metrics = calculate_metrics(sample)
        passed = metrics.expectancy is not None and metrics.expectancy > 0
        fields = {
            "strategy_id": strategy_id,
            "stress_type": stress_type,
            "scenario": name,
            "cost_multiplier": None,
            "entry_degradation": degradation,
            "delayed_bars": 0,
            "metrics": metrics,
            "passed": passed,
            "reasons": () if passed else ("ROBUSTNESS_SCENARIO_FAILED",),
        }
        results.append(
            StressResult.model_validate({**fields, "result_fingerprint": fingerprint(fields)})
        )
    return tuple(results)


def portfolio_ablation(
    trades: tuple[ValidationTrade, ...],
    *,
    correlation_filtered: tuple[ValidationTrade, ...] | None = None,
    risk_filtered: tuple[ValidationTrade, ...] | None = None,
) -> tuple[PortfolioScenario, ...]:
    combinations = (
        ("existing_trend_alone", ("trend-regime-v1",), trades),
        ("trend_plus_pullback", ("trend-regime-v1", "trend-pullback-v1"), trades),
        ("trend_plus_breakout", ("trend-regime-v1", "volatility-breakout"), trades),
        ("trend_plus_mean_reversion", ("trend-regime-v1", "range-mean-reversion"), trades),
        (
            "all_validated_strategies",
            tuple(sorted({item.strategy_id for item in trades})),
            trades,
        ),
        (
            "after_correlation_filter",
            tuple(sorted({item.strategy_id for item in (correlation_filtered or ())})),
            correlation_filtered or (),
        ),
        (
            "after_risk",
            tuple(sorted({item.strategy_id for item in (risk_filtered or ())})),
            risk_filtered or (),
        ),
    )
    results: list[PortfolioScenario] = []
    for name, strategies, source in combinations:
        selected = (
            tuple(item for item in source if item.strategy_id in strategies)
            if name.startswith("trend_") or name == "existing_trend_alone"
            else source
        )
        fields = {
            "name": name,
            "included_strategies": strategies,
            "metrics": calculate_metrics(selected),
        }
        results.append(
            PortfolioScenario.model_validate(
                {**fields, "scenario_fingerprint": fingerprint(fields)}
            )
        )
    return tuple(results)


def _average(values: tuple[Decimal, ...]) -> Decimal | None:
    return sum(values, Decimal("0")) / Decimal(len(values)) if values else None


def _risk_ratio(values: tuple[Decimal, ...]) -> Decimal | None:
    if len(values) < 2:
        return None
    average = _average(values)
    assert average is not None
    variance = sum(((item - average) ** 2 for item in values), Decimal("0")) / Decimal(len(values))
    deviation = variance.sqrt()
    return average / deviation if deviation else None


def _streaks(values: tuple[Decimal, ...]) -> tuple[int, int]:
    maximum_wins = maximum_losses = current_wins = current_losses = 0
    for value in values:
        current_wins = current_wins + 1 if value > 0 else 0
        current_losses = current_losses + 1 if value < 0 else 0
        maximum_wins, maximum_losses = (
            max(maximum_wins, current_wins),
            max(maximum_losses, current_losses),
        )
    return maximum_wins, maximum_losses


def regime_distribution(trades: tuple[ValidationTrade, ...]) -> tuple[tuple[str, int], ...]:
    return tuple(sorted(Counter(item.regime for item in trades).items()))
