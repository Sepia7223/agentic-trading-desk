"""Cutoff-safe context-grouped performance and historical expectancy."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from trading_desk.context.fingerprints import fingerprint
from trading_desk.context.models import MarketContextSnapshot


class ContextualModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


class ContextualTradeObservation(ContextualModel):
    strategy_id: str
    return_fraction: Decimal
    cost: Decimal = Field(ge=0)
    maximum_favorable_excursion: Decimal
    maximum_adverse_excursion: Decimal
    exposure_fraction: Decimal = Field(ge=0, le=1)
    turnover: Decimal = Field(ge=0)
    closed_at: datetime
    context: MarketContextSnapshot

    @field_validator("closed_at")
    @classmethod
    def utc_closed(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("trade close must be timezone-aware UTC")
        return value


class ContextPerformanceSummary(ContextualModel):
    summary_id: str = Field(min_length=64, max_length=64)
    group: tuple[tuple[str, str], ...]
    cutoff_timestamp: datetime
    sample_size: int
    sufficient_sample: bool
    net_expectancy: Decimal
    median_return: Decimal
    net_return: Decimal
    maximum_drawdown: Decimal
    sharpe: Decimal | None
    sortino: Decimal | None
    profit_factor: Decimal | None
    win_rate: Decimal
    payoff_ratio: Decimal | None
    exposure: Decimal
    turnover: Decimal
    costs: Decimal
    average_cost: Decimal
    average_mfe: Decimal
    average_mae: Decimal
    recent_performance: Decimal
    stability_score: Decimal


def summarize_contextual_performance(
    observations: tuple[ContextualTradeObservation, ...],
    *,
    cutoff_timestamp: datetime,
    minimum_sample_size: int = 30,
) -> tuple[ContextPerformanceSummary, ...]:
    if cutoff_timestamp.tzinfo is None:
        raise ValueError("expectancy cutoff must be timezone-aware")
    visible = tuple(item for item in observations if item.closed_at <= cutoff_timestamp)
    groups: dict[tuple[tuple[str, str], ...], list[ContextualTradeObservation]] = {}
    for item in visible:
        groups.setdefault(_group_key(item), []).append(item)
    return tuple(
        _summary(key, tuple(values), cutoff_timestamp, minimum_sample_size)
        for key, values in sorted(groups.items())
    )


def _group_key(item: ContextualTradeObservation) -> tuple[tuple[str, str], ...]:
    context = item.context
    spread_bucket = (
        "LOW" if context.spread_bps <= 3 else "NORMAL" if context.spread_bps <= 10 else "WIDE"
    )
    return (
        ("strategy", item.strategy_id),
        ("session", context.session.value),
        ("overlap", str(context.session_overlap).lower()),
        ("liquidity", context.liquidity_state.value),
        ("volatility", context.volatility_state.value),
        ("trend", context.trend_state.value),
        ("event", context.scheduled_event_state.value),
        ("weekday", str(context.day_of_week)),
        ("spread_bucket", spread_bucket),
        ("instrument", context.epic),
        ("timeframe", context.timeframe.value),
    )


def _summary(
    key: tuple[tuple[str, str], ...],
    values: tuple[ContextualTradeObservation, ...],
    cutoff: datetime,
    minimum: int,
) -> ContextPerformanceSummary:
    returns = tuple(item.return_fraction - item.cost for item in values)
    count = len(returns)
    wins = tuple(value for value in returns if value > 0)
    losses = tuple(value for value in returns if value < 0)
    mean = sum(returns, Decimal("0")) / Decimal(count)
    ordered = sorted(returns)
    median = (
        ordered[count // 2] if count % 2 else (ordered[count // 2 - 1] + ordered[count // 2]) / 2
    )
    variance = sum(((value - mean) ** 2 for value in returns), Decimal("0")) / Decimal(count)
    stdev = variance.sqrt()
    downside = tuple(value for value in returns if value < 0)
    downside_dev = (
        (sum((value**2 for value in downside), Decimal("0")) / Decimal(len(downside))).sqrt()
        if downside
        else Decimal("0")
    )
    equity = Decimal("0")
    peak = Decimal("0")
    drawdown = Decimal("0")
    for value in returns:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    gross_win = sum(wins, Decimal("0"))
    gross_loss = abs(sum(losses, Decimal("0")))
    average_win = gross_win / Decimal(len(wins)) if wins else None
    average_loss = gross_loss / Decimal(len(losses)) if losses else None
    recent = sum(returns[-min(20, count) :], Decimal("0")) / Decimal(min(20, count))
    stability = Decimal("1") / (Decimal("1") + stdev)
    fields = {
        "group": key,
        "cutoff_timestamp": cutoff.astimezone(UTC),
        "sample_size": count,
        "sufficient_sample": count >= minimum,
        "net_expectancy": mean,
        "median_return": median,
        "net_return": sum(returns, Decimal("0")),
        "maximum_drawdown": drawdown,
        "sharpe": mean / stdev if stdev else None,
        "sortino": mean / downside_dev if downside_dev else None,
        "profit_factor": gross_win / gross_loss if gross_loss else None,
        "win_rate": Decimal(len(wins)) / Decimal(count),
        "payoff_ratio": average_win / average_loss
        if average_win is not None and average_loss
        else None,
        "exposure": sum((item.exposure_fraction for item in values), Decimal("0")) / Decimal(count),
        "turnover": sum((item.turnover for item in values), Decimal("0")),
        "costs": sum((item.cost for item in values), Decimal("0")),
        "average_cost": sum((item.cost for item in values), Decimal("0")) / Decimal(count),
        "average_mfe": sum((item.maximum_favorable_excursion for item in values), Decimal("0"))
        / Decimal(count),
        "average_mae": sum((item.maximum_adverse_excursion for item in values), Decimal("0"))
        / Decimal(count),
        "recent_performance": recent,
        "stability_score": stability,
    }
    return ContextPerformanceSummary.model_validate({"summary_id": fingerprint(fields), **fields})
