"""Cutoff-safe deterministic market-context assembly."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from trading_desk.context.config import MarketContextConfiguration
from trading_desk.context.events import classify_event_context, event_visible_at
from trading_desk.context.fingerprints import fingerprint
from trading_desk.context.liquidity import classify_liquidity
from trading_desk.context.models import (
    BreakoutState,
    ContextQuality,
    ContextReasonCode,
    ContextTimeframe,
    EconomicEvent,
    LiquidityState,
    MarketContextSnapshot,
    NewsItem,
    NewsState,
    RangeState,
    ScheduledEventState,
    SessionState,
    TrendState,
    VolatilityState,
)
from trading_desk.context.news import classify_news
from trading_desk.context.sessions import classify_session
from trading_desk.context.volatility import classify_volatility, percentile_rank
from trading_desk.strategy.models import (
    HMMRegimeResult,
    KalmanTrendResult,
    Regime,
    StrategyMarketData,
)


class MarketContextEngine:
    """Build immutable snapshots using observations no later than the cutoff."""

    def __init__(self, config: MarketContextConfiguration | None = None) -> None:
        self.config = config or MarketContextConfiguration()

    def classify(
        self,
        data: StrategyMarketData,
        kalman: KalmanTrendResult,
        regime: HMMRegimeResult,
        *,
        evaluation_timestamp: datetime,
        timeframe: ContextTimeframe,
        events: tuple[EconomicEvent, ...] = (),
        news: tuple[NewsItem, ...] = (),
        holiday: bool = False,
    ) -> MarketContextSnapshot:
        evaluation = _utc(evaluation_timestamp)
        if not data.timestamps:
            raise ValueError("market context requires at least one completed bar")
        cutoff = _utc(data.timestamps[-1])
        visible_events = tuple(event_visible_at(item, evaluation) for item in events)
        session = classify_session(evaluation, self.config, holiday=holiday)
        reasons: list[ContextReasonCode] = []
        age = max(0, int((evaluation - cutoff).total_seconds()))
        if cutoff > evaluation:
            reasons.append(ContextReasonCode.FUTURE_DATA)
        if age > int(timeframe.seconds * self.config.maximum_data_age_multiple):
            reasons.append(ContextReasonCode.STALE_DATA)
        if len(data.timestamps) < self.config.minimum_history:
            reasons.append(ContextReasonCode.INSUFFICIENT_HISTORY)
        if session.session is SessionState.CLOSED:
            reasons.append(ContextReasonCode.MARKET_CLOSED)
        if session.session is SessionState.UNKNOWN:
            reasons.append(ContextReasonCode.UNKNOWN_SESSION)

        spread_bps = Decimal(str(data.spread_bps[-1]))
        spread_percentile = percentile_rank(data.spread_bps, data.spread_bps[-1])
        liquidity = classify_liquidity(
            session=session.session,
            spread_bps=spread_bps,
            spread_percentile=spread_percentile,
            market_status=data.market_status,
            config=self.config,
        )
        if liquidity is LiquidityState.LOW:
            reasons.append(ContextReasonCode.LOW_LIQUIDITY)
        elif liquidity is LiquidityState.ABNORMAL:
            reasons.append(ContextReasonCode.ABNORMAL_SPREAD)

        volatility, realized, atr, volatility_percentile, compression = classify_volatility(
            data.high_midpoints, data.low_midpoints, data.close_midpoints, self.config
        )
        if volatility is VolatilityState.EXTREME:
            reasons.append(ContextReasonCode.EXTREME_VOLATILITY)
        trend = _trend_state(kalman, regime, volatility, self.config)
        if trend is TrendState.TRANSITION:
            reasons.append(ContextReasonCode.REGIME_TRANSITION)
        if trend is TrendState.UNKNOWN:
            reasons.append(ContextReasonCode.MODEL_NOT_READY)

        event = classify_event_context(visible_events, evaluation, timeframe.seconds, self.config)
        if event.state is ScheduledEventState.PRE_EVENT:
            reasons.append(ContextReasonCode.PRE_HIGH_IMPACT_EVENT)
        if event.state is ScheduledEventState.INITIAL_REACTION:
            reasons.append(ContextReasonCode.INITIAL_NEWS_REACTION)
        news_context = classify_news(news, evaluation, self.config)
        news_state = news_context.state
        if news_state is NewsState.UNSCHEDULED_CAUTION:
            reasons.append(ContextReasonCode.UNSCHEDULED_NEWS)

        range_state = _range_state(trend, volatility)
        breakout = _breakout_state(data, volatility)
        blocking = {
            ContextReasonCode.FUTURE_DATA,
            ContextReasonCode.STALE_DATA,
            ContextReasonCode.INSUFFICIENT_HISTORY,
            ContextReasonCode.MARKET_CLOSED,
            ContextReasonCode.UNKNOWN_SESSION,
            ContextReasonCode.ABNORMAL_SPREAD,
            ContextReasonCode.EXTREME_VOLATILITY,
            ContextReasonCode.PRE_HIGH_IMPACT_EVENT,
            ContextReasonCode.INITIAL_NEWS_REACTION,
            ContextReasonCode.UNSCHEDULED_NEWS,
            ContextReasonCode.MODEL_NOT_READY,
        }
        quality = (
            ContextQuality.INVALID
            if any(reason in blocking for reason in reasons)
            else ContextQuality.DEGRADED
            if reasons
            else ContextQuality.VALID
        )
        probabilities = tuple(
            (item.regime.value, Decimal(str(item.probability))) for item in regime.probabilities
        )
        fields: dict[str, object] = {
            "instrument": data.instrument_name,
            "epic": data.epic,
            "evaluation_timestamp": evaluation,
            "data_cutoff_timestamp": cutoff,
            "timeframe": timeframe,
            "session": session.session,
            "session_overlap": session.session_overlap,
            "day_of_week": evaluation.weekday(),
            "minutes_from_session_open": session.minutes_from_session_open,
            "minutes_to_session_close": session.minutes_to_session_close,
            "liquidity_state": liquidity,
            "spread_bps": spread_bps,
            "spread_percentile": spread_percentile,
            "volatility_state": volatility,
            "realized_volatility": realized,
            "atr": atr,
            "volatility_percentile": volatility_percentile,
            "trend_state": trend,
            "trend_strength": Decimal(str(abs(kalman.current_normalized_slope or 0))),
            "kalman_slope": _decimal(kalman.current_slope),
            "kalman_uncertainty": _decimal(kalman.current_slope_uncertainty),
            "hmm_regime": regime.current_regime.value,
            "hmm_probabilities": probabilities,
            "range_state": range_state,
            "compression_state": compression,
            "breakout_state": breakout,
            "scheduled_event_state": event.state,
            "minutes_to_next_high_impact_event": event.minutes_to_next_high_impact_event,
            "minutes_since_previous_high_impact_event": (
                event.minutes_since_previous_high_impact_event
            ),
            "event_category": event.category,
            "news_state": news_state,
            "market_status": data.market_status,
            "data_freshness_seconds": age,
            "context_quality": quality,
            "reason_codes": tuple(dict.fromkeys(reasons)),
            "configuration_fingerprint": self.config.configuration_fingerprint,
        }
        identity = fingerprint(fields)
        return MarketContextSnapshot.model_validate(
            {**fields, "context_id": identity, "context_fingerprint": identity}
        )


def _trend_state(
    kalman: KalmanTrendResult,
    regime: HMMRegimeResult,
    volatility: VolatilityState,
    config: MarketContextConfiguration,
) -> TrendState:
    if not kalman.ready or not regime.ready or kalman.current_normalized_slope is None:
        return TrendState.UNKNOWN
    if volatility is VolatilityState.EXTREME or regime.current_regime is Regime.BEAR_HIGH_VOL:
        return TrendState.HIGH_VOLATILITY_DISORDER
    slope = Decimal(str(kalman.current_normalized_slope))
    if regime.current_regime is Regime.TRANSITIONAL:
        return TrendState.TRANSITION
    if abs(slope) <= config.range_slope_threshold:
        return TrendState.RANGE
    if slope >= config.strong_trend_slope_threshold:
        return TrendState.STRONG_BULL_TREND
    if slope >= config.trend_slope_threshold:
        return TrendState.WEAK_BULL_TREND
    return TrendState.TRANSITION


def _range_state(trend: TrendState, volatility: VolatilityState) -> RangeState:
    if trend is TrendState.UNKNOWN:
        return RangeState.UNKNOWN
    if trend is TrendState.RANGE and volatility not in {
        VolatilityState.EXTREME,
        VolatilityState.HIGH,
    }:
        return RangeState.ESTABLISHED
    return RangeState.NOT_RANGE


def _breakout_state(data: StrategyMarketData, volatility: VolatilityState) -> BreakoutState:
    if len(data.close_midpoints) < 21:
        return BreakoutState.UNKNOWN
    prior_high = max(data.high_midpoints[-21:-1])
    prior_low = min(data.low_midpoints[-21:-1])
    close = data.close_midpoints[-1]
    if volatility is VolatilityState.EXPANSION and close > prior_high:
        return BreakoutState.CONFIRMED_UP
    if volatility is VolatilityState.EXPANSION and close < prior_low:
        return BreakoutState.CONFIRMED_DOWN
    return BreakoutState.NONE


def _decimal(value: float | None) -> Decimal | None:
    return Decimal(str(value)) if value is not None else None


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("context timestamps must be timezone-aware")
    return value.astimezone(UTC)
