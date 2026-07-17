from __future__ import annotations

from datetime import UTC, datetime, timedelta

from trading_desk.context.classifier import MarketContextEngine
from trading_desk.context.config import MarketContextConfiguration
from trading_desk.context.models import (
    ContextQuality,
    ContextTimeframe,
    LiquidityState,
    MarketContextSnapshot,
    VolatilityState,
)
from trading_desk.strategy.models import (
    HMMRegimeResult,
    KalmanTrendResult,
    Regime,
    RegimeProbability,
    StrategyMarketData,
)


def market_data(
    *,
    end: datetime = datetime(2026, 7, 15, 14, tzinfo=UTC),
    count: int = 40,
    spread_bps: float = 1.0,
    slope: float = 0.01,
) -> StrategyMarketData:
    closes = tuple(100 + index * slope for index in range(count))
    timestamps = tuple(end - timedelta(hours=count - 1 - index) for index in range(count))
    return StrategyMarketData(
        epic="CS.D.TEST.CFD.IP",
        instrument_name="Test market",
        timestamps=timestamps,
        open_midpoints=closes,
        high_midpoints=tuple(value + 0.1 for value in closes),
        low_midpoints=tuple(value - 0.1 for value in closes),
        close_midpoints=closes,
        bids=tuple(value - 0.005 for value in closes),
        asks=tuple(value + 0.005 for value in closes),
        spreads=(0.01,) * count,
        spread_bps=(spread_bps,) * count,
        volume=(1000.0,) * count,
        market_status="TRADEABLE",
        data_retrieval_time=end,
        source_bar_count=count,
    )


def kalman(slope: float = 0.001, *, ready: bool = True) -> KalmanTrendResult:
    return KalmanTrendResult(
        ready=ready,
        current_filtered_level=100,
        current_slope=slope,
        current_slope_uncertainty=0.01,
        current_normalized_slope=slope,
        current_normalized_slope_uncertainty=0.001,
        normalized_price_deviation=0,
        observations_used=40,
    )


def regime(value: Regime = Regime.BULL_LOW_VOL, *, ready: bool = True) -> HMMRegimeResult:
    probabilities = tuple(
        RegimeProbability(regime=item, probability=0.9 if item is value else 0.05)
        for item in (Regime.BULL_LOW_VOL, Regime.TRANSITIONAL, Regime.BEAR_HIGH_VOL)
    )
    return HMMRegimeResult(
        ready=ready,
        current_regime=value,
        probabilities=probabilities,
        selected_regime_probability=0.9,
        uncertainty=0.2,
        converged=ready,
        observations_used=40,
    )


def snapshot(**updates: object) -> MarketContextSnapshot:
    data = market_data()
    config = MarketContextConfiguration(minimum_history=30, volatility_window=5)
    result = MarketContextEngine(config).classify(
        data,
        kalman(),
        regime(),
        evaluation_timestamp=data.timestamps[-1],
        timeframe=ContextTimeframe.HOUR,
    )
    fields = result.model_dump(mode="python", exclude={"context_id", "context_fingerprint"})
    fields["volatility_state"] = VolatilityState.NORMAL
    fields["liquidity_state"] = LiquidityState.NORMAL
    fields["context_quality"] = ContextQuality.VALID
    fields["reason_codes"] = ()
    fields.update(updates)
    from trading_desk.context.fingerprints import fingerprint

    identity = fingerprint(fields)
    return MarketContextSnapshot.model_validate(
        {**fields, "context_id": identity, "context_fingerprint": identity}
    )
