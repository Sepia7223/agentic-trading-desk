"""Governed daily-timeframe strategy search with a committed results ledger.

Runs a single portfolio strategy on one pair's DAILY bars over the development +
validation window (never the locked final-test partition), net of real costs,
using the DAY-scale context configuration. Appends one deterministic record per
run to ``artifacts/strategy_research/daily_ledger.jsonl`` and prints the metrics
against the Milestone 12 predetermined gates.

This is research tooling: it ranks candidates for human promotion review and
grants no lifecycle, Demo, Risk, execution, or Live authority. It is separate
from the Milestone 12 validation CLI and does not alter it.

Usage:
    PYTHONPATH=src python scripts/daily_strategy_search.py --pair USDJPY
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from trading_desk.strategy.configuration import StrategyConfiguration
from trading_desk.strategy.donchian_breakout import DonchianBreakoutEvaluator
from trading_desk.strategy.models import StrategyBarResolution
from trading_desk.strategy.portfolio_configuration import DonchianBreakoutConfiguration
from trading_desk.strategy.validation import calculate_metrics
from trading_desk.strategy.validation_cli import PAIR_EPICS
from trading_desk.strategy.validation_runner import (
    CausalContextBuilder,
    SimulatedStrategy,
    SimulationCosts,
    load_bars,
    simulate_strategies,
)

DEV_START = datetime(2019, 7, 1, tzinfo=UTC)
VALIDATION_END = datetime(2025, 6, 30, 23, 59, 59, tzinfo=UTC)
DAY_CONTEXT_WINDOW = 250

# Milestone 12 predetermined gates (development + validation aggregate).
MIN_TRADES = 100
MIN_PROFIT_FACTOR = Decimal("1.10")
MAX_DRAWDOWN = Decimal("0.20")

LEDGER = Path("artifacts/strategy_research/daily_ledger.jsonl")
MANIFEST = Path("artifacts/strategy_validation/dataset/manifest.json")


def _dataset_fingerprint() -> str:
    if MANIFEST.is_file():
        return str(json.loads(MANIFEST.read_text(encoding="utf-8")).get("dataset_fingerprint", ""))
    return ""


def _simulate_pair(pair: str, config: DonchianBreakoutConfiguration, bars_root: Path):  # type: ignore[no-untyped-def]
    epic, instrument = PAIR_EPICS[pair]
    strategy = SimulatedStrategy(
        evaluator=DonchianBreakoutEvaluator(config),
        maximum_holding_bars=config.maximum_holding_bars,
        configuration_fingerprint=config.fingerprint,
    )
    bars = load_bars(bars_root / f"{pair}_DAY.csv", epic=epic)
    builder = CausalContextBuilder(
        epic=epic,
        instrument=instrument,
        resolution=StrategyBarResolution.DAY,
        strategy_configuration=StrategyConfiguration(),
        window_size=DAY_CONTEXT_WINDOW,
    )
    (result,) = simulate_strategies(
        (strategy,),
        bars,
        builder=builder,
        costs=SimulationCosts(),
        evaluation_start=DEV_START,
        evaluation_end=VALIDATION_END,
        trade_prefix=f"{pair}-DAY",
    )
    return result, len(bars)


def _run(
    pairs: list[str], config: DonchianBreakoutConfiguration, bars_root: Path
) -> dict[str, object]:
    trades = []
    candidate_count = 0
    rejection_count = 0
    total_bars = 0
    for pair in pairs:
        result, bar_count = _simulate_pair(pair, config, bars_root)
        trades.extend(result.trades)
        candidate_count += result.candidate_count
        rejection_count += result.rejection_count
        total_bars += bar_count
    metrics = calculate_metrics(
        tuple(trades), rejection_count=rejection_count, candidate_count=candidate_count
    )
    passes = (
        metrics.closed_trade_count >= MIN_TRADES
        and metrics.expectancy > 0
        and metrics.profit_factor is not None
        and metrics.profit_factor >= MIN_PROFIT_FACTOR
        and metrics.maximum_drawdown <= MAX_DRAWDOWN
    )
    return {
        "schema_version": "daily-research-v1",
        "pairs": pairs,
        "timeframe": "DAY",
        "stage": "development_validation",
        "strategy_id": "donchian-breakout",
        "strategy_version": "1.0.0",
        "configuration_fingerprint": config.fingerprint,
        "parameters": config.model_dump(mode="json"),
        "dataset_fingerprint": _dataset_fingerprint(),
        "bars": total_bars,
        "closed_trades": metrics.closed_trade_count,
        "win_rate": str(metrics.win_rate),
        "expectancy": str(metrics.expectancy),
        "profit_factor": None if metrics.profit_factor is None else str(metrics.profit_factor),
        "maximum_drawdown": str(metrics.maximum_drawdown),
        "candidate_count": candidate_count,
        "rejection_count": rejection_count,
        "gate_minimums": {
            "min_trades": MIN_TRADES,
            "min_profit_factor": str(MIN_PROFIT_FACTOR),
            "max_drawdown": str(MAX_DRAWDOWN),
        },
        "passes_gates": passes,
        "advisory": "research only; grants no lifecycle/Demo/Risk/execution/Live authority",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Governed daily strategy search")
    parser.add_argument("--pairs", required=True, help="comma-separated pairs, pooled")
    parser.add_argument("--entry-channel", type=int, default=None)
    parser.add_argument("--stop-atr", type=str, default=None)
    parser.add_argument("--bars-root", default="data/validation/bars")
    args = parser.parse_args(argv)
    pairs = [p.strip() for p in args.pairs.split(",") if p.strip()]
    overrides: dict[str, object] = {}
    if args.entry_channel is not None:
        overrides["entry_channel_window"] = args.entry_channel
    if args.stop_atr is not None:
        overrides["stop_atr_multiple"] = Decimal(args.stop_atr)
    config = DonchianBreakoutConfiguration(**overrides)
    record = _run(pairs, config, Path(args.bars_root))
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
    params = record["parameters"]
    channel = params["entry_channel_window"] if isinstance(params, dict) else "?"
    print(
        f"{'+'.join(pairs)} DAY donchian ch={channel}: "
        f"trades={record['closed_trades']} win_rate={record['win_rate']} "
        f"expectancy={record['expectancy']} pf={record['profit_factor']} "
        f"maxDD={record['maximum_drawdown']} passes_gates={record['passes_gates']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
