"""Backend-authoritative deterministic performance projections."""

from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation

from trading_desk.operations.models import (
    PerformanceBreakdown,
    PerformanceSummary,
    RecordProjection,
)


def build_performance(
    closed_trades: tuple[RecordProjection, ...],
    latest_portfolio: RecordProjection | None,
) -> PerformanceSummary:
    values = tuple(
        (_decimal(item.payload.get("net_pnl")) or Decimal("0")) for item in closed_trades
    )
    wins = tuple(value for value in values if value > 0)
    losses = tuple(value for value in values if value < 0)
    realized = sum(values, Decimal("0"))
    equity: list[tuple[datetime, Decimal]] = []
    drawdown: list[tuple[datetime, Decimal]] = []
    daily: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    cumulative = Decimal("0")
    peak = Decimal("0")
    for record, value in zip(closed_trades, values, strict=True):
        cumulative += value
        peak = max(peak, cumulative)
        equity.append((record.effective_at, cumulative))
        drawdown.append((record.effective_at, cumulative - peak))
        daily[record.effective_at.date().isoformat()] += value
    commission = _sum(closed_trades, "commission", "entry_commission", "exit_commission")
    slippage = _sum(closed_trades, "slippage_cost", "entry_slippage_cost")
    spread = _sum(closed_trades, "spread_cost", "spread_costs")
    funding = _sum(closed_trades, "funding", "accrued_funding")
    explicit_total = _sum(closed_trades, "total_costs")
    total_costs = explicit_total or commission + slippage + spread + funding
    gross_exposure = _decimal_from_record(
        latest_portfolio, "gross_exposure", "current_exposure"
    ) or Decimal("0")
    unrealized = _decimal_from_record(latest_portfolio, "unrealized_pnl") or Decimal("0")
    turnover = sum((_trade_turnover(item) for item in closed_trades), Decimal("0"))
    return PerformanceSummary(
        sample_size=len(values),
        realized_pnl=realized,
        total_costs=total_costs,
        wins=len(wins),
        losses=len(losses),
        win_rate=_ratio(len(wins), len(values)),
        profit_factor=(
            sum(wins, Decimal("0")) / abs(sum(losses, Decimal("0"))) if losses else None
        ),
        expectancy=(realized / Decimal(len(values))) if values else None,
        equity_curve=tuple(equity),
        drawdown_curve=tuple(drawdown),
        daily_pnl=tuple(sorted(daily.items())),
        unrealized_pnl=unrealized,
        spread_costs=spread,
        slippage_costs=slippage,
        commissions=commission,
        funding=funding,
        gross_exposure=gross_exposure,
        turnover=turnover,
        payoff_ratio=(
            (sum(wins, Decimal("0")) / Decimal(len(wins)))
            / abs(sum(losses, Decimal("0")) / Decimal(len(losses)))
            if wins and losses
            else None
        ),
        by_instrument=_breakdown(closed_trades, "instrument"),
        by_strategy=_breakdown(closed_trades, "strategy_variant"),
        by_regime=_breakdown(closed_trades, "regime"),
        by_session=_breakdown(closed_trades, "session"),
        by_volatility_state=_breakdown(closed_trades, "volatility_state"),
        by_event_state=_breakdown(closed_trades, "event_state"),
        by_environment=_breakdown(closed_trades, "environment"),
    )


def _breakdown(records: tuple[RecordProjection, ...], key: str) -> tuple[PerformanceBreakdown, ...]:
    grouped: dict[str, list[Decimal]] = defaultdict(list)
    for record in records:
        value: object | None
        if key == "instrument":
            value = record.instrument
        elif key == "strategy_variant":
            value = record.strategy_variant
        elif key == "environment":
            value = record.environment
        else:
            value = record.payload.get(key)
        label = str(value or "UNKNOWN")
        grouped[label].append(_decimal(record.payload.get("net_pnl")) or Decimal("0"))
    return tuple(
        PerformanceBreakdown(
            label=label,
            sample_size=len(values),
            net_pnl=sum(values, Decimal("0")),
            wins=sum(value > 0 for value in values),
            losses=sum(value < 0 for value in values),
            win_rate=_ratio(sum(value > 0 for value in values), len(values)),
        )
        for label, values in sorted(grouped.items())
    )


def _sum(records: tuple[RecordProjection, ...], *keys: str) -> Decimal:
    total = Decimal("0")
    for record in records:
        total += sum(
            (_decimal(record.payload.get(key)) or Decimal("0") for key in keys),
            Decimal("0"),
        )
    return total


def _trade_turnover(record: RecordProjection) -> Decimal:
    quantity = _decimal(record.payload.get("quantity")) or Decimal("0")
    entry = _decimal(record.payload.get("entry_price")) or Decimal("0")
    exit_price = _decimal(record.payload.get("exit_price")) or Decimal("0")
    return quantity * (entry + exit_price)


def _decimal_from_record(record: RecordProjection | None, *keys: str) -> Decimal | None:
    if record is None:
        return None
    for key in keys:
        value = _decimal(record.payload.get(key))
        if value is not None:
            return value
    return None


def _decimal(value: object | None) -> Decimal | None:
    try:
        return None if value is None else Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _ratio(numerator: int, denominator: int) -> Decimal | None:
    return Decimal(numerator) / Decimal(denominator) if denominator else None
