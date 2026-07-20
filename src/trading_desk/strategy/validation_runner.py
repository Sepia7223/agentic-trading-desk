"""Chronological historical validation harness for portfolio strategies.

This module produces the governed :mod:`trading_desk.strategy.validation`
evidence (``ValidationTrade`` records) for the Milestone 12 strategy families by
replaying an approved local historical dataset strictly forward in time.

Boundaries:

- Research only. No broker adapter, credential, HTTP, journal-write, risk,
  or execution import. Output is evidence for human promotion review.
- Every evaluation uses observations at or before its explicit cutoff. Market
  context, Kalman state, and HMM state are built from bounded windows that end
  at the completed evaluation bar. HMM parameters are refitted on a fixed
  causal cadence; between refits the most recent strictly-older fit is reused,
  so model parameters are bounded-stale but never depend on future data.
- Entries fill on the next bar's ask-side open plus configured adverse
  slippage; exits fill from the bid side. Intrabar stop/target ambiguity is
  resolved adverse-first.
- Costs are itemized per trade: real bid/ask half-spreads, configured
  slippage, configured commission (zero by default, matching the governed
  Milestone 11 cost policy), and per-day funding.
- Bars strictly after the configured evaluation end are never read, which is
  what makes a locked final-test partition technically enforceable.
"""

from __future__ import annotations

import csv
import math
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from trading_desk.context.classifier import MarketContextEngine
from trading_desk.context.models import ContextTimeframe, MarketContextSnapshot, SessionState
from trading_desk.context.sessions import classify_session
from trading_desk.strategy.configuration import StrategyConfiguration
from trading_desk.strategy.contracts import (
    StrategyDecision,
    StrategyEvaluationResult,
    StrategyEvaluator,
    evaluation_context,
)
from trading_desk.strategy.invalidation import (
    InvalidationDecision,
    PositionEntryContext,
    evaluate_invalidation,
)
from trading_desk.strategy.kalman import fit_local_linear_trend
from trading_desk.strategy.models import (
    HMMRegimeResult,
    KalmanTrendResult,
    StrategyBarResolution,
    StrategyMarketData,
)
from trading_desk.strategy.regime import fit_regime_model
from trading_desk.strategy.validation import ValidationTrade

RESOLUTION_TIMEFRAMES: dict[StrategyBarResolution, ContextTimeframe] = {
    StrategyBarResolution.MINUTE_5: ContextTimeframe.MINUTE_5,
    StrategyBarResolution.MINUTE_15: ContextTimeframe.MINUTE_15,
    StrategyBarResolution.HOUR: ContextTimeframe.HOUR,
    StrategyBarResolution.HOUR_4: ContextTimeframe.HOUR_4,
    StrategyBarResolution.DAY: ContextTimeframe.DAY,
}

_PRICE_QUANTUM = Decimal("0.00000001")


class ValidationRunnerError(ValueError):
    """Raised when historical validation input cannot be used safely."""


@dataclass(frozen=True)
class HistoricalBar:
    timestamp: datetime
    open_bid: float
    open_ask: float
    high_bid: float
    high_ask: float
    low_bid: float
    low_ask: float
    close_bid: float
    close_ask: float
    volume: float

    @property
    def open_mid(self) -> float:
        return (self.open_bid + self.open_ask) / 2.0

    @property
    def high_mid(self) -> float:
        return (self.high_bid + self.high_ask) / 2.0

    @property
    def low_mid(self) -> float:
        return (self.low_bid + self.low_ask) / 2.0

    @property
    def close_mid(self) -> float:
        return (self.close_bid + self.close_ask) / 2.0


def load_bars(path: str | Path, *, epic: str) -> tuple[HistoricalBar, ...]:
    """Load a governed bid/ask OHLC CSV and enforce strict chronology."""

    source = Path(path)
    bars: list[HistoricalBar] = []
    with source.open("r", encoding="utf-8", newline="") as handle:
        for row_number, row in enumerate(csv.DictReader(handle), start=2):
            if row.get("epic") != epic:
                raise ValidationRunnerError(
                    f"row {row_number}: epic {row.get('epic')!r} does not match {epic!r}"
                )
            timestamp = datetime.fromisoformat(row["timestamp"])
            if timestamp.tzinfo is None:
                raise ValidationRunnerError(f"row {row_number}: naive timestamp")
            values = {
                name: float(row[name])
                for name in (
                    "open_bid",
                    "open_ask",
                    "high_bid",
                    "high_ask",
                    "low_bid",
                    "low_ask",
                    "close_bid",
                    "close_ask",
                )
            }
            if any(not math.isfinite(item) or item <= 0 for item in values.values()):
                raise ValidationRunnerError(f"row {row_number}: non-finite or non-positive price")
            bars.append(
                HistoricalBar(
                    timestamp=timestamp.astimezone(UTC),
                    volume=float(row.get("last_traded_volume") or 0.0),
                    **values,
                )
            )
    if not bars:
        raise ValidationRunnerError(f"{source.name} contains no bars")
    for left, right in zip(bars, bars[1:], strict=False):
        if left.timestamp >= right.timestamp:
            raise ValidationRunnerError("historical bars are not strictly increasing")
    return tuple(bars)


def bars_market_data(
    bars: tuple[HistoricalBar, ...],
    *,
    epic: str,
    instrument: str,
    resolution: StrategyBarResolution,
    retrieval_time: datetime,
) -> StrategyMarketData:
    """Typed strategy-domain view of a bounded historical bar window."""

    return StrategyMarketData(
        epic=epic,
        instrument_name=instrument,
        timestamps=tuple(item.timestamp for item in bars),
        open_midpoints=tuple(item.open_mid for item in bars),
        high_midpoints=tuple(item.high_mid for item in bars),
        low_midpoints=tuple(item.low_mid for item in bars),
        close_midpoints=tuple(item.close_mid for item in bars),
        bids=tuple(item.close_bid for item in bars),
        asks=tuple(item.close_ask for item in bars),
        spreads=tuple(item.close_ask - item.close_bid for item in bars),
        spread_bps=tuple(
            (item.close_ask - item.close_bid) / item.close_mid * 10_000.0 for item in bars
        ),
        volume=tuple(item.volume for item in bars),
        market_status="TRADEABLE",
        data_retrieval_time=retrieval_time,
        bar_resolution=resolution,
        source_bar_count=len(bars),
        excluded_invalid_bars=0,
    )


class IncrementalKalman:
    """Continuous local-linear-trend filter.

    Mirrors the exact per-step recursion of
    :func:`trading_desk.strategy.kalman.fit_local_linear_trend` (prediction,
    Joseph-form update, symmetrization) while carrying filter state across
    bars, so per-bar context construction is O(1) instead of O(window).
    Equivalence with the reference implementation is asserted by unit test.
    """

    def __init__(self, config: StrategyConfiguration) -> None:
        self._config = config
        self._count = 0
        self._level = 0.0
        self._slope = 0.0
        self._p00 = config.kalman_initial_level_variance
        self._p01 = 0.0
        self._p11 = config.kalman_initial_slope_variance
        self._last_observation = 0.0
        self._failed = False

    def update(self, observation: float) -> None:
        if self._failed or not math.isfinite(observation):
            self._failed = True
            return
        config = self._config
        if self._count == 0:
            self._level = observation
            self._slope = 0.0
        predicted_level = self._level + self._slope
        predicted_slope = self._slope
        p00 = self._p00 + 2.0 * self._p01 + self._p11 + config.kalman_process_level_noise
        p01 = self._p01 + self._p11
        p11 = self._p11 + config.kalman_process_slope_noise
        innovation = observation - predicted_level
        innovation_variance = p00 + config.kalman_observation_noise
        if not math.isfinite(innovation_variance) or innovation_variance <= 0:
            self._failed = True
            return
        gain0 = p00 / innovation_variance
        gain1 = p01 / innovation_variance
        self._level = predicted_level + gain0 * innovation
        self._slope = predicted_slope + gain1 * innovation
        residual = 1.0 - gain0
        noise = config.kalman_observation_noise
        n00 = residual * residual * p00
        n01 = residual * (p01 - gain1 * p00)
        n11 = gain1 * gain1 * p00 - 2.0 * gain1 * p01 + p11
        self._p00 = n00 + gain0 * gain0 * noise
        self._p01 = n01 + gain0 * gain1 * noise
        self._p11 = n11 + gain1 * gain1 * noise
        self._count += 1
        self._last_observation = observation
        if not all(
            math.isfinite(item)
            for item in (self._level, self._slope, self._p00, self._p01, self._p11)
        ):
            self._failed = True

    def result(self) -> KalmanTrendResult:
        config = self._config
        if self._failed or self._count < config.kalman_minimum_observations:
            return KalmanTrendResult(
                ready=False,
                reason="insufficient observations for Kalman trend",
                observations_used=self._count,
            )
        level_scale = max(abs(self._level), 1e-12)
        slope_uncertainty = math.sqrt(max(self._p11, 0.0))
        level_uncertainty = math.sqrt(max(self._p00, 0.0))
        deviation_variance = level_uncertainty**2 + config.kalman_observation_noise
        return KalmanTrendResult(
            ready=True,
            current_filtered_level=self._level,
            current_slope=self._slope,
            current_slope_uncertainty=slope_uncertainty,
            current_normalized_slope=self._slope / level_scale,
            current_normalized_slope_uncertainty=slope_uncertainty / level_scale,
            normalized_price_deviation=(self._last_observation - self._level)
            / math.sqrt(deviation_variance),
            observations_used=self._count,
            steps=(),
        )


@dataclass
class CausalContextBuilder:
    """Builds cutoff-safe market context for one instrument and timeframe.

    HMM parameters are refitted every ``hmm_refit_interval`` completed bars on
    the trailing ``window_size`` bars using the real
    :func:`~trading_desk.strategy.regime.fit_regime_model`. Between refits the
    latest strictly-older fit is reused; parameters are therefore stale by a
    bounded, documented interval but never influenced by future observations.

    ``evaluator_window`` bounds the market-data slice handed to strategy
    evaluators; it must satisfy every governed strategy's ``minimum_history``.
    """

    epic: str
    instrument: str
    resolution: StrategyBarResolution
    strategy_configuration: StrategyConfiguration
    window_size: int = 400
    hmm_refit_interval: int = 120
    evaluator_window: int = 80
    engine: MarketContextEngine = field(default_factory=MarketContextEngine)

    def __post_init__(self) -> None:
        self._bars: list[HistoricalBar] = []
        self._kalman = IncrementalKalman(self.strategy_configuration)
        self._regime: HMMRegimeResult | None = None
        self._bars_since_refit = 0

    @property
    def timeframe(self) -> ContextTimeframe:
        return RESOLUTION_TIMEFRAMES[self.resolution]

    def observe(self, bar: HistoricalBar) -> None:
        self._bars.append(bar)
        if len(self._bars) > self.window_size:
            del self._bars[0]
        self._kalman.update(bar.close_mid)
        self._bars_since_refit += 1
        if self._bars_since_refit >= self.hmm_refit_interval and len(self._bars) >= 150:
            self._refit_regime()
            self._bars_since_refit = 0

    def _refit_regime(self) -> None:
        closes = tuple(item.close_mid for item in self._bars)
        try:
            window_kalman = fit_local_linear_trend(closes, self.strategy_configuration)
            self._regime = fit_regime_model(
                closes,
                window_kalman if window_kalman.ready else None,
                self.strategy_configuration,
            )
        except (ValueError, ArithmeticError):
            self._regime = None

    def context_market_data(self, evaluation_timestamp: datetime) -> StrategyMarketData:
        return bars_market_data(
            tuple(self._bars),
            epic=self.epic,
            instrument=self.instrument,
            resolution=self.resolution,
            retrieval_time=evaluation_timestamp,
        )

    def evaluator_market_data(self, evaluation_timestamp: datetime) -> StrategyMarketData:
        return bars_market_data(
            tuple(self._bars[-self.evaluator_window :]),
            epic=self.epic,
            instrument=self.instrument,
            resolution=self.resolution,
            retrieval_time=evaluation_timestamp,
        )

    def session_open(self, evaluation_timestamp: datetime) -> bool:
        """Cheap pre-check: a CLOSED session can never produce a candidate.

        Skipping full context classification on closed-session bars is
        behavior-preserving: entry evaluation would reject with
        ``SESSION_INELIGIBLE`` and in-position invalidation treats an absent
        snapshot as UNKNOWN, which holds — exactly what a closed session does.
        """

        session = classify_session(evaluation_timestamp, self.engine.config)
        return session.session is not SessionState.CLOSED

    def snapshot(self, evaluation_timestamp: datetime) -> MarketContextSnapshot | None:
        if len(self._bars) < self.window_size // 2 or self._regime is None:
            return None
        try:
            return self.engine.classify(
                self.context_market_data(evaluation_timestamp),
                self._kalman.result(),
                self._regime,
                evaluation_timestamp=evaluation_timestamp,
                timeframe=self.timeframe,
            )
        except (ValueError, ArithmeticError):
            return None


@dataclass(frozen=True)
class SimulationCosts:
    """Cost policy applied identically to every simulated strategy."""

    slippage_bps: Decimal = Decimal("0.5")
    commission_per_fill: Decimal = Decimal("0")
    funding_fraction_per_day: Decimal = Decimal("0.00008")


@dataclass(frozen=True)
class SimulatedStrategy:
    """One evaluator plus the simulation limits its configuration defines."""

    evaluator: StrategyEvaluator
    maximum_holding_bars: int
    configuration_fingerprint: str


@dataclass
class _OpenPosition:
    result: StrategyEvaluationResult
    entry_context: PositionEntryContext
    entry_at: datetime
    entry_mid: Decimal
    entry_half_spread: Decimal
    entry_slippage: Decimal
    stop: Decimal
    target: Decimal | None
    maximum_holding_bars: int
    regime: str
    bars_held: int = 0
    exit_pending_reason: str | None = None


@dataclass(frozen=True)
class SimulationResult:
    strategy_id: str
    trades: tuple[ValidationTrade, ...]
    candidate_count: int
    rejection_count: int
    evaluation_count: int
    forced_exit_count: int
    session_closed_skips: int
    rejection_reasons: tuple[tuple[str, int], ...]


def _decimal(value: float) -> Decimal:
    return Decimal(str(value)).quantize(_PRICE_QUANTUM)


class _StrategyState:
    """Single-position long-only state machine for one strategy."""

    def __init__(
        self,
        strategy: SimulatedStrategy,
        *,
        costs: SimulationCosts,
        timeframe_seconds: int,
        trade_prefix: str,
    ) -> None:
        self.strategy = strategy
        self.costs = costs
        self.timeframe_seconds = timeframe_seconds
        self.trade_prefix = trade_prefix
        self.trades: list[ValidationTrade] = []
        self.position: _OpenPosition | None = None
        self.pending: tuple[StrategyEvaluationResult, str] | None = None
        self.candidate_count = 0
        self.rejection_count = 0
        self.evaluation_count = 0
        self.forced_exit_count = 0
        self.session_closed_skips = 0
        self.rejection_reason_counts: Counter[str] = Counter()

    def _slippage(self, reference_mid: Decimal) -> Decimal:
        return (reference_mid * self.costs.slippage_bps / Decimal("10000")).quantize(_PRICE_QUANTUM)

    def _bar_end(self, bar: HistoricalBar) -> datetime:
        return bar.timestamp + timedelta(seconds=self.timeframe_seconds)

    def _close(self, exit_bid_fill: Decimal, exit_mid: Decimal, exit_at: datetime) -> None:
        """Record the closed trade with all values as fractions of entry notional.

        Normalizing by the entry midpoint makes trades from differently priced
        instruments (for example JPY-quoted versus USD-quoted pairs) directly
        comparable, so cross-instrument aggregation, expectancy, and drawdown
        gates operate on a single scale: return per one unit of notional.
        """

        position = self.position
        assert position is not None
        exit_slippage = self._slippage(exit_mid)
        held_days = Decimal(str(max((exit_at - position.entry_at).total_seconds(), 0.0) / 86400.0))
        funding = (self.costs.funding_fraction_per_day * held_days).quantize(_PRICE_QUANTUM)
        notional = position.entry_mid
        self.trades.append(
            ValidationTrade(
                trade_id=f"{self.trade_prefix}-{len(self.trades) + 1:05d}",
                strategy_id=position.result.strategy_id,
                instrument_id=position.result.instrument_id,
                timeframe=position.result.timeframe.value,
                regime=position.regime,
                entry_at=position.entry_at,
                exit_at=exit_at,
                gross_pnl=((exit_mid - position.entry_mid) / notional).quantize(_PRICE_QUANTUM),
                spread_cost=(
                    (position.entry_half_spread + max(exit_mid - exit_bid_fill, Decimal("0")))
                    / notional
                ).quantize(_PRICE_QUANTUM),
                slippage_cost=((position.entry_slippage + exit_slippage) / notional).quantize(
                    _PRICE_QUANTUM
                ),
                commission_cost=self.costs.commission_per_fill * 2,
                funding_cost=funding,
                turnover=((position.entry_mid + exit_mid) / notional).quantize(_PRICE_QUANTUM),
            )
        )
        self.position = None

    def fill_pending_entry(self, bar: HistoricalBar) -> bool:
        if self.position is not None or self.pending is None:
            return False
        result, regime = self.pending
        self.pending = None
        stop = result.proposed_stop
        if stop is None:
            return False
        entry_ask = _decimal(bar.open_ask)
        entry_mid = _decimal(bar.open_mid)
        self.position = _OpenPosition(
            result=result,
            entry_context=PositionEntryContext(
                strategy_id=result.strategy_id,
                strategy_version=result.strategy_version,
                maximum_holding_period=timedelta(
                    seconds=self.timeframe_seconds * self.strategy.maximum_holding_bars
                ),
            ),
            entry_at=bar.timestamp,
            entry_mid=entry_mid,
            entry_half_spread=max(entry_ask - entry_mid, Decimal("0")),
            entry_slippage=self._slippage(entry_mid),
            stop=stop,
            target=result.proposed_target,
            maximum_holding_bars=self.strategy.maximum_holding_bars,
            regime=regime,
        )
        return True

    def manage_exits(self, bar: HistoricalBar, *, entered_this_bar: bool) -> None:
        position = self.position
        if position is None:
            return
        if not entered_this_bar:
            position.bars_held += 1
        half_spread = max((_decimal(bar.open_ask) - _decimal(bar.open_bid)) / 2, Decimal("0"))
        if position.exit_pending_reason is not None and not entered_this_bar:
            open_bid = _decimal(bar.open_bid)
            self._close(open_bid, open_bid + half_spread, self._bar_end(bar))
            return
        if _decimal(bar.low_bid) <= position.stop:
            fill = min(position.stop, _decimal(bar.open_bid))
            self._close(fill, fill + half_spread, self._bar_end(bar))
            return
        if position.target is not None and _decimal(bar.high_bid) >= position.target:
            self._close(position.target, position.target + half_spread, self._bar_end(bar))

    def evaluate_position_state(
        self, bar: HistoricalBar, snapshot: MarketContextSnapshot | None
    ) -> None:
        position = self.position
        if position is None or position.exit_pending_reason is not None:
            return
        invalidation = evaluate_invalidation(
            position.entry_context, snapshot, bar.timestamp - position.entry_at
        )
        if invalidation.decision is InvalidationDecision.EXIT:
            position.exit_pending_reason = ",".join(invalidation.reasons) or "INVALIDATED"
        elif position.bars_held >= position.maximum_holding_bars:
            position.exit_pending_reason = "MAXIMUM_HOLDING_PERIOD"

    def wants_entry_evaluation(self) -> bool:
        return self.position is None and self.pending is None

    def evaluate_entry(
        self,
        snapshot: MarketContextSnapshot,
        market_data: StrategyMarketData,
        builder: CausalContextBuilder,
        bar: HistoricalBar,
        evaluation_at: datetime,
    ) -> None:
        self.evaluation_count += 1
        context = evaluation_context(
            evaluation_timestamp=evaluation_at,
            instrument_id=builder.instrument,
            epic=builder.epic,
            timeframe=builder.timeframe,
            completed_bar_timestamp=bar.timestamp,
            market_data=market_data,
            higher_timeframe_data=None,
            market_context=snapshot,
            existing_position=False,
            strategy_configuration_fingerprint=self.strategy.configuration_fingerprint,
        )
        result = self.strategy.evaluator.evaluate(context=context)
        if result.decision is StrategyDecision.CANDIDATE and result.proposed_stop is not None:
            self.candidate_count += 1
            self.pending = (result, snapshot.hmm_regime)
        else:
            self.rejection_count += 1
            self.rejection_reason_counts.update(
                result.rejection_reasons or (result.decision.value,)
            )

    def force_exit(self, bar: HistoricalBar) -> None:
        if self.position is None:
            return
        exit_mid = _decimal(bar.close_mid)
        self._close(_decimal(bar.close_bid), exit_mid, self._bar_end(bar))
        self.forced_exit_count += 1

    def result(self) -> SimulationResult:
        return SimulationResult(
            strategy_id=self.strategy.evaluator.strategy_id,
            trades=tuple(self.trades),
            candidate_count=self.candidate_count,
            rejection_count=self.rejection_count,
            evaluation_count=self.evaluation_count,
            forced_exit_count=self.forced_exit_count,
            session_closed_skips=self.session_closed_skips,
            rejection_reasons=tuple(sorted(self.rejection_reason_counts.items())),
        )


def simulate_strategies(
    strategies: tuple[SimulatedStrategy, ...],
    bars: tuple[HistoricalBar, ...],
    *,
    builder: CausalContextBuilder,
    costs: SimulationCosts,
    evaluation_start: datetime,
    evaluation_end: datetime,
    trade_prefix: str,
) -> tuple[SimulationResult, ...]:
    """Replay ``bars`` chronologically through the given strategy evaluators.

    All strategies share one causal context per bar: the market context is
    classified once and handed to every strategy, which mirrors how the
    operational engine serves one context snapshot to the router. Bars before
    ``evaluation_start`` build warmup context only and cannot open positions.
    Bars after ``evaluation_end`` are never read.
    """

    if evaluation_end <= evaluation_start:
        raise ValidationRunnerError("evaluation window is empty")
    timeframe_seconds = builder.timeframe.seconds
    states = tuple(
        _StrategyState(
            strategy,
            costs=costs,
            timeframe_seconds=timeframe_seconds,
            trade_prefix=f"{trade_prefix}-{strategy.evaluator.strategy_id}",
        )
        for strategy in strategies
    )
    last_processed: HistoricalBar | None = None
    for bar in bars:
        if bar.timestamp > evaluation_end:
            break
        last_processed = bar
        for state in states:
            entered = state.fill_pending_entry(bar)
            state.manage_exits(bar, entered_this_bar=entered)
        builder.observe(bar)
        evaluation_at = bar.timestamp + timedelta(seconds=timeframe_seconds)
        holding = any(
            state.position is not None and state.position.exit_pending_reason is None
            for state in states
        )
        evaluating = bar.timestamp >= evaluation_start and any(
            state.wants_entry_evaluation() for state in states
        )
        if not holding and not evaluating:
            continue
        session_open = builder.session_open(evaluation_at)
        snapshot = builder.snapshot(evaluation_at) if session_open else None
        for state in states:
            state.evaluate_position_state(bar, snapshot)
        if not evaluating:
            continue
        if not session_open:
            for state in states:
                if state.wants_entry_evaluation():
                    state.session_closed_skips += 1
            continue
        if snapshot is None:
            continue
        market_data = builder.evaluator_market_data(evaluation_at)
        for state in states:
            if state.wants_entry_evaluation() and bar.timestamp >= evaluation_start:
                state.evaluate_entry(snapshot, market_data, builder, bar, evaluation_at)
    if last_processed is not None:
        for state in states:
            state.force_exit(last_processed)
    return tuple(state.result() for state in states)


__all__ = [
    "CausalContextBuilder",
    "HistoricalBar",
    "IncrementalKalman",
    "RESOLUTION_TIMEFRAMES",
    "SimulatedStrategy",
    "SimulationCosts",
    "SimulationResult",
    "ValidationRunnerError",
    "load_bars",
    "simulate_strategies",
]
