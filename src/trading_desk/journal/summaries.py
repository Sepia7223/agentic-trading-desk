"""UTC-bounded deterministic daily, weekly, and monthly summaries."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from trading_desk.journal.fingerprints import fingerprint
from trading_desk.journal.models import JournalQuery, JournalRecord, PeriodicReview

if TYPE_CHECKING:
    from trading_desk.ports.journal import JournalReader


def daily_review(reader: JournalReader, trading_day: date) -> PeriodicReview:
    start = datetime.combine(trading_day, time.min, tzinfo=UTC)
    return _periodic_review(reader, "DAILY", start, start + timedelta(days=1))


def weekly_review(reader: JournalReader, year: int, week: int) -> PeriodicReview:
    start_date = date.fromisocalendar(year, week, 1)
    start = datetime.combine(start_date, time.min, tzinfo=UTC)
    return _periodic_review(reader, "WEEKLY", start, start + timedelta(days=7))


def monthly_review(reader: JournalReader, year: int, month: int) -> PeriodicReview:
    start = datetime(year, month, 1, tzinfo=UTC)
    end = datetime(year + int(month == 12), month % 12 + 1, 1, tzinfo=UTC)
    return _periodic_review(reader, "MONTHLY", start, end)


def _periodic_review(
    reader: JournalReader, period_type: str, start: datetime, end_exclusive: datetime
) -> PeriodicReview:
    inclusive_end = end_exclusive - timedelta(microseconds=1)
    records = _period_records(reader, start, inclusive_end)
    counts: defaultdict[str, int] = defaultdict(int)
    totals: defaultdict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    breakdowns: defaultdict[str, defaultdict[str, Decimal | int]] = defaultdict(
        lambda: defaultdict(int)
    )
    for record in records:
        _accumulate(record, counts, totals, breakdowns)
    fields = {
        "period_type": period_type,
        "period_start": start,
        "period_end": inclusive_end,
        "sample_size": len(records),
        "counts": dict(sorted(counts.items())),
        "totals": dict(sorted(totals.items())),
        "breakdowns": {
            key: dict(sorted(values.items())) for key, values in sorted(breakdowns.items())
        },
        "metrics": _review_metrics(records),
        "insufficient_sample": counts.get("closed_trades", 0) < 30,
    }
    return PeriodicReview.model_validate({**fields, "review_fingerprint": fingerprint(fields)})


def _period_records(
    reader: JournalReader, start: datetime, inclusive_end: datetime
) -> tuple[JournalRecord, ...]:
    records: list[JournalRecord] = []
    offset = 0
    while True:
        result = reader.query(
            JournalQuery(
                start_at=start,
                end_at=inclusive_end,
                cutoff_at=inclusive_end,
                limit=1_000,
                offset=offset,
            )
        )
        records.extend(result.records)
        if result.next_offset is None:
            return tuple(records)
        offset = result.next_offset


def _accumulate(
    record: JournalRecord,
    counts: defaultdict[str, int],
    totals: defaultdict[str, Decimal],
    breakdowns: defaultdict[str, defaultdict[str, Decimal | int]],
) -> None:
    counts[record.record_type.value] += 1
    payload = record.payload
    for key in ("action", "status", "process_classification", "financial_outcome"):
        value = payload.get(key)
        if value is not None:
            counts[f"{key}:{value}"] += 1
    for key in (
        "realized_pnl",
        "unrealized_pnl",
        "net_pnl",
        "total_costs",
        "drawdown",
        "exposure",
    ):
        value = _as_decimal(payload.get(key))
        if value is not None:
            totals[key] += value
    if record.instrument:
        breakdowns["instrument"][record.instrument] += 1
    if record.strategy_variant:
        breakdowns["strategy_variant"][record.strategy_variant] += 1
    regime = payload.get("entry_regime") or payload.get("current_regime")
    if regime:
        breakdowns["regime"][str(regime)] += 1
    reason_codes = payload.get("reason_codes", ())
    if isinstance(reason_codes, (list, tuple)):
        for reason in reason_codes:
            breakdowns["risk_reason"][str(reason)] += 1
    if record.record_type.value == "PAPER_CLOSED_TRADE":
        counts["closed_trades"] += 1


def _review_metrics(records: tuple[JournalRecord, ...]) -> dict[str, Decimal | int | str]:
    pnls = tuple(
        value
        for record in records
        if (value := _as_decimal(record.payload.get("net_pnl"))) is not None
        and record.record_type.value in {"PAPER_CLOSED_TRADE", "POST_TRADE_REVIEW"}
    )
    wins = tuple(value for value in pnls if value > 0)
    losses = tuple(-value for value in pnls if value < 0)
    holding_periods = tuple(
        value
        for record in records
        if (value := _as_decimal(record.payload.get("holding_period_seconds"))) is not None
        and value >= 0
    )
    risk_statuses = tuple(
        str(record.payload.get("status"))
        for record in records
        if record.record_type.value == "RISK_DECISION"
    )
    risk_approved = sum(status == "APPROVED" for status in risk_statuses)
    drawdowns = tuple(
        value
        for record in records
        if (value := _as_decimal(record.payload.get("drawdown"))) is not None
    )
    closed_count = len(pnls)
    gross_profit = sum(wins, Decimal("0"))
    gross_loss = sum(losses, Decimal("0"))
    metrics: dict[str, Decimal | int | str] = {
        "closed_trade_sample_size": closed_count,
        "win_count": len(wins),
        "loss_count": len(losses),
        "win_rate": Decimal(len(wins)) / Decimal(closed_count) if closed_count else Decimal("0"),
        "payoff_ratio": (
            (gross_profit / Decimal(len(wins))) / (gross_loss / Decimal(len(losses)))
            if wins and losses and gross_loss > 0
            else Decimal("0")
        ),
        "profit_factor": gross_profit / gross_loss if gross_loss > 0 else Decimal("0"),
        "average_holding_period_seconds": (
            sum(holding_periods, Decimal("0")) / Decimal(len(holding_periods))
            if holding_periods
            else Decimal("0")
        ),
        "risk_approval_rate": (
            Decimal(risk_approved) / Decimal(len(risk_statuses)) if risk_statuses else Decimal("0")
        ),
        "maximum_drawdown": max(drawdowns, default=Decimal("0")),
        "statistical_strength": "INSUFFICIENT" if closed_count < 30 else "DESCRIPTIVE",
    }
    return metrics


def _as_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None
