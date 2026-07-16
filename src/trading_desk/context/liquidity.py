"""Observable-input liquidity classification without depth inference."""

from decimal import Decimal

from trading_desk.context.config import MarketContextConfiguration
from trading_desk.context.models import LiquidityState, SessionState


def classify_liquidity(
    *,
    session: SessionState,
    spread_bps: Decimal | None,
    spread_percentile: Decimal | None,
    market_status: str,
    missing_quote_rate: Decimal = Decimal("0"),
    config: MarketContextConfiguration,
) -> LiquidityState:
    if spread_bps is None or spread_percentile is None:
        return LiquidityState.UNKNOWN
    if market_status.upper() != "TRADEABLE" or session in {
        SessionState.CLOSED,
        SessionState.ROLLOVER,
        SessionState.HOLIDAY_OR_THIN,
        SessionState.UNKNOWN,
    }:
        return LiquidityState.LOW
    if spread_bps >= config.abnormal_spread_bps or missing_quote_rate >= Decimal("0.20"):
        return LiquidityState.ABNORMAL
    if (
        spread_bps > config.maximum_spread_bps
        or spread_percentile >= config.low_liquidity_spread_percentile
        or missing_quote_rate >= Decimal("0.05")
    ):
        return LiquidityState.LOW
    if session is SessionState.LONDON_NEW_YORK_OVERLAP and spread_percentile <= Decimal("50"):
        return LiquidityState.HIGH
    return LiquidityState.NORMAL
