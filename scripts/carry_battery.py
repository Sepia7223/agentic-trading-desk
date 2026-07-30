"""Carry-aware research battery (offline overlay on emitted validation trades).

Re-prices emitted trades with a policy-rate carry proxy instead of the harness's
flat funding cost, then applies a corrected cost-stress: execution costs (spread,
slippage, commission) are stressed UP, while carry is treated as income and
stressed DOWN separately (its adverse scenario is compression toward zero, not
doubling as a cost). Reports per-pair whether the strategy is positive at 2x
execution costs and how robust that is to carry compression.

RESEARCH ONLY. Reads committed/emitted trades; does not touch the M12 validation
harness, its gates, or any lifecycle authority. Carry uses carry_model, a proxy
(see its docstring) that is not a promotable broker swap series.

Usage:
    PYTHONPATH=src python scripts/carry_battery.py <trades.jsonl> [--markup 1.0]
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from trading_desk.strategy.carry_model import annual_carry_percent, daily_carry_fraction


def _pair_of(trade_id: str) -> str:
    return trade_id.split("-", 1)[0]


def _load(path: Path) -> list[dict]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def _net(
    gross: Decimal, exec_cost: Decimal, carry: Decimal, k_exec: Decimal, carry_keep: Decimal
) -> Decimal:
    """net = gross - k*exec + kept carry (income if +, full debit if -)."""

    kept = carry * carry_keep if carry > 0 else carry
    return gross - k_exec * exec_cost + kept


def _expectancy(
    legs: list[tuple[Decimal, Decimal, Decimal]], k_exec: Decimal, carry_keep: Decimal
) -> Decimal:
    """Mean per-trade net over (gross, exec_cost, carry) legs at a stress setting."""

    total = sum((_net(g, e, c, k_exec, carry_keep) for g, e, c in legs), Decimal("0"))
    return total / len(legs)


def _profit_factor(nets: list[Decimal]) -> Decimal | None:
    wins = sum((n for n in nets if n > 0), Decimal("0"))
    losses = -sum((n for n in nets if n < 0), Decimal("0"))
    if losses == 0:
        return None
    return wins / losses


def analyse(path: Path, markup: Decimal, min_carry: Decimal = Decimal("-999")) -> list[dict]:
    rows = _load(path)
    by_pair: dict[str, list[dict]] = {}
    for r in rows:
        by_pair.setdefault(_pair_of(r["trade_id"]), []).append(r)

    one = Decimal("1")
    out: list[dict] = []
    for pair, trades in sorted(by_pair.items()):
        legs: list[tuple[Decimal, Decimal, Decimal]] = []
        carry_ann_weighted = Decimal("0")
        days_total = Decimal("0")
        for t in trades:
            entry = datetime.fromisoformat(t["entry_at"])
            # Carry filter: only keep trades whose entry-date annual carry clears
            # the threshold. Carry is known at entry, so this is equivalent to a
            # signal-time regime filter, not hindsight.
            entry_carry_annual = annual_carry_percent(pair, entry.date(), markup)
            if entry_carry_annual < min_carry:
                continue
            exit_ = datetime.fromisoformat(t["exit_at"])
            held_days = Decimal(str((exit_ - entry).total_seconds() / 86400))
            gross = Decimal(t["gross_pnl"])
            exec_cost = (
                Decimal(t["spread_cost"])
                + Decimal(t["slippage_cost"])
                + Decimal(t["commission_cost"])
            )
            carry = daily_carry_fraction(pair, entry.date(), markup) * held_days
            legs.append((gross, exec_cost, carry))
            carry_ann_weighted += entry_carry_annual * held_days
            days_total += held_days

        n = len(legs)
        if n == 0:
            continue
        avg_carry_ann = carry_ann_weighted / days_total if days_total else Decimal("0")

        # execution stress ladder (carry treated as income, unstressed)
        exp_1x = _expectancy(legs, one, one)
        exp_125 = _expectancy(legs, Decimal("1.25"), one)
        exp_15 = _expectancy(legs, Decimal("1.5"), one)
        exp_2x = _expectancy(legs, Decimal("2"), one)
        # carry-compression stress at 2x exec: keep 50% / 0% of carry income
        exp_2x_half = _expectancy(legs, Decimal("2"), Decimal("0.5"))
        exp_2x_zero = _expectancy(legs, Decimal("2"), Decimal("0"))

        nets_1x = [_net(g, e, c, one, one) for g, e, c in legs]
        pf = _profit_factor(nets_1x)

        out.append(
            {
                "pair": pair,
                "trades": n,
                "avg_annual_carry_pct": f"{avg_carry_ann:.2f}",
                "profit_factor_with_carry": None if pf is None else f"{pf:.3f}",
                "expectancy_1x_exec": f"{exp_1x:+.7f}",
                "expectancy_1.25x_exec": f"{exp_125:+.7f}",
                "expectancy_1.5x_exec": f"{exp_15:+.7f}",
                "expectancy_2x_exec": f"{exp_2x:+.7f}",
                "expectancy_2x_exec_carry_half": f"{exp_2x_half:+.7f}",
                "expectancy_2x_exec_carry_zero": f"{exp_2x_zero:+.7f}",
                "passes_2x_exec": exp_2x > 0,
                "carry_robust_2x_exec_half_carry": exp_2x_half > 0,
                "survives_carry_collapse": exp_2x_zero > 0,
            }
        )
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Carry-aware research battery")
    parser.add_argument("trades", help="emitted trades JSONL")
    parser.add_argument(
        "--markup", type=str, default="1.0", help="annual broker swap markup, percent"
    )
    parser.add_argument(
        "--min-carry",
        type=str,
        default="-999",
        help="only keep trades whose entry-date annual carry (pct) clears this",
    )
    args = parser.parse_args(argv)
    results = analyse(Path(args.trades), Decimal(args.markup), Decimal(args.min_carry))
    for r in results:
        print(json.dumps(r, sort_keys=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
