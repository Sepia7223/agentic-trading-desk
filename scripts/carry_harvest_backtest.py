"""Pure carry-harvest research backtest (daily, long-only, low-turnover).

Tests the research-identified durable FX edge directly: hold a positive-carry pair
long while (a) its policy-rate carry is favourable and (b) a slow trend filter
confirms, harvesting daily swap income; exit when carry compresses, the trend
breaks, or a trailing stop fires. Because it holds for months and trades rarely,
transaction cost per unit time is tiny -- the hypothesis is that this is naturally
robust to a 2x transaction-cost stress, unlike the high-turnover hourly breakout.

RESEARCH ONLY. Uses carry_model (a policy-rate proxy, not a broker swap feed) and
the local daily validation bars; it touches no lifecycle/Demo/Risk/execution
authority and no M12 gate. Development+validation window only (never final-test).

Usage:
    PYTHONPATH=src python scripts/carry_harvest_backtest.py --pairs USDJPY,EURJPY
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from trading_desk.strategy.carry_model import annual_carry_percent, daily_carry_fraction
from trading_desk.strategy.validation_cli import PAIR_EPICS
from trading_desk.strategy.validation_runner import HistoricalBar, load_bars

DEV_START = datetime(2019, 7, 1, tzinfo=UTC)
VALIDATION_END = datetime(2025, 6, 30, 23, 59, 59, tzinfo=UTC)


@dataclass
class Position:
    entry_at: datetime
    exit_at: datetime
    gross_price: Decimal  # mid-to-mid price return, fraction of entry
    txn_cost: Decimal  # spread + slippage, both sides, fraction of entry
    carry: Decimal  # summed daily carry income, fraction of entry
    held_days: int


def _D(value: float) -> Decimal:
    return Decimal(str(value))


def _mid(bar: HistoricalBar, side: str) -> Decimal:
    if side == "open":
        return (_D(bar.open_bid) + _D(bar.open_ask)) / 2
    return (_D(bar.close_bid) + _D(bar.close_ask)) / 2


def backtest(
    pair: str,
    bars: tuple[HistoricalBar, ...],
    trend_window: int,
    entry_carry: Decimal,
    exit_carry: Decimal,
    trailing_stop: Decimal,
    slippage: Decimal,
) -> list[Position]:
    window = [b for b in bars if DEV_START <= b.timestamp <= VALIDATION_END]
    positions: list[Position] = []
    in_pos = False
    entry_bar: HistoricalBar | None = None
    entry_mid = Decimal("0")
    peak_mid = Decimal("0")
    carry_accum = Decimal("0")
    entry_index = 0

    closes = [_mid(b, "close") for b in window]
    for i in range(trend_window, len(window) - 1):
        bar = window[i]
        nxt = window[i + 1]
        sma = sum(closes[i - trend_window : i]) / trend_window
        close = closes[i]
        carry_annual = annual_carry_percent(pair, bar.timestamp.date())
        carry_now = daily_carry_fraction(pair, bar.timestamp.date())

        if not in_pos:
            if carry_annual > entry_carry and close > sma:
                in_pos = True
                entry_bar = nxt
                entry_mid = _mid(nxt, "open")
                peak_mid = entry_mid
                carry_accum = Decimal("0")
                entry_index = i + 1
        else:
            carry_accum += carry_now  # one day's carry accrues while held
            peak_mid = max(peak_mid, close)
            drawdown = (peak_mid - close) / peak_mid if peak_mid else Decimal("0")
            exit_now = (
                carry_annual <= exit_carry
                or close < sma
                or drawdown >= trailing_stop / Decimal("100")
            )
            if exit_now:
                assert entry_bar is not None
                exit_mid = _mid(nxt, "open")
                gross_price = (exit_mid - entry_mid) / entry_mid
                half_spread_in = (_D(entry_bar.open_ask) - _D(entry_bar.open_bid)) / 2 / entry_mid
                half_spread_out = (_D(nxt.open_ask) - _D(nxt.open_bid)) / 2 / entry_mid
                txn = half_spread_in + half_spread_out + 2 * slippage
                positions.append(
                    Position(
                        entry_at=entry_bar.timestamp,
                        exit_at=nxt.timestamp,
                        gross_price=gross_price,
                        txn_cost=txn,
                        carry=carry_accum,
                        held_days=i + 1 - entry_index,
                    )
                )
                in_pos = False
    return positions


def summarise(pair: str, positions: list[Position]) -> dict:
    n = len(positions)
    if n == 0:
        return {"pair": pair, "round_trips": 0, "note": "no positions taken"}

    def total(k_txn: Decimal, carry_keep: Decimal) -> Decimal:
        return sum(
            (p.gross_price - k_txn * p.txn_cost + carry_keep * p.carry for p in positions),
            Decimal("0"),
        )

    net_1x = total(Decimal("1"), Decimal("1"))
    net_2x = total(Decimal("2"), Decimal("1"))
    net_2x_nocarry = total(Decimal("2"), Decimal("0"))
    gross_price = sum((p.gross_price for p in positions), Decimal("0"))
    carry_total = sum((p.carry for p in positions), Decimal("0"))
    txn_total = sum((p.txn_cost for p in positions), Decimal("0"))
    wins = sum(1 for p in positions if (p.gross_price - p.txn_cost + p.carry) > 0)
    avg_hold = sum(p.held_days for p in positions) / n
    return {
        "pair": pair,
        "round_trips": n,
        "avg_hold_days": round(avg_hold, 1),
        "win_rate": f"{wins / n:.2f}",
        "gross_price_return": f"{gross_price:+.4f}",
        "carry_income_total": f"{carry_total:+.4f}",
        "txn_cost_total": f"{txn_total:.4f}",
        "net_1x": f"{net_1x:+.4f}",
        "net_2x_txn": f"{net_2x:+.4f}",
        "net_2x_txn_no_carry": f"{net_2x_nocarry:+.4f}",
        "positive_at_2x_costs": net_2x > 0,
        "carry_is_load_bearing": net_2x > 0 and net_2x_nocarry <= 0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pure carry-harvest research backtest")
    parser.add_argument("--pairs", default="USDJPY,EURJPY")
    parser.add_argument("--trend-window", type=int, default=100)
    parser.add_argument("--entry-carry", type=str, default="0.5")
    parser.add_argument("--exit-carry", type=str, default="-1.0")
    parser.add_argument("--trailing-stop", type=str, default="15")
    parser.add_argument("--slippage", type=str, default="0.00005")
    parser.add_argument("--bars-root", default="data/validation/bars")
    args = parser.parse_args(argv)

    pairs = [p.strip() for p in args.pairs.split(",") if p.strip()]
    root = Path(args.bars_root)
    for pair in pairs:
        epic, _ = PAIR_EPICS[pair]
        bars = load_bars(root / f"{pair}_DAY.csv", epic=epic)
        positions = backtest(
            pair,
            bars,
            args.trend_window,
            Decimal(args.entry_carry),
            Decimal(args.exit_carry),
            Decimal(args.trailing_stop),
            Decimal(args.slippage),
        )
        print(json.dumps(summarise(pair, positions), sort_keys=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
