"""Governed historical dataset acquisition for Milestone 12 strategy validation.

Downloads public Dukascopy candle archives for the governed six-market FOREX
universe, decodes them locally, and writes bid/ask OHLC bar files in the exact
schema required by ``trading_desk.backtest.data.load_dataset``.

Sources per output series (documented in the committed dataset manifest):

- ``HOUR``      — native hourly candles (one archive per month and side).
- ``DAY``       — native daily candles (one archive per year and side).
- ``MINUTE_15`` and ``MINUTE_5`` — aggregated from one-minute candles
  (one archive per day and side); minute coverage may start later than the
  hourly coverage and is recorded in the download summary.

The script is read-only with respect to the trading system: it has no broker,
credential, journal, risk, or execution dependency. Raw archives and derived
bar files live under the local (gitignored) data directory; the committed
dataset manifest references them by SHA-256 fingerprint only.

Bi5 payloads are LZMA streams of big-endian 24-byte records:
``offset_seconds, open, close, low, high (scaled integers), volume (float32)``.
Offsets are relative to the archive period start (day, month, or year).
Prices are scaled by 1e5 except JPY-quoted pairs which use 1e3. The URL month
component is zero-based. The public server throttles aggressive clients, so
requests are paced through a small number of persistent connections with
bounded retries and an optional availability probe.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import lzma
import struct
import sys
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx

BASE_URL = "https://datafeed.dukascopy.com/datafeed"
SIDES = ("BID", "ASK")
RECORD = struct.Struct(">iiiiif")

PAIR_EPICS: dict[str, str] = {
    "EURUSD": "CS.D.EURUSD.CFD.IP",
    "GBPUSD": "CS.D.GBPUSD.CFD.IP",
    "USDJPY": "CS.D.USDJPY.CFD.IP",
    "AUDUSD": "CS.D.AUDUSD.CFD.IP",
    "USDCAD": "CS.D.USDCAD.CFD.IP",
    "EURJPY": "CS.D.EURJPY.CFD.IP",
}
JPY_QUOTED = {"USDJPY", "EURJPY"}

MINUTE_AGGREGATIONS: dict[str, int] = {
    "MINUTE_5": 300,
    "MINUTE_15": 900,
}

CSV_COLUMNS = (
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
    "last_traded_volume",
)


@dataclass(frozen=True)
class Candle:
    start: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


def decode_bi5(payload: bytes, scale: float, period_start: datetime) -> tuple[Candle, ...]:
    """Decode one archive; zero-tick filler records are excluded.

    Dukascopy pads closed-market periods (weekends, holidays) with flat
    records carrying zero volume and zero range. Live broker feeds print no
    bars for closed markets, so those records are dropped to preserve
    live parity: a record survives only if it shows a price range or volume.
    """

    if not payload:
        return ()
    raw = lzma.decompress(payload)
    if len(raw) % RECORD.size:
        raise ValueError("bi5 payload is not a whole number of records")
    candles: list[Candle] = []
    for offset in range(0, len(raw), RECORD.size):
        seconds, open_, close, low, high, volume = RECORD.unpack_from(raw, offset)
        if open_ <= 0 or close <= 0 or low <= 0 or high <= 0:
            continue
        if volume == 0 and high == low:
            continue
        candles.append(
            Candle(
                start=period_start + timedelta(seconds=seconds),
                open=open_ / scale,
                high=high / scale,
                low=low / scale,
                close=close / scale,
                volume=float(volume),
            )
        )
    return tuple(candles)


@dataclass(frozen=True)
class FetchItem:
    url: str
    target: Path


class PacedFetcher:
    """Small-footprint downloader: few persistent connections, paced requests."""

    def __init__(self, concurrency: int, request_delay: float) -> None:
        self.concurrency = concurrency
        self.request_delay = request_delay
        self.counts = {"cached": 0, "downloaded": 0, "empty": 0, "missing": 0, "failed": 0}

    async def fetch_all(self, items: list[FetchItem], label: str) -> None:
        pending = [item for item in items if not item.target.exists()]
        self.counts["cached"] += len(items) - len(pending)
        if not pending:
            print(f"{label}: all {len(items)} archives cached", flush=True)
            return
        queue: asyncio.Queue[FetchItem] = asyncio.Queue()
        for item in pending:
            queue.put_nowait(item)
        timeout = httpx.Timeout(90.0, connect=60.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            workers = [
                asyncio.create_task(self._worker(client, queue)) for _ in range(self.concurrency)
            ]
            total = len(pending)
            while any(not worker.done() for worker in workers):
                await asyncio.sleep(15)
                done = total - queue.qsize()
                print(f"{label}: ~{done}/{total} ({self.counts})", flush=True)
            for worker in workers:
                await worker
        print(f"{label}: complete ({self.counts})", flush=True)

    async def _worker(self, client: httpx.AsyncClient, queue: asyncio.Queue[FetchItem]) -> None:
        while True:
            try:
                item = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            await self._fetch_one(client, item)
            if self.request_delay:
                await asyncio.sleep(self.request_delay)

    async def _fetch_one(self, client: httpx.AsyncClient, item: FetchItem) -> None:
        for attempt in range(6):
            try:
                response = await client.get(item.url)
            except httpx.HTTPError:
                await asyncio.sleep(min(120.0, 5.0 * 2**attempt))
                continue
            if response.status_code == 404:
                self.counts["missing"] += 1
                return
            if response.status_code == 200:
                if not response.content:
                    self.counts["empty"] += 1
                    return
                item.target.parent.mkdir(parents=True, exist_ok=True)
                item.target.write_bytes(response.content)
                self.counts["downloaded"] += 1
                return
            await asyncio.sleep(min(120.0, 5.0 * 2**attempt))
        self.counts["failed"] += 1


def month_range(start: date, end: date) -> tuple[tuple[int, int], ...]:
    months = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        months.append((year, month))
        month += 1
        if month == 13:
            year, month = year + 1, 1
    return tuple(months)


def build_items(
    pair: str, root: Path, start: date, end: date, minute_start: date
) -> tuple[list[FetchItem], list[FetchItem], list[FetchItem]]:
    hourly = [
        FetchItem(
            url=f"{BASE_URL}/{pair}/{year}/{month - 1:02d}/{side}_candles_hour_1.bi5",
            target=root / "raw" / pair / "hour" / f"{year}-{month:02d}_{side}.bi5",
        )
        for year, month in month_range(start, end)
        for side in SIDES
    ]
    daily = [
        FetchItem(
            url=f"{BASE_URL}/{pair}/{year}/{side}_candles_day_1.bi5",
            target=root / "raw" / pair / "day" / f"{year}_{side}.bi5",
        )
        for year in range(start.year, end.year + 1)
        for side in SIDES
    ]
    minute = [
        FetchItem(
            url=(
                f"{BASE_URL}/{pair}/{day.year}/{day.month - 1:02d}/{day.day:02d}/"
                f"{side}_candles_min_1.bi5"
            ),
            target=root / "raw" / pair / f"{day.isoformat()}_{side}.bi5",
        )
        for day in (
            minute_start + timedelta(days=index) for index in range((end - minute_start).days + 1)
        )
        for side in SIDES
    ]
    return hourly, daily, minute


def _load_side(path: Path, scale: float, period_start: datetime) -> dict[datetime, Candle]:
    if not path.exists():
        return {}
    try:
        return {
            candle.start: candle for candle in decode_bi5(path.read_bytes(), scale, period_start)
        }
    except (lzma.LZMAError, ValueError):
        return {}


def _write_csv(
    root: Path,
    pair: str,
    series: str,
    rows: list[tuple[datetime, Candle, Candle]],
    decimals: int,
) -> dict[str, object]:
    epic = PAIR_EPICS[pair]
    path = root / "bars" / f"{pair}_{series}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    dropped = 0
    written = 0
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(CSV_COLUMNS)
        for start, bid, ask in rows:
            prices = {
                "open_bid": bid.open,
                "open_ask": ask.open,
                "high_bid": bid.high,
                "high_ask": ask.high,
                "low_bid": bid.low,
                "low_ask": ask.low,
                "close_bid": bid.close,
                "close_ask": ask.close,
            }
            if any(
                prices[f"{field}_bid"] > prices[f"{field}_ask"]
                for field in ("open", "high", "low", "close")
            ):
                dropped += 1
                continue
            writer.writerow(
                [
                    epic,
                    start.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
                    *(f"{prices[column]:.{decimals}f}" for column in CSV_COLUMNS[2:10]),
                    f"{bid.volume:.2f}",
                ]
            )
            written += 1
    return {
        "path": str(path.relative_to(root)),
        "bar_count": written,
        "dropped_crossed_bars": dropped,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def aggregate_native(
    pair: str,
    root: Path,
    series: str,
    archives: tuple[tuple[Path, Path, datetime], ...],
    *,
    skip_weekend_days: bool,
) -> dict[str, object]:
    """HOUR/DAY series from native candles: join bid and ask per start time."""

    scale = 1e3 if pair in JPY_QUOTED else 1e5
    decimals = 3 if pair in JPY_QUOTED else 5
    rows: list[tuple[datetime, Candle, Candle]] = []
    for bid_path, ask_path, period_start in archives:
        bid = _load_side(bid_path, scale, period_start)
        ask = _load_side(ask_path, scale, period_start)
        for start in sorted(set(bid) & set(ask)):
            if skip_weekend_days and start.weekday() in (5, 6):
                continue
            rows.append((start, bid[start], ask[start]))
    rows.sort(key=lambda item: item[0])
    return _write_csv(root, pair, series, rows, decimals)


def aggregate_minutes(
    pair: str, root: Path, minute_start: date, end: date
) -> dict[str, dict[str, object]]:
    scale = 1e3 if pair in JPY_QUOTED else 1e5
    decimals = 3 if pair in JPY_QUOTED else 5
    buckets: dict[str, dict[datetime, list[tuple[Candle, Candle]]]] = {
        name: {} for name in MINUTE_AGGREGATIONS
    }
    days_with_data = 0
    minutes_used = 0
    for index in range((end - minute_start).days + 1):
        day = minute_start + timedelta(days=index)
        period_start = datetime(day.year, day.month, day.day, tzinfo=UTC)
        bid = _load_side(root / "raw" / pair / f"{day.isoformat()}_BID.bi5", scale, period_start)
        ask = _load_side(root / "raw" / pair / f"{day.isoformat()}_ASK.bi5", scale, period_start)
        shared = sorted(set(bid) & set(ask))
        if not shared:
            continue
        days_with_data += 1
        minutes_used += len(shared)
        for start in shared:
            for name, seconds in MINUTE_AGGREGATIONS.items():
                epoch = int(start.timestamp())
                window = datetime.fromtimestamp(epoch - epoch % seconds, tz=UTC)
                buckets[name].setdefault(window, []).append((bid[start], ask[start]))
    outputs: dict[str, dict[str, object]] = {}
    for name in MINUTE_AGGREGATIONS:
        rows: list[tuple[datetime, Candle, Candle]] = []
        for window, pairs in sorted(buckets[name].items()):
            bid_candle = Candle(
                start=window,
                open=pairs[0][0].open,
                high=max(item[0].high for item in pairs),
                low=min(item[0].low for item in pairs),
                close=pairs[-1][0].close,
                volume=sum(item[0].volume for item in pairs),
            )
            ask_candle = Candle(
                start=window,
                open=pairs[0][1].open,
                high=max(item[1].high for item in pairs),
                low=min(item[1].low for item in pairs),
                close=pairs[-1][1].close,
                volume=sum(item[1].volume for item in pairs),
            )
            rows.append((window, bid_candle, ask_candle))
        outputs[name] = _write_csv(root, pair, name, rows, decimals)
    outputs["_minute_coverage"] = {
        "days_with_data": days_with_data,
        "minutes_used": minutes_used,
        "minute_start": minute_start.isoformat(),
    }
    return outputs


def wait_until_available(probe_url: str, poll_seconds: int) -> None:
    while True:
        try:
            response = httpx.get(probe_url, timeout=30.0, follow_redirects=False)
            if response.status_code in (200, 404):
                print("datafeed reachable", flush=True)
                return
            print(f"probe status {response.status_code}; waiting", flush=True)
        except httpx.HTTPError as error:
            print(f"probe failed ({type(error).__name__}); waiting", flush=True)
        time.sleep(poll_seconds)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", default="data/validation")
    parser.add_argument("--start", default="2019-01-01")
    parser.add_argument("--end", default="2026-06-30")
    parser.add_argument(
        "--minute-start",
        default="2021-11-01",
        help="First day of one-minute coverage (15m/5m series)",
    )
    parser.add_argument("--pairs", nargs="*", default=sorted(PAIR_EPICS))
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--request-delay", type=float, default=0.25)
    parser.add_argument("--skip-download", action="store_true")
    parser.add_argument(
        "--skip-minute",
        action="store_true",
        help="Fetch and aggregate only the native hourly and daily series",
    )
    parser.add_argument("--wait-for-availability", action="store_true")
    parser.add_argument("--probe-poll-seconds", type=int, default=120)
    args = parser.parse_args()

    for pair in args.pairs:
        if pair not in PAIR_EPICS:
            print(f"unknown pair: {pair}", file=sys.stderr)
            return 2
    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    minute_start = date.fromisoformat(args.minute_start)
    if not start <= minute_start <= end:
        print("minute-start must lie within start..end", file=sys.stderr)
        return 2
    root = Path(args.output_root)
    root.mkdir(parents=True, exist_ok=True)

    if args.wait_for_availability and not args.skip_download:
        wait_until_available(
            f"{BASE_URL}/EURUSD/{start.year}/{start.month - 1:02d}/BID_candles_hour_1.bi5",
            args.probe_poll_seconds,
        )

    summary: dict[str, object] = {
        "source": "Dukascopy Bank SA public datafeed (bid and ask candles)",
        "base_url": BASE_URL,
        "retrieved_at": datetime.now(tz=UTC).isoformat(),
        "coverage_start": start.isoformat(),
        "coverage_end": end.isoformat(),
        "minute_coverage_start": minute_start.isoformat(),
        "timezone": "UTC",
        "series_provenance": {
            "HOUR": "native hourly candles (monthly archives)",
            "DAY": "native daily candles (yearly archives), UTC weekend days excluded",
            "MINUTE_15": "aggregated from one-minute candles (daily archives)",
            "MINUTE_5": "aggregated from one-minute candles (daily archives)",
        },
        "pairs": {},
    }
    for pair in args.pairs:
        hourly, daily, minute = build_items(pair, root, start, end, minute_start)
        fetcher = PacedFetcher(args.concurrency, args.request_delay)
        if not args.skip_download:
            asyncio.run(fetcher.fetch_all(daily, f"{pair} daily"))
            asyncio.run(fetcher.fetch_all(hourly, f"{pair} hourly"))
            if not args.skip_minute:
                asyncio.run(fetcher.fetch_all(minute, f"{pair} minute"))
            if fetcher.counts["failed"]:
                print(f"{pair}: {fetcher.counts['failed']} archives failed", file=sys.stderr)
        print(f"{pair}: aggregating", flush=True)
        hour_output = aggregate_native(
            pair,
            root,
            "HOUR",
            tuple(
                (
                    root / "raw" / pair / "hour" / f"{year}-{month:02d}_BID.bi5",
                    root / "raw" / pair / "hour" / f"{year}-{month:02d}_ASK.bi5",
                    datetime(year, month, 1, tzinfo=UTC),
                )
                for year, month in month_range(start, end)
            ),
            skip_weekend_days=False,
        )
        day_output = aggregate_native(
            pair,
            root,
            "DAY",
            tuple(
                (
                    root / "raw" / pair / "day" / f"{year}_BID.bi5",
                    root / "raw" / pair / "day" / f"{year}_ASK.bi5",
                    datetime(year, 1, 1, tzinfo=UTC),
                )
                for year in range(start.year, end.year + 1)
            ),
            skip_weekend_days=True,
        )
        minute_outputs = (
            {} if args.skip_minute else aggregate_minutes(pair, root, minute_start, end)
        )
        summary["pairs"] = {
            **summary["pairs"],  # type: ignore[dict-item]
            pair: {
                "download": dict(fetcher.counts),
                "bars": {
                    "HOUR": hour_output,
                    "DAY": day_output,
                    **minute_outputs,
                },
            },
        }
        print(f"{pair}: aggregation complete", flush=True)

    summary_path = root / "download_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"summary written: {summary_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
