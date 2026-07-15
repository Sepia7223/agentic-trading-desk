"""Credential-free local JSON, CSV, and Markdown exports."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from trading_desk.backtest.models import BacktestRun


def export_json(run: BacktestRun, path: str | Path) -> None:
    Path(path).write_text(
        json.dumps(run.model_dump(mode="json"), indent=2, sort_keys=True),
        encoding="utf-8",
    )


def export_trades_csv(run: BacktestRun, path: str | Path) -> None:
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "variant",
                "entry_timestamp",
                "exit_timestamp",
                "exit_reason",
                "gross_pnl",
                "total_cost",
                "net_pnl",
            ),
        )
        writer.writeheader()
        for trade in run.trades:
            writer.writerow(
                {
                    "variant": trade.variant.value,
                    "entry_timestamp": trade.entry_fill.timestamp.isoformat(),
                    "exit_timestamp": trade.exit_fill.timestamp.isoformat(),
                    "exit_reason": trade.exit_reason.value,
                    "gross_pnl": trade.gross_pnl,
                    "total_cost": trade.total_cost,
                    "net_pnl": trade.net_pnl,
                }
            )


def export_markdown(run: BacktestRun, path: str | Path) -> None:
    content = "\n".join(
        (
            f"# Backtest: {run.variant.value}",
            "",
            f"- Run fingerprint: `{run.run_fingerprint}`",
            f"- Dataset hash: `{run.manifest.content_sha256}`",
            f"- Test net return: {run.metrics.net_return:.6f}",
            f"- Maximum drawdown: {run.metrics.maximum_drawdown:.6f}",
            f"- Trades: {run.metrics.trade_count}",
            f"- Forced valid end-of-data liquidations: {run.forced_end_of_data_closures}",
            f"- Unresolved open positions: {len(run.unresolved_positions)}",
            f"- Realized net P&L: {run.metrics.realized_net_pnl:.6f}",
            f"- Costs: {sum(trade.total_cost for trade in run.trades):.6f}",
            "",
            (
                "A profitable backtest is evidence for further testing, not proof of a "
                "profitable live strategy."
            ),
        )
    )
    Path(path).write_text(content + "\n", encoding="utf-8")
