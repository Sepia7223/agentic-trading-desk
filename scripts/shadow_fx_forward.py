#!/usr/bin/env python3
"""Nightly forward paper-trading log for the six FX pairs (mini PC).

HONEST FRAMING. The portfolio strategies (trend-pullback, volatility-breakout,
range-mean-reversion, donchian) FAILED their M12 historical validation gates on
15m/HOUR Dukascopy data (trend-pullback lost on all six pairs). This loop
forward-tests them on LIVE data at ZERO risk to accrue honest forward evidence.
It is NOT a proven edge and no promotion follows from it.

Setup mirrors the validated HOUR configuration (the intraday context
configuration + 300-bar window), so the evaluators actually trade -- on DAILY
bars the regime is almost never ready and nothing fires. One documented
approximation remains: Yahoo publishes MID only, so bid/ask are synthesized
from a fixed half-spread (Dukascopy carried real spreads).

Each run re-simulates the EXACT validated evaluators (imported from
validation_cli) over a rolling ~60-day hourly window per pair. Only closed
trades whose exit is on/after the deploy cutoff are journaled, deduplicated by
the natural (pair, strategy, entry, exit) key so the append log is stable even
as the rolling window advances.

Cron (weekdays 19:50, after the DTC shadow):
    50 19 * * 1-5 .../scripts/run_shadow_fx.sh
"""

from __future__ import annotations

import argparse
import json
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from trading_desk.strategy.models import StrategyBarResolution
from trading_desk.strategy.validation_cli import (
    INTRADAY_CONTEXT_CONFIGURATION,
    INTRADAY_CONTEXT_WINDOW,
    PAIR_EPICS,
    _costs,
    _strategies,
)
from trading_desk.strategy.validation_runner import (
    CausalContextBuilder,
    HistoricalBar,
    simulate_strategies,
)

YAHOO_URL = "https://query2.finance.yahoo.com/v8/finance/chart/{sym}=X?interval=1h&range=60d"
# Journal exits on/after this cutoff. Set to the deploy month so the first run
# captures the recent window as an initial track; genuinely-forward trades are
# those whose logged_at date is after deployment.
DEPLOY_CUTOFF = datetime(2026, 6, 1, tzinfo=UTC)
HALF_SPREAD_FRACTION = 5e-5  # synth bid/ask (~1 bp); Yahoo is mid-only
PAIRS = ("EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "EURJPY")

MidRow = tuple[datetime, float, float, float, float]


def fetch_hourly_mid(pair: str, *, timeout: float = 25.0) -> list[MidRow]:
    """Fetch ~60 days of hourly mid OHLC for one pair from Yahoo."""

    url = YAHOO_URL.format(sym=pair)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read().decode())
    result = payload["chart"]["result"][0]
    stamps = result["timestamp"]
    quote = result["indicators"]["quote"][0]
    by_ts: dict[datetime, MidRow] = {}
    for i, epoch in enumerate(stamps):
        o, h, lo, c = quote["open"][i], quote["high"][i], quote["low"][i], quote["close"][i]
        if None in (o, h, lo, c) or min(o, h, lo, c) <= 0:
            continue
        ts = datetime.fromtimestamp(epoch, tz=UTC)
        by_ts[ts] = (ts, float(o), float(h), float(lo), float(c))
    return [by_ts[key] for key in sorted(by_ts)]


def to_bars(rows: list[MidRow]) -> tuple[HistoricalBar, ...]:
    """Build bid/ask HistoricalBars from mid rows using a synthetic half-spread."""

    hs = HALF_SPREAD_FRACTION
    bars: list[HistoricalBar] = []
    previous: datetime | None = None
    for ts, o, h, lo, c in rows:
        if previous is not None and ts <= previous:
            continue
        previous = ts
        bars.append(
            HistoricalBar(
                timestamp=ts,
                open_bid=o * (1 - hs),
                open_ask=o * (1 + hs),
                high_bid=h * (1 - hs),
                high_ask=h * (1 + hs),
                low_bid=lo * (1 - hs),
                low_ask=lo * (1 + hs),
                close_bid=c * (1 - hs),
                close_ask=c * (1 + hs),
                volume=0.0,
            )
        )
    return tuple(bars)


def simulate_pair(pair: str) -> tuple[float, int, list[dict[str, str]]]:
    """Return (cumulative net over the window, trade count, journalable rows)."""

    epic, instrument = PAIR_EPICS[pair]
    bars = to_bars(fetch_hourly_mid(pair))
    if len(bars) < INTRADAY_CONTEXT_WINDOW + 50:
        raise ValueError(f"insufficient bars ({len(bars)})")
    builder = CausalContextBuilder(
        epic=epic,
        instrument=instrument,
        resolution=StrategyBarResolution.HOUR,
        strategy_configuration=INTRADAY_CONTEXT_CONFIGURATION,
        window_size=INTRADAY_CONTEXT_WINDOW,
    )
    results = simulate_strategies(
        _strategies(),
        bars,
        builder=builder,
        costs=_costs(),
        evaluation_start=bars[INTRADAY_CONTEXT_WINDOW].timestamp,
        evaluation_end=bars[-1].timestamp,
        trade_prefix=f"{pair}-HOUR-fwd",
    )
    logged_at = datetime.now(tz=UTC).date().isoformat()
    cum_net = 0.0
    count = 0
    journalable: list[dict[str, str]] = []
    for res in results:
        for tr in res.trades:
            count += 1
            cum_net += float(tr.net_pnl)
            if tr.exit_at >= DEPLOY_CUTOFF:
                journalable.append(
                    {
                        "logged_at": logged_at,
                        "pair": pair,
                        "strategy_id": tr.strategy_id,
                        "trade_id": tr.trade_id,
                        "regime": tr.regime,
                        "entry_at": tr.entry_at.isoformat(),
                        "exit_at": tr.exit_at.isoformat(),
                        "gross_pnl": str(tr.gross_pnl),
                        "net_pnl": str(tr.net_pnl),
                    }
                )
    return cum_net, count, journalable


def _natural_key(row: dict[str, str]) -> tuple[str, str, str, str]:
    return (row["pair"], row["strategy_id"], row["entry_at"], row["exit_at"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--shadow-dir", default="data/shadow")
    parser.add_argument("--pairs", nargs="*", default=list(PAIRS))
    args = parser.parse_args(argv)

    shadow = Path(args.shadow_dir)
    shadow.mkdir(parents=True, exist_ok=True)
    journal = shadow / "fx_forward.jsonl"
    seen: set[tuple[str, str, str, str]] = set()
    if journal.exists():
        for line in journal.read_text(encoding="utf-8").splitlines():
            if line.strip():
                seen.add(_natural_key(json.loads(line)))

    appended = 0
    with journal.open("a", encoding="utf-8") as handle:
        for pair in args.pairs:
            try:
                cum_net, count, rows = simulate_pair(pair)
            except Exception as exc:  # noqa: BLE001 - network/thin data -> skip pair
                print(f"{pair}: skipped ({exc})")
                continue
            fresh = [row for row in rows if _natural_key(row) not in seen]
            for row in fresh:
                handle.write(json.dumps(row) + "\n")
                seen.add(_natural_key(row))
            appended += len(fresh)
            print(
                f"{pair}: {count} trades in window, cum_net {cum_net:+.5f}, "
                f"{len(fresh)} new forward rows"
            )
    print(f"appended {appended} new forward trades to {journal}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
