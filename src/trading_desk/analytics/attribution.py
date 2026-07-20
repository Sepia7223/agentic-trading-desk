"""Deterministic scorecard and attribution calculation.

Every aggregate reconciles exactly: dimension slices sum to the portfolio
totals, cost decomposition sums to total cost, and net equals gross minus
costs. Reconciliation is computed and recorded on the scorecard rather than
assumed. Trades in a non-reporting currency make currency-sensitive
measures explicitly unavailable instead of silently converting.
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal

from trading_desk.analytics.models import (
    CostDecomposition,
    DimensionName,
    DimensionSlice,
    Measure,
    MeasureConvention,
    PortfolioScorecard,
    TradeEvidence,
    available,
    create_scorecard,
    unavailable,
)

_DIMENSION_KEYS: dict[DimensionName, Callable[[TradeEvidence], str]] = {
    DimensionName.STRATEGY: lambda trade: trade.strategy_id,
    DimensionName.INSTRUMENT: lambda trade: trade.instrument,
    DimensionName.TIMEFRAME: lambda trade: trade.timeframe,
    DimensionName.REGIME: lambda trade: trade.regime,
    DimensionName.EXIT_REASON: lambda trade: trade.exit_reason,
}


def _mean(values: list[Decimal]) -> Decimal:
    return sum(values, Decimal(0)) / Decimal(len(values))


def _population_stddev(values: list[Decimal]) -> Decimal:
    mean = _mean(values)
    variance = sum(((item - mean) ** 2 for item in values), Decimal(0)) / Decimal(len(values))
    return variance.sqrt()


def _risk_ratio(values: list[Decimal]) -> Measure:
    if len(values) < 2:
        return unavailable("INSUFFICIENT_OBSERVATIONS")
    deviation = _population_stddev(values)
    if deviation == 0:
        return unavailable("ZERO_DISPERSION")
    return available(_mean(values) / deviation)


def _drawdown(ordered_net: list[Decimal]) -> tuple[Measure, Measure]:
    equity = Decimal(0)
    peak = Decimal(0)
    maximum = Decimal(0)
    duration = 0
    worst_duration = 0
    for value in ordered_net:
        equity += value
        if equity >= peak:
            peak = equity
            duration = 0
        else:
            duration += 1
            worst_duration = max(worst_duration, duration)
            maximum = max(maximum, peak - equity)
    return available(maximum), available(Decimal(worst_duration))


def build_scorecard(
    trades: tuple[TradeEvidence, ...], convention: MeasureConvention
) -> PortfolioScorecard:
    """Compute the full deterministic scorecard for one trade population."""

    ordered = tuple(sorted(trades, key=lambda item: (item.exit_at, item.trade_id)))
    foreign = any(item.currency != convention.reporting_currency for item in ordered)
    costs = CostDecomposition(
        spread=sum((item.spread_cost for item in ordered), Decimal(0)),
        slippage=sum((item.slippage_cost for item in ordered), Decimal(0)),
        commission=sum((item.commission_cost for item in ordered), Decimal(0)),
        funding=sum((item.funding_cost for item in ordered), Decimal(0)),
    )
    attribution: list[DimensionSlice] = []
    for dimension, key_of in _DIMENSION_KEYS.items():
        keys = sorted({key_of(item) for item in ordered})
        for key in keys:
            members = [item for item in ordered if key_of(item) == key]
            attribution.append(
                DimensionSlice(
                    dimension=dimension,
                    key=key,
                    trade_count=len(members),
                    gross_return=sum((item.gross_return for item in members), Decimal(0)),
                    net_return=sum((item.net_return for item in members), Decimal(0)),
                    total_cost=sum((item.total_cost for item in members), Decimal(0)),
                )
            )

    if not ordered:
        empty = unavailable("NO_CLOSED_TRADES")
        return create_scorecard(
            convention=convention,
            input_start=None,
            input_end=None,
            trade_count=0,
            source_record_count=0,
            gross_return=empty,
            net_return=empty,
            win_rate=empty,
            payoff_ratio=empty,
            expectancy=empty,
            profit_factor=empty,
            sharpe_like=empty,
            sortino_like=empty,
            maximum_drawdown=empty,
            recovery_duration_trades=empty,
            turnover=empty,
            exposure_seconds=empty,
            cost_drag=empty,
            costs=costs,
            attribution=(),
            reconciled=True,
        )

    if foreign:
        currency_blocked = unavailable("CURRENCY_CONVERSION_EVIDENCE_UNAVAILABLE")
        gross_measure = currency_blocked
        net_measure = currency_blocked
        expectancy_measure = currency_blocked
        cost_drag_measure = currency_blocked
        reconciled = False
    else:
        gross_total = sum((item.gross_return for item in ordered), Decimal(0))
        net_total = sum((item.net_return for item in ordered), Decimal(0))
        gross_measure = available(gross_total)
        net_measure = available(net_total)
        expectancy_measure = available(net_total / Decimal(len(ordered)))
        cost_drag_measure = available(costs.total)
        strategy_slices = [item for item in attribution if item.dimension is DimensionName.STRATEGY]
        reconciled = (
            sum((item.net_return for item in strategy_slices), Decimal(0)) == net_total
            and sum((item.gross_return for item in strategy_slices), Decimal(0)) == gross_total
            and net_total == gross_total - costs.total
        )

    nets = [item.net_return for item in ordered]
    wins = [value for value in nets if value > 0]
    losses = [value for value in nets if value < 0]
    win_rate = available(Decimal(len(wins)) / Decimal(len(ordered)))
    payoff = (
        available(_mean(wins) / abs(_mean(losses)))
        if wins and losses and _mean(losses) != 0
        else unavailable("NO_WINS_OR_NO_LOSSES")
    )
    gross_profit = sum(wins, Decimal(0))
    gross_loss = sum((abs(value) for value in losses), Decimal(0))
    profit_factor = available(gross_profit / gross_loss) if gross_loss else unavailable("NO_LOSSES")
    maximum_drawdown, recovery = _drawdown(nets)
    exposure = sum(
        (Decimal(int((item.exit_at - item.entry_at).total_seconds())) for item in ordered),
        Decimal(0),
    )
    return create_scorecard(
        convention=convention,
        input_start=min(item.entry_at for item in ordered),
        input_end=max(item.exit_at for item in ordered),
        trade_count=len(ordered),
        source_record_count=sum(len(item.source_record_ids) for item in ordered),
        gross_return=gross_measure,
        net_return=net_measure,
        win_rate=win_rate,
        payoff_ratio=payoff,
        expectancy=expectancy_measure,
        profit_factor=profit_factor,
        sharpe_like=_risk_ratio(nets),
        sortino_like=_risk_ratio(losses) if losses else unavailable("NO_LOSSES"),
        maximum_drawdown=maximum_drawdown,
        recovery_duration_trades=recovery,
        turnover=available(sum((item.turnover for item in ordered), Decimal(0))),
        exposure_seconds=available(exposure),
        cost_drag=cost_drag_measure,
        costs=costs,
        attribution=tuple(attribution),
        reconciled=reconciled,
    )
