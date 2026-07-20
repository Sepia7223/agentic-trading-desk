"""Offline full-battery analysis of a captured strategy trade set.

Computes the Milestone-12 extended gates from an emitted ValidationTrade JSONL —
walk-forward consistency (profitable fraction across chronological windows),
cost-stress survival (expectancy at 1.25/1.5/2.0x costs), regime coverage, and
risk-adjusted return — without re-simulating. This is a governed research screen;
the authoritative walk-forward is the M12 validation CLI, and the locked
final-test remains the ultimate arbiter. Research only; no trading authority.

Usage:
    PYTHONPATH=src python scripts/full_battery_analysis.py TRADES.jsonl --windows 7
"""

from __future__ import annotations

import argparse
import json
from decimal import Decimal
from pathlib import Path

from trading_desk.strategy.validation import ValidationTrade, calculate_metrics

MIN_PROFITABLE_WINDOW_FRACTION = Decimal("0.60")
MIN_WALK_FORWARD_WINDOWS = 4
MAX_COST_SENSITIVITY = Decimal("0.50")
MIN_REGIMES = 2


def _load(path: Path) -> tuple[ValidationTrade, ...]:
    trades = [
        ValidationTrade.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return tuple(sorted(trades, key=lambda item: item.exit_at))


def _cost_stressed_expectancy(trades: tuple[ValidationTrade, ...], multiplier: Decimal) -> Decimal:
    nets = [
        item.gross_pnl
        - multiplier
        * (item.spread_cost + item.slippage_cost + item.commission_cost + item.funding_cost)
        for item in trades
    ]
    return sum(nets, Decimal(0)) / Decimal(len(nets))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline full-battery analysis")
    parser.add_argument("trades")
    parser.add_argument("--windows", type=int, default=7)
    parser.add_argument("--label", default="")
    args = parser.parse_args(argv)
    trades = _load(Path(args.trades))
    overall = calculate_metrics(trades)

    # Walk-forward: split by exit time into equal-time windows.
    start = trades[0].exit_at
    span = (trades[-1].exit_at - start).total_seconds()
    buckets: list[list[ValidationTrade]] = [[] for _ in range(args.windows)]
    for item in trades:
        frac = (item.exit_at - start).total_seconds() / span if span else 0.0
        index = min(args.windows - 1, int(frac * args.windows))
        buckets[index].append(item)
    window_expectancies = [
        calculate_metrics(tuple(bucket)).expectancy if bucket else None for bucket in buckets
    ]
    populated = [e for e in window_expectancies if e is not None]
    profitable = sum(1 for e in populated if e > 0)
    profitable_fraction = Decimal(profitable) / Decimal(len(populated)) if populated else Decimal(0)

    base = overall.expectancy or Decimal(0)
    stress = {
        str(m): _cost_stressed_expectancy(trades, Decimal(m)) for m in ("1.25", "1.50", "2.00")
    }
    doubled = stress["2.00"]
    cost_sensitivity = (base - doubled) / base if base > 0 else Decimal("999")

    regimes = sorted({item.regime for item in trades})

    checks = {
        "walk_forward_consistency": (
            len(populated) >= MIN_WALK_FORWARD_WINDOWS
            and profitable_fraction >= MIN_PROFITABLE_WINDOW_FRACTION
        ),
        "cost_stress_2x_positive": doubled > 0,
        "cost_sensitivity_bounded": base > 0 and cost_sensitivity <= MAX_COST_SENSITIVITY,
        "regime_coverage": len(regimes) >= MIN_REGIMES,
        "risk_adjusted_positive": overall.sharpe_ratio is not None and overall.sharpe_ratio > 0,
    }
    verdict = {
        "label": args.label,
        "trades": overall.closed_trade_count,
        "expectancy": str(base),
        "profit_factor": None if overall.profit_factor is None else str(overall.profit_factor),
        "sharpe_ratio": None if overall.sharpe_ratio is None else str(overall.sharpe_ratio),
        "maximum_drawdown": str(overall.maximum_drawdown),
        "walk_forward_windows_populated": len(populated),
        "walk_forward_profitable": profitable,
        "walk_forward_profitable_fraction": str(profitable_fraction),
        "window_expectancies": [None if e is None else str(e) for e in window_expectancies],
        "cost_stress_expectancy": {k: str(v) for k, v in stress.items()},
        "cost_sensitivity": str(cost_sensitivity),
        "regimes": regimes,
        "extended_gate_checks": checks,
        "all_extended_gates_pass": all(checks.values()),
        "advisory": "research screen; authoritative gates are the M12 CLI + locked final-test",
    }
    print(json.dumps(verdict, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
