"""Deterministic CSV/Parquet loading and strategy-domain normalization."""

from __future__ import annotations

import csv
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from trading_desk.backtest.models import BacktestBar, BacktestDataManifest, BacktestDataset
from trading_desk.backtest.validation import BacktestDataError, validate_bars
from trading_desk.strategy.models import StrategyBarResolution, StrategyMarketData

_REQUIRED_COLUMNS = (
    "epic",
    "timestamp",
    "open_bid",
    "open_ask",
    "high_bid",
    "high_ask",
    "low_bid",
    "low_ask",
    "close_bid",
    "close_ask",
)


def load_dataset(path: str | Path, resolution: StrategyBarResolution) -> BacktestDataset:
    source = Path(path)
    raw = source.read_bytes()
    suffix = source.suffix.lower()
    if suffix == ".csv":
        with source.open("r", encoding="utf-8", newline="") as handle:
            rows = tuple(csv.DictReader(handle))
    elif suffix in {".parquet", ".pq"}:
        try:
            import pandas as pd  # type: ignore[import-untyped]
        except ImportError as error:
            raise BacktestDataError("Parquet support requires pandas and pyarrow") from error
        rows = tuple(pd.read_parquet(source).to_dict(orient="records"))
    else:
        raise BacktestDataError("dataset must be CSV or Parquet")
    return dataset_from_rows(rows, source.name, hashlib.sha256(raw).hexdigest(), resolution)


def dataset_from_rows(
    rows: tuple[dict[str, Any], ...],
    source_filename: str,
    content_sha256: str,
    resolution: StrategyBarResolution,
) -> BacktestDataset:
    bars: list[BacktestBar] = []
    for row_number, row in enumerate(rows, start=2):
        missing = [name for name in _REQUIRED_COLUMNS if row.get(name) in (None, "")]
        if missing:
            raise BacktestDataError(
                f"row {row_number} is missing required fields: {', '.join(missing)}"
            )
        try:
            timestamp = _timestamp(row["timestamp"])
            bars.append(
                BacktestBar(
                    epic=str(row["epic"]),
                    timestamp=timestamp,
                    open_bid=float(row["open_bid"]),
                    open_ask=float(row["open_ask"]),
                    high_bid=float(row["high_bid"]),
                    high_ask=float(row["high_ask"]),
                    low_bid=float(row["low_bid"]),
                    low_ask=float(row["low_ask"]),
                    close_bid=float(row["close_bid"]),
                    close_ask=float(row["close_ask"]),
                    last_traded_volume=(
                        None
                        if row.get("last_traded_volume") in (None, "")
                        else float(row["last_traded_volume"])
                    ),
                    market_status=str(row.get("market_status") or "TRADEABLE"),
                )
            )
        except (TypeError, ValueError, ValidationError) as error:
            raise BacktestDataError(f"row {row_number} failed strict validation") from error
    bar_tuple = tuple(bars)
    findings = validate_bars(bar_tuple, resolution)
    epics = {bar.epic for bar in bar_tuple}
    if len(epics) != 1:
        raise BacktestDataError("one dataset may contain only one EPIC")
    manifest = BacktestDataManifest(
        source_filename=Path(source_filename).name,
        content_sha256=content_sha256,
        row_count=len(bar_tuple),
        first_timestamp=bar_tuple[0].timestamp,
        last_timestamp=bar_tuple[-1].timestamp,
        resolution=resolution,
        findings=findings,
    )
    return BacktestDataset(bars=bar_tuple, manifest=manifest)


def strategy_data_from_bars(
    bars: tuple[BacktestBar, ...],
    resolution: StrategyBarResolution,
    *,
    instrument_name: str | None = None,
) -> StrategyMarketData:
    if not bars:
        raise BacktestDataError("cannot normalize an empty bar slice")
    opens = tuple((bar.open_bid + bar.open_ask) / 2 for bar in bars)
    highs = tuple((bar.high_bid + bar.high_ask) / 2 for bar in bars)
    lows = tuple((bar.low_bid + bar.low_ask) / 2 for bar in bars)
    closes = tuple((bar.close_bid + bar.close_ask) / 2 for bar in bars)
    spreads = tuple(bar.close_ask - bar.close_bid for bar in bars)
    spread_bps = tuple(
        10_000.0 * spread / close for spread, close in zip(spreads, closes, strict=True)
    )
    return StrategyMarketData(
        epic=bars[0].epic,
        instrument_name=instrument_name or bars[0].epic,
        timestamps=tuple(bar.timestamp for bar in bars),
        open_midpoints=opens,
        high_midpoints=highs,
        low_midpoints=lows,
        close_midpoints=closes,
        bids=tuple(bar.close_bid for bar in bars),
        asks=tuple(bar.close_ask for bar in bars),
        spreads=spreads,
        spread_bps=spread_bps,
        volume=tuple(bar.last_traded_volume for bar in bars),
        market_status=bars[-1].market_status,
        data_retrieval_time=bars[-1].timestamp,
        bar_resolution=resolution,
        source_bar_count=len(bars),
    )


def _timestamp(value: Any) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError("timestamps must include an explicit timezone")
    return parsed
