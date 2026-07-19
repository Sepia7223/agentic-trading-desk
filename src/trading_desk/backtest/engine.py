"""Chronological walk-forward simulation engine."""

from __future__ import annotations

from collections import Counter

from trading_desk.backtest.configuration import (
    BacktestConfiguration,
    FrozenSelection,
    runtime_versions,
)
from trading_desk.backtest.data import strategy_data_from_bars
from trading_desk.backtest.execution import (
    create_trade,
    end_of_data_fill,
    fill_pending_order,
    profit_target_fill,
    protective_stop_fill,
    resolve_intrabar_ambiguity,
)
from trading_desk.backtest.metrics import calculate_drawdowns, calculate_metrics
from trading_desk.backtest.models import (
    BacktestDataset,
    BacktestRun,
    BacktestSignal,
    BacktestTrade,
    BenchmarkName,
    BenchmarkResult,
    DatasetSplit,
    ExitReason,
    FillSide,
    MetricValue,
    RegimePerformance,
    RejectionSummary,
    SimulatedFill,
    SimulatedOrder,
    UnresolvedPosition,
    UnresolvedPositionReason,
)
from trading_desk.backtest.portfolio import BacktestPortfolio
from trading_desk.backtest.splits import build_chronological_splits, split_for_index
from trading_desk.strategy.baseline import evaluate_baseline
from trading_desk.strategy.configuration import StrategyConfiguration
from trading_desk.strategy.models import Regime, StrategyAction, StrategyContext
from trading_desk.strategy.pipeline import RegimeAwareStrategyPipeline


class BacktestEngine:
    """Run one deterministic variant on validation or an authorized final test."""

    def __init__(
        self,
        configuration: BacktestConfiguration,
        strategy_configuration: StrategyConfiguration | None = None,
        *,
        final_test_selection: FrozenSelection | None = None,
    ) -> None:
        self.configuration = configuration
        base = strategy_configuration or StrategyConfiguration()
        self.strategy_configuration = base.model_copy(update={"variant": configuration.variant})
        self.final_test_selection = final_test_selection
        if configuration.evaluation_split is DatasetSplit.TEST:
            if final_test_selection is None:
                raise ValueError("TEST evaluation requires a frozen selection artifact")
            if (
                final_test_selection.computed_identifier
                != final_test_selection.selection_identifier
            ):
                raise ValueError("frozen selection identifier mismatch")
            expected = final_test_selection.backtest_configuration.model_copy(
                update={"evaluation_split": DatasetSplit.TEST}
            )
            if configuration != expected:
                raise ValueError("TEST configuration differs from frozen selection")
            if self.strategy_configuration != final_test_selection.strategy_configuration:
                raise ValueError("TEST strategy configuration differs from frozen selection")
        elif final_test_selection is not None:
            raise ValueError("frozen selection artifacts are only valid for TEST evaluation")
        if (
            configuration.maximum_rolling_window is not None
            and configuration.maximum_rolling_window
            < self.strategy_configuration.minimum_bars_required
        ):
            raise ValueError("rolling window is shorter than strategy history requirements")

    def run(self, dataset: BacktestDataset) -> BacktestRun:
        if dataset.manifest.resolution is not self.configuration.resolution:
            raise ValueError("dataset and backtest resolutions differ")
        if dataset.bars[0].epic != self.configuration.epic:
            raise ValueError("dataset EPIC differs from backtest configuration")
        splits = build_chronological_splits(
            dataset,
            self.configuration.splits,
            self.strategy_configuration.minimum_bars_required,
        )
        if self.final_test_selection is not None:
            if dataset.manifest.content_sha256 != self.final_test_selection.dataset_content_sha256:
                raise ValueError("TEST dataset differs from frozen selection")
            if splits != self.final_test_selection.chronological_splits:
                raise ValueError("TEST splits differ from frozen selection")
            expected_validation_fingerprint = (
                self.final_test_selection.backtest_configuration.fingerprint(
                    self.final_test_selection.strategy_configuration,
                    dataset.manifest.content_sha256,
                )
            )
            if (
                expected_validation_fingerprint
                != self.final_test_selection.validation_run_fingerprint
            ):
                raise ValueError("frozen validation configuration fingerprint mismatch")
        pipeline = RegimeAwareStrategyPipeline(self.strategy_configuration)
        portfolio = BacktestPortfolio.create(self.configuration.initial_capital)
        signals: list[BacktestSignal] = []
        fills: list[SimulatedFill] = []
        trades: list[BacktestTrade] = []
        equity = []
        rejection_counts: Counter[str] = Counter()
        pending: SimulatedOrder | None = None
        pending_exit_reason: ExitReason | None = None
        forced_closures = 0
        unresolved_positions: list[UnresolvedPosition] = []
        bars = dataset.bars
        evaluation_period = (
            splits.validation
            if self.configuration.evaluation_split is DatasetSplit.VALIDATION
            else splits.test
        )
        warmup_index = max(
            self.strategy_configuration.minimum_bars_required - 1,
            evaluation_period.start_index,
        )

        for index, bar in enumerate(bars):
            if index > evaluation_period.end_index:
                break
            if pending is not None and index >= pending.earliest_fill_index:
                fill, failure = fill_pending_order(
                    pending,
                    bars[: index + 1],
                    self.configuration,
                )
                if fill is not None:
                    fills.append(fill)
                    if fill.side is FillSide.ENTRY:
                        signal = next(
                            item for item in reversed(signals) if item.index == pending.signal_index
                        )
                        portfolio.open(fill, signal.regime)
                    else:
                        if portfolio.position is None or pending_exit_reason is None:
                            raise RuntimeError("simulated exit has no open position")
                        trade = create_trade(
                            self.configuration.epic,
                            portfolio.position.signal_regime,
                            portfolio.position.entry_fill,
                            fill,
                            pending_exit_reason,
                            self.configuration,
                        )
                        trades.append(trade)
                        portfolio.close(trade)
                    pending = None
                    pending_exit_reason = None
                elif (
                    index >= pending.signal_index + self.configuration.maximum_execution_delay_bars
                ):
                    rejection_counts[failure or "FILL_REJECTED"] += 1
                    pending = None
                    pending_exit_reason = None

            if portfolio.position is not None and pending is None:
                entry_fill = portfolio.position.entry_fill
                stop_level = entry_fill.fill_price * (
                    1.0 - self.configuration.protective_stop_bps / 10_000.0
                )
                target_level = (
                    entry_fill.fill_price * (1.0 + self.configuration.profit_target_bps / 10_000.0)
                    if self.configuration.profit_target_bps is not None
                    else float("inf")
                )
                outcome = resolve_intrabar_ambiguity(
                    bar.low_bid,
                    bar.high_bid,
                    stop_level,
                    target_level,
                    self.configuration.ambiguity_policy,
                    entry_fill=entry_fill,
                    bar_index=index,
                )
                exit_fill: SimulatedFill | None = None
                exit_reason: ExitReason | None = None
                if outcome == "STOP":
                    exit_fill = protective_stop_fill(entry_fill, bar, index, self.configuration)
                    exit_reason = ExitReason.PROTECTIVE_STOP
                elif outcome == "TARGET":
                    exit_fill = profit_target_fill(entry_fill, bar, index, self.configuration)
                    exit_reason = ExitReason.PROFIT_TARGET
                if exit_fill is not None and exit_reason is not None:
                    fills.append(exit_fill)
                    trade = create_trade(
                        self.configuration.epic,
                        portfolio.position.signal_regime,
                        entry_fill,
                        exit_fill,
                        exit_reason,
                        self.configuration,
                    )
                    trades.append(trade)
                    portfolio.close(trade)

            if index >= warmup_index:
                split = split_for_index(index, splits)
                strategy_data = self._strategy_window(bars, index)
                context = _context(strategy_data, portfolio.position is not None)
                candidate = pipeline.analyze_latest(strategy_data, context)
                signal = BacktestSignal(
                    index=index,
                    timestamp=bar.timestamp,
                    split=split,
                    variant=self.configuration.variant,
                    action=candidate.action,
                    regime=candidate.current_regime,
                    strategy_configuration_fingerprint=candidate.configuration_fingerprint,
                    rejection_reasons=candidate.rejection_reasons,
                )
                signals.append(signal)
                rejection_counts.update(candidate.rejection_reasons)

                if split is self.configuration.evaluation_split and pending is None:
                    if (
                        portfolio.position is None
                        and candidate.action is StrategyAction.LONG_CANDIDATE
                    ):
                        if index + 1 <= evaluation_period.end_index:
                            pending = SimulatedOrder(
                                signal_index=index,
                                earliest_fill_index=index + 1,
                                side=FillSide.ENTRY,
                                variant=self.configuration.variant,
                                reason="LONG_CANDIDATE",
                            )
                        else:
                            rejection_counts["NEXT_BAR_UNAVAILABLE"] += 1
                    elif portfolio.position is not None:
                        baseline = evaluate_baseline(strategy_data, context)
                        reason = _exit_reason(
                            baseline.original_decision,
                            baseline.exhaustion_flags,
                            index - portfolio.position.entry_fill.fill_index,
                            self.configuration.maximum_holding_bars,
                        )
                        if reason is not None and index + 1 <= evaluation_period.end_index:
                            pending = SimulatedOrder(
                                signal_index=index,
                                earliest_fill_index=index + 1,
                                side=FillSide.EXIT,
                                variant=self.configuration.variant,
                                reason=reason.value,
                            )
                            pending_exit_reason = reason

            if index >= evaluation_period.start_index:
                equity.append(portfolio.equity_point(bar, index))

        if portfolio.position is not None:
            final_index = evaluation_period.end_index
            final_fill = end_of_data_fill(
                portfolio.position.entry_fill,
                bars,
                final_index,
                self.configuration,
            )
            if final_fill is not None:
                fills.append(final_fill)
                trade = create_trade(
                    self.configuration.epic,
                    portfolio.position.signal_regime,
                    portfolio.position.entry_fill,
                    final_fill,
                    ExitReason.FORCED_END_OF_DATA_LIQUIDATION,
                    self.configuration,
                )
                trades.append(trade)
                portfolio.close(trade)
                forced_closures = 1
                equity[-1] = portfolio.equity_point(bars[final_index], final_index)
            else:
                final_equity = equity[-1]
                unresolved_positions.append(
                    UnresolvedPosition(
                        epic=self.configuration.epic,
                        variant=self.configuration.variant,
                        signal_regime=portfolio.position.signal_regime,
                        entry_fill=portfolio.position.entry_fill,
                        reason=UnresolvedPositionReason.NO_VALID_EXIT_QUOTE,
                        evaluation_end_index=final_index,
                        evaluation_end_timestamp=bars[final_index].timestamp,
                        unrealized_pnl=final_equity.unrealized_pnl,
                        entry_costs=portfolio.position.entry_cost,
                    )
                )
                entry_index = portfolio.position.entry_fill.fill_index
                equity = [
                    point.model_copy(
                        update={
                            "equity": point.cash,
                            "unrealized_pnl": 0.0,
                            "gross_exposure": 0.0,
                        }
                    )
                    if point.index >= entry_index
                    else point
                    for point in equity
                ]

        equity_tuple = tuple(equity)
        trade_tuple = tuple(trades)
        metrics = calculate_metrics(
            self.configuration.variant,
            self.configuration.initial_capital,
            equity_tuple,
            trade_tuple,
            self.configuration.resolved_annualization_factor(),
            unresolved_position_count=len(unresolved_positions),
        )
        return BacktestRun(
            run_fingerprint=self.configuration.fingerprint(
                self.strategy_configuration, dataset.manifest.content_sha256
            ),
            strategy_configuration_fingerprint=self.strategy_configuration.fingerprint,
            variant=self.configuration.variant,
            evaluation_split=self.configuration.evaluation_split,
            manifest=dataset.manifest,
            splits=splits,
            signals=tuple(signals),
            fills=tuple(fills),
            trades=trade_tuple,
            unresolved_positions=tuple(unresolved_positions),
            equity_curve=equity_tuple,
            drawdown_curve=calculate_drawdowns(equity_tuple),
            metrics=metrics,
            benchmarks=_benchmarks(
                dataset,
                evaluation_period.start_index,
                evaluation_period.end_index,
                self.configuration,
            ),
            rejections=tuple(
                RejectionSummary(reason=reason, count=count)
                for reason, count in sorted(rejection_counts.items())
                if count > 0
            ),
            regime_performance=_regime_performance(tuple(signals), tuple(fills), trade_tuple),
            runtime_versions=runtime_versions(),
            fitting_window_policy=self.configuration.fitting_window_policy,
            forced_end_of_data_closures=forced_closures,
        )

    def _strategy_window(self, bars: tuple, cutoff: int):  # type: ignore[no-untyped-def]
        start = 0
        if self.configuration.fitting_window_policy.value == "ROLLING":
            assert self.configuration.maximum_rolling_window is not None
            start = max(0, cutoff + 1 - self.configuration.maximum_rolling_window)
        return strategy_data_from_bars(
            bars[start : cutoff + 1],
            self.configuration.resolution,
        )


def _context(data, holding: bool) -> StrategyContext:  # type: ignore[no-untyped-def]
    return StrategyContext(
        holding=holding,
        macro_score=None,
        current_spread=data.spreads[-1],
        current_spread_bps=data.spread_bps[-1],
        market_status=data.market_status,
        current_time=data.timestamps[-1],
    )


def _exit_reason(
    decision: str,
    exhaustion: tuple[str, ...],
    holding_bars: int,
    maximum_holding_bars: int,
) -> ExitReason | None:
    if len(exhaustion) >= 2:
        return ExitReason.EXHAUSTION
    if decision.startswith("EXIT"):
        return ExitReason.STRATEGY_EXIT
    if holding_bars >= maximum_holding_bars:
        return ExitReason.MAXIMUM_HOLDING_PERIOD
    return None


def _benchmarks(
    dataset: BacktestDataset,
    start_index: int,
    end_index: int,
    configuration: BacktestConfiguration,
) -> tuple[BenchmarkResult, ...]:
    results: list[BenchmarkResult] = []
    if configuration.enable_cash_benchmark:
        results.append(
            BenchmarkResult(
                name=BenchmarkName.CASH,
                starting_equity=configuration.initial_capital,
                ending_equity=configuration.initial_capital,
                net_return=0.0,
                total_cost=0.0,
            )
        )
    if configuration.enable_buy_and_hold_benchmark:
        first, last = dataset.bars[start_index], dataset.bars[end_index]
        entry_midpoint = (first.open_bid + first.open_ask) / 2
        exit_midpoint = (last.close_bid + last.close_ask) / 2
        entry = first.open_ask * (1 + configuration.slippage_bps / 10_000)
        exit_price = last.close_bid * (1 - configuration.slippage_bps / 10_000)
        commissions = 2 * configuration.fixed_commission_per_side + (
            (entry + exit_price)
            * configuration.fixed_quantity
            * configuration.proportional_commission_bps
            / 10_000
        )
        funding = (
            entry
            * configuration.fixed_quantity
            * configuration.overnight_funding_bps_per_day
            / 10_000
            * max((last.timestamp - first.timestamp).total_seconds() / 86400, 0)
        )
        gross_pnl = (exit_midpoint - entry_midpoint) * configuration.fixed_quantity
        executable_pnl = (exit_price - entry) * configuration.fixed_quantity - commissions - funding
        total_cost = max(gross_pnl - executable_pnl, 0.0)
        results.append(
            BenchmarkResult(
                name=BenchmarkName.BUY_AND_HOLD,
                starting_equity=configuration.initial_capital,
                ending_equity=configuration.initial_capital + executable_pnl,
                net_return=executable_pnl / configuration.initial_capital,
                total_cost=total_cost,
            )
        )
    return tuple(results)


def _regime_performance(
    signals: tuple[BacktestSignal, ...],
    fills: tuple[SimulatedFill, ...],
    trades: tuple[BacktestTrade, ...],
) -> tuple[RegimePerformance, ...]:
    results = []
    for regime in Regime:
        regime_signals = tuple(item for item in signals if item.regime is regime)
        regime_trades = tuple(item for item in trades if item.signal_regime is regime)
        signal_indices = {item.index for item in regime_signals}
        regime_fills = tuple(item for item in fills if item.signal_index in signal_indices)
        wins = sum(item.net_pnl > 0 for item in regime_trades)
        results.append(
            RegimePerformance(
                regime=regime,
                signals=len(regime_signals),
                fills=len(regime_fills),
                trades=len(regime_trades),
                net_pnl=sum(item.net_pnl for item in regime_trades),
                win_rate=(
                    MetricValue(available=True, value=wins / len(regime_trades))
                    if regime_trades
                    else MetricValue(available=False, reason="no trades in regime")
                ),
                average_trade=(
                    MetricValue(
                        available=True,
                        value=sum(item.net_pnl for item in regime_trades) / len(regime_trades),
                    )
                    if regime_trades
                    else MetricValue(available=False, reason="no trades in regime")
                ),
                costs=sum(item.total_cost for item in regime_trades),
            )
        )
    return tuple(results)
