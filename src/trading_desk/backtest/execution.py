"""Conservative bid/ask simulation fills with itemized costs."""

from __future__ import annotations

from trading_desk.backtest.configuration import BacktestConfiguration
from trading_desk.backtest.models import (
    BacktestBar,
    BacktestTrade,
    ExitReason,
    FillPriceMode,
    FillSide,
    IntrabarAmbiguityPolicy,
    SimulatedFill,
    SimulatedOrder,
)
from trading_desk.backtest.validation import days_held, permitted_execution_deadline
from trading_desk.strategy.models import Regime


def fill_pending_order(
    order: SimulatedOrder,
    bars: tuple[BacktestBar, ...],
    configuration: BacktestConfiguration,
) -> tuple[SimulatedFill | None, str | None]:
    if order.earliest_fill_index <= order.signal_index:
        raise ValueError("same-bar execution is prohibited")
    deadline = permitted_execution_deadline(
        order.signal_index, configuration.maximum_execution_delay_bars
    )
    for index in range(order.earliest_fill_index, min(deadline, len(bars) - 1) + 1):
        bar = bars[index]
        if bar.market_status.upper() != "TRADEABLE":
            continue
        mode = (
            configuration.entry_fill_mode
            if order.side is FillSide.ENTRY
            else configuration.exit_fill_mode
        )
        use_close = mode in {FillPriceMode.NEXT_CLOSE, FillPriceMode.END_OF_BAR_EXIT}
        if order.side is FillSide.ENTRY:
            quote = bar.close_ask if use_close else bar.open_ask
        else:
            quote = bar.close_bid if use_close else bar.open_bid
        midpoint = (
            (bar.close_bid + bar.close_ask) / 2 if use_close else (bar.open_bid + bar.open_ask) / 2
        )
        multiplier = (
            1.0 + configuration.slippage_bps / 10_000.0
            if order.side is FillSide.ENTRY
            else 1.0 - configuration.slippage_bps / 10_000.0
        )
        fill_price = quote * multiplier
        slippage = abs(fill_price - quote) * configuration.fixed_quantity
        commission = _commission(fill_price, configuration)
        return (
            SimulatedFill(
                signal_index=order.signal_index,
                fill_index=index,
                timestamp=bar.timestamp,
                side=order.side,
                quote_price=quote,
                midpoint_price=midpoint,
                fill_price=fill_price,
                quantity=configuration.fixed_quantity,
                slippage_cost=slippage,
                commission_cost=commission,
                variant=order.variant,
                fill_price_mode=mode,
            ),
            None,
        )
    if order.earliest_fill_index >= len(bars):
        return None, "NEXT_BAR_UNAVAILABLE"
    return None, "NEXT_BAR_NON_TRADEABLE_OR_DELAY_EXCEEDED"


def protective_stop_fill(
    entry_fill: SimulatedFill,
    bar: BacktestBar,
    index: int,
    configuration: BacktestConfiguration,
) -> SimulatedFill | None:
    if not intrabar_evaluation_allowed(entry_fill, index):
        return None
    stop_level = entry_fill.fill_price * (1.0 - configuration.protective_stop_bps / 10_000.0)
    if bar.low_bid > stop_level:
        return None
    quote = min(stop_level, bar.open_bid)
    fill_price = quote * (1.0 - configuration.slippage_bps / 10_000.0)
    return SimulatedFill(
        signal_index=index,
        fill_index=index,
        timestamp=bar.timestamp,
        side=FillSide.EXIT,
        quote_price=quote,
        midpoint_price=(bar.open_bid + bar.open_ask) / 2,
        fill_price=fill_price,
        quantity=configuration.fixed_quantity,
        slippage_cost=abs(fill_price - quote) * configuration.fixed_quantity,
        commission_cost=_commission(fill_price, configuration),
        variant=entry_fill.variant,
        fill_price_mode=FillPriceMode.PROTECTIVE_STOP_LEVEL,
    )


def profit_target_fill(
    entry_fill: SimulatedFill,
    bar: BacktestBar,
    index: int,
    configuration: BacktestConfiguration,
) -> SimulatedFill | None:
    """Bid-side fill at the configured profit target.

    A gap-open above the target fills at the (better) open bid; otherwise the
    limit level itself fills. Adverse slippage is still charged, matching the
    engine's conservative fill philosophy.
    """

    if configuration.profit_target_bps is None:
        return None
    if not intrabar_evaluation_allowed(entry_fill, index):
        return None
    target_level = entry_fill.fill_price * (1.0 + configuration.profit_target_bps / 10_000.0)
    if bar.high_bid < target_level:
        return None
    quote = max(target_level, bar.open_bid)
    fill_price = quote * (1.0 - configuration.slippage_bps / 10_000.0)
    return SimulatedFill(
        signal_index=index,
        fill_index=index,
        timestamp=bar.timestamp,
        side=FillSide.EXIT,
        quote_price=quote,
        midpoint_price=(bar.open_bid + bar.open_ask) / 2,
        fill_price=fill_price,
        quantity=configuration.fixed_quantity,
        slippage_cost=abs(fill_price - quote) * configuration.fixed_quantity,
        commission_cost=_commission(fill_price, configuration),
        variant=entry_fill.variant,
        fill_price_mode=FillPriceMode.PROFIT_TARGET_LEVEL,
    )


def end_of_data_fill(
    entry_fill: SimulatedFill,
    bars: tuple[BacktestBar, ...],
    evaluation_end_index: int,
    configuration: BacktestConfiguration,
) -> SimulatedFill | None:
    first_eligible = entry_fill.fill_index
    if entry_fill.fill_price_mode is FillPriceMode.NEXT_CLOSE:
        first_eligible += 1
    for index in range(evaluation_end_index, first_eligible - 1, -1):
        bar = bars[index]
        if bar.market_status.upper() == "TRADEABLE":
            return _end_of_data_fill_at_bar(entry_fill, bar, index, configuration)
    return None


def _end_of_data_fill_at_bar(
    entry_fill: SimulatedFill,
    bar: BacktestBar,
    index: int,
    configuration: BacktestConfiguration,
) -> SimulatedFill:
    quote = bar.close_bid
    fill_price = quote * (1.0 - configuration.slippage_bps / 10_000.0)
    return SimulatedFill(
        signal_index=index,
        fill_index=index,
        timestamp=bar.timestamp,
        side=FillSide.EXIT,
        quote_price=quote,
        midpoint_price=(bar.close_bid + bar.close_ask) / 2,
        fill_price=fill_price,
        quantity=configuration.fixed_quantity,
        slippage_cost=abs(fill_price - quote) * configuration.fixed_quantity,
        commission_cost=_commission(fill_price, configuration),
        variant=entry_fill.variant,
        fill_price_mode=FillPriceMode.END_OF_BAR_EXIT,
    )


def create_trade(
    epic: str,
    regime: Regime,
    entry: SimulatedFill,
    exit_fill: SimulatedFill,
    exit_reason: ExitReason,
    configuration: BacktestConfiguration,
    *,
    intrabar_ambiguous: bool = False,
) -> BacktestTrade:
    quantity = entry.quantity
    gross_pnl = (exit_fill.midpoint_price - entry.midpoint_price) * quantity
    spread = max(
        (
            (entry.quote_price - entry.midpoint_price)
            + (exit_fill.midpoint_price - exit_fill.quote_price)
        )
        * quantity,
        0.0,
    )
    slippage = entry.slippage_cost + exit_fill.slippage_cost
    commission = entry.commission_cost + exit_fill.commission_cost
    holding_days = days_held(entry.timestamp, exit_fill.timestamp)
    funding = (
        entry.midpoint_price
        * quantity
        * configuration.overnight_funding_bps_per_day
        / 10_000.0
        * holding_days
    )
    premium = configuration.guaranteed_stop_premium
    total_cost = spread + slippage + commission + funding + premium
    return BacktestTrade(
        epic=epic,
        variant=entry.variant,
        signal_regime=regime,
        entry_fill=entry,
        exit_fill=exit_fill,
        exit_reason=exit_reason,
        holding_bars=exit_fill.fill_index - entry.fill_index,
        holding_days=holding_days,
        gross_pnl=gross_pnl,
        spread_impact=spread,
        slippage_cost=slippage,
        commission_cost=commission,
        funding_cost=funding,
        guaranteed_stop_premium=premium,
        total_cost=total_cost,
        net_pnl=gross_pnl - total_cost,
        intrabar_ambiguous=intrabar_ambiguous,
        ambiguity_policy=configuration.ambiguity_policy,
    )


def resolve_intrabar_ambiguity(
    low_bid: float,
    high_bid: float,
    stop_level: float,
    target_level: float,
    policy: IntrabarAmbiguityPolicy,
    *,
    entry_fill: SimulatedFill | None = None,
    bar_index: int | None = None,
) -> str | None:
    if entry_fill is not None:
        if bar_index is None:
            raise ValueError("bar index is required when entry timing is supplied")
        if not intrabar_evaluation_allowed(entry_fill, bar_index):
            return None
    stop_hit = low_bid <= stop_level
    target_hit = high_bid >= target_level
    if stop_hit and target_hit:
        if policy is IntrabarAmbiguityPolicy.ADVERSE_FIRST:
            return "STOP"
        if policy is IntrabarAmbiguityPolicy.FAVORABLE_FIRST:
            return "TARGET"
        return None
    if stop_hit:
        return "STOP"
    if target_hit:
        return "TARGET"
    return None


def intrabar_evaluation_allowed(entry_fill: SimulatedFill, bar_index: int) -> bool:
    if bar_index < entry_fill.fill_index:
        return False
    if entry_fill.fill_price_mode is FillPriceMode.NEXT_CLOSE:
        return bar_index > entry_fill.fill_index
    return True


def _commission(price: float, configuration: BacktestConfiguration) -> float:
    return configuration.fixed_commission_per_side + (
        price * configuration.fixed_quantity * configuration.proportional_commission_bps / 10_000.0
    )
