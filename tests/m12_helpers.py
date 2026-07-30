from __future__ import annotations

from datetime import timedelta

from context_helpers import market_data, snapshot
from trading_desk.context.fingerprints import fingerprint
from trading_desk.context.models import ContextTimeframe, MarketContextSnapshot
from trading_desk.strategy.contracts import StrategyEvaluationContext, evaluation_context
from trading_desk.strategy.models import StrategyMarketData


def portfolio_data(kind: str) -> StrategyMarketData:
    data = market_data(count=80, slope=0.02)
    closes = list(data.close_midpoints)
    if kind == "pullback":
        closes[-8:] = [101.55, 101.48, 101.40, 101.32, 101.25, 101.30, 101.38, 101.45]
    elif kind == "breakout":
        closes[-22:] = [101.30 + (index % 2) * 0.04 for index in range(21)] + [101.48]
    elif kind == "range":
        closes = [100 + (index % 5 - 2) * 0.05 for index in range(80)]
        closes[-1] = 99.775
    opens = list(closes)
    opens[-1] = closes[-1] - 0.08
    highs = [value + 0.10 for value in closes]
    lows = [value - 0.10 for value in closes]
    if kind == "pullback":
        highs[-8:] = [101.65, 101.58, 101.50, 101.42, 101.35, 101.40, 101.48, 101.55]
        lows[-8:] = [101.45, 101.38, 101.30, 101.22, 101.15, 101.20, 101.28, 101.35]
    elif kind == "breakout":
        highs[-1], lows[-1] = 101.60, 101.20
    elif kind == "range":
        highs[-31:-1] = [100.25] * 30
        lows[-31:-1] = [99.75] * 30
        opens[-1] = 99.73
        highs[-1], lows[-1] = 99.90, 99.725
    return data.model_copy(
        update={
            "open_midpoints": tuple(opens),
            "high_midpoints": tuple(highs),
            "low_midpoints": tuple(lows),
            "close_midpoints": tuple(closes),
            "bids": tuple(value - 0.005 for value in closes),
            "asks": tuple(value + 0.005 for value in closes),
        }
    )


def updated_snapshot(**updates: object) -> MarketContextSnapshot:
    value = snapshot()
    fields = value.model_dump(mode="python", exclude={"context_id", "context_fingerprint"})
    fields.update(updates)
    identity = fingerprint(fields)
    return MarketContextSnapshot.model_validate(
        {**fields, "context_id": identity, "context_fingerprint": identity}
    )


def evaluation(
    data: StrategyMarketData, context: MarketContextSnapshot
) -> StrategyEvaluationContext:
    return evaluation_context(
        evaluation_timestamp=data.timestamps[-1] + timedelta(hours=1),
        instrument_id="Test market",
        epic=data.epic,
        timeframe=ContextTimeframe.HOUR,
        completed_bar_timestamp=data.timestamps[-1],
        market_data=data,
        higher_timeframe_data=None,
        market_context=updated_snapshot(
            **context.model_dump(
                mode="python",
                exclude={
                    "context_id",
                    "context_fingerprint",
                    "evaluation_timestamp",
                    "data_cutoff_timestamp",
                },
            ),
            evaluation_timestamp=data.timestamps[-1] + timedelta(hours=1),
            data_cutoff_timestamp=data.timestamps[-1],
        ),
        existing_position=False,
        strategy_configuration_fingerprint="a" * 64,
    )
