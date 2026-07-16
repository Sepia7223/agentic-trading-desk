from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from risk_helpers import EPIC, NOW, account, candidate, market
from trading_desk.portfolio import MarketQuote, PaperPortfolio, PaperPortfolioConfiguration
from trading_desk.risk import RiskEngine
from trading_desk.risk.models import RiskDecision, TradeCandidate


def configured_portfolio(**updates: object) -> PaperPortfolio:
    values: dict[str, object] = {
        "initial_cash": Decimal("100000"),
        "fixed_commission_per_fill": Decimal("2"),
        "slippage_bps": Decimal("1"),
        "funding_bps_per_utc_day": Decimal("1"),
    }
    values.update(updates)
    portfolio = PaperPortfolio(PaperPortfolioConfiguration.model_validate(values))
    portfolio.create("paper-1", NOW - timedelta(minutes=1))
    return portfolio


def approval(
    portfolio: PaperPortfolio,
    *,
    candidate_updates: dict[str, object] | None = None,
    market_updates: dict[str, object] | None = None,
) -> tuple[RiskDecision, TradeCandidate, MarketQuote]:
    trade_candidate = candidate(**(candidate_updates or {}))
    account_state = account(
        snapshot_id=portfolio.state.snapshot_id,
        timestamp=NOW - timedelta(seconds=10),
    )
    market_state = market(**(market_updates or {}))
    decision = RiskEngine().evaluate(trade_candidate, account_state, market_state, NOW)
    quote = MarketQuote(
        snapshot_id=market_state.snapshot_id,
        timestamp=NOW,
        epic=EPIC,
        bid=market_state.bid,
        ask=market_state.ask,
        market_status=market_state.market_status.value,
        value_per_price_unit=market_state.value_per_price_unit or Decimal("1"),
    )
    return decision, trade_candidate, quote


def later(minutes: int = 1) -> datetime:
    return datetime(2026, 7, 15, 12, minutes, tzinfo=UTC)
