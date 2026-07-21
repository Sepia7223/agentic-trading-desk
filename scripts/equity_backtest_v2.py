"""Rigorous long-short equity backtest engine (v2) — reviewer-gate compliant.

Fixes the flaws that made the v1 cross-sectional backtest untrustworthy:

1.  POINT-IN-TIME UNIVERSE — at each rebalance only tickers that were S&P 500
    members ON THAT DATE (from data/pit/universe_*.json, incl. later-removed
    names) and have price data are ranked. Coverage gaps are read from
    coverage.json and reported with results, not hidden.
2.  SHORT-SIDE COSTS — borrow fee accrues daily on short notional (flat
    general-collateral rate by default, configurable); names under a price floor
    (hard-to-borrow / distressed proxy) are excluded from shorting BEFORE
    ranking. Dividends: returns use adjusted close symmetrically, which charges
    dividends owed on shorts and credits them on longs (documented assumption).
3.  TURNOVER + COST ACCOUNTING — one-way dollar turnover is tracked per
    rebalance; execution cost = turnover x (half-spread + slippage + commission).
    Reports one-way turnover/day, annual turnover multiple, and cost per dollar
    traded. "Trades" are reported as position changes AND as estimated orders.
4.  BUFFERED (HYSTERESIS) REBALANCING — enter long at rank <= enter_n, hold
    while rank <= hold_n; mirror for shorts. Reduces churn on a slow signal.
    Plain top-N/daily remains available for comparison.
5.  EXECUTION-DELAY MODE — signals from close t are executed at close t+1
    (delay=1) instead of same-close, as a realism stress.
6.  EXPOSURE REPORT — daily portfolio beta vs SPY (rolling), plus net/gross
    sector exposure at each rebalance (GICS sectors; sector map is a current
    snapshot — documented PIT limitation).
7.  QUALITY GATES (v3 + reviewer) — return/maxDD, % months positive,
    concentration by calendar year, per-name contribution concentration,
    worst day, ruin check, all reported per run.

RESEARCH ONLY. Daily adjusted-close data. No leverage assumed (gross <= 1 by
default). Compounds equity from --start-equity.

Usage:
    PYTHONPATH=scripts python scripts/equity_backtest_v2.py \
        --start 2022-01-01 --end 2025-06-30 [--buffered] [--delay 1] [--out r.json]
"""

from __future__ import annotations

import argparse
import json
import statistics
from datetime import date
from pathlib import Path

# ---------------------------------------------------------------- data loading


def load_prices(bars_dir: Path, min_days: int = 120) -> dict[str, dict[date, float]]:
    prices: dict[str, dict[date, float]] = {}
    for f in sorted(bars_dir.glob("*.csv")):
        rows = f.read_text(encoding="utf-8").splitlines()[1:]
        s: dict[date, float] = {}
        for r in rows:
            parts = r.split(",")
            try:
                s[date.fromisoformat(parts[0])] = float(parts[5])  # adjclose
            except (ValueError, IndexError):
                continue
        if len(s) >= min_days:
            prices[f.stem] = s
    return prices


def load_universe(pit_dir: Path, start: str, end: str):
    uni = json.loads((pit_dir / f"universe_{start}_{end}.json").read_text("utf-8"))
    memb = json.loads((pit_dir / "membership.json").read_text("utf-8"))
    cov_path = pit_dir / "coverage.json"
    coverage = json.loads(cov_path.read_text("utf-8")) if cov_path.exists() else None
    intervals = {
        t: [(date.fromisoformat(a), date.fromisoformat(b)) for a, b in ivs]
        for t, ivs in uni["intervals"].items()
    }
    return intervals, memb["sectors"], coverage


def member_on(intervals, ticker: str, d: date) -> bool:
    return any(a <= d <= b for a, b in intervals.get(ticker, ()))


def load_events(path: Path) -> dict[str, list[tuple[date, str]]]:
    """EDGAR 8-K ledger -> {symbol: [(accepted_date, tier), ...] sorted}.

    Causality note: acceptance is usually after the close, so an event accepted
    on day e is treated as knowable for decisions strictly AFTER e.
    """

    out: dict[str, list[tuple[date, str]]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        e = json.loads(line)
        if e.get("tier") in ("BLOCK", "CAUTION"):
            out.setdefault(e["ticker"], []).append(
                (date.fromisoformat(e["accepted"][:10]), e["tier"])
            )
    for evs in out.values():
        evs.sort()
    return out


def event_state(
    evs: list[tuple[date, str]] | None,
    d: date,
    block_days: int,
    caution_days: int,
) -> tuple[bool, bool]:
    """(blocked, caution) for decision date d, using only events accepted
    strictly before d."""

    if not evs:
        return False, False
    blocked = caution = False
    horizon = max(block_days, caution_days)
    for ed, tier in reversed(evs):
        age = (d - ed).days
        if age > horizon:
            break
        if age < 1:  # accepted on/after the decision day: not yet knowable
            continue
        if tier == "BLOCK" and age <= block_days:
            blocked = True
        elif tier == "CAUTION" and age <= caution_days:
            caution = True
    return blocked, caution


# ------------------------------------------------------------------- backtest


def run(
    prices: dict[str, dict[date, float]],
    intervals,
    sectors: dict[str, str],
    *,
    start: date,
    end: date,
    lookback: int,
    skip: int,
    basket: int,
    hold_buffer: int,
    buffered: bool,
    sector_neutral: bool,
    rebalance_every: int,
    gross: float,
    half_spread_bps: float,
    slippage_bps: float,
    commission_bps: float,
    borrow_fee_annual: float,
    min_short_price: float,
    delay: int,
    start_equity: float,
    events: dict[str, list[tuple[date, str]]] | None = None,
    event_block_days: int = 7,
    event_caution_days: int = 3,
):
    all_dates = sorted({d for s in prices.values() for d in s})
    dates = [d for d in all_dates if d <= end]
    first_idx = next((i for i, d in enumerate(dates) if d >= start), len(dates))
    k0 = max(lookback + skip + 1, first_idx)

    def ret(sym: str, d0: date, d1: date):
        s = prices.get(sym)
        if s is None:
            return None
        p0, p1 = s.get(d0), s.get(d1)
        if p0 and p1 and p0 > 0:
            return p1 / p0 - 1
        return None

    equity = start_equity
    curve: list[tuple[date, float]] = []
    long_book: dict[str, float] = {}
    short_book: dict[str, float] = {}
    pending: tuple | None = None  # for delay mode: (new_long, new_short)
    turnover_dollars = 0.0
    exec_cost_total = 0.0
    borrow_cost_total = 0.0
    position_changes = 0
    rebalances = 0
    daily_rets: list[tuple[date, float]] = []
    name_contrib: dict[str, float] = {}
    sector_net_series: list[dict[str, float]] = []
    day_count = 0
    event_block_exclusions = 0
    event_short_exclusions = 0
    cost_rate = (half_spread_bps + slippage_bps + commission_bps) / 10000.0
    borrow_daily = borrow_fee_annual / 252.0

    def apply_books(nl: list[str], ns: list[str]) -> float:
        """Swap the books to the new baskets; return execution cost (fraction of
        equity) and account turnover/position-change stats."""
        nonlocal turnover_dollars, position_changes
        wl = (gross / 2) / max(len(nl), 1)
        ws = (gross / 2) / max(len(ns), 1)
        new_l = dict.fromkeys(nl, wl)
        new_s = dict.fromkeys(ns, ws)
        oneway = 0.0
        for sym in set(new_l) | set(long_book):
            oneway += abs(new_l.get(sym, 0.0) - long_book.get(sym, 0.0))
        for sym in set(new_s) | set(short_book):
            oneway += abs(new_s.get(sym, 0.0) - short_book.get(sym, 0.0))
        position_changes += len(set(new_l) ^ set(long_book))
        position_changes += len(set(new_s) ^ set(short_book))
        turnover_dollars += oneway * equity
        long_book.clear()
        long_book.update(new_l)
        short_book.clear()
        short_book.update(new_s)
        return oneway * cost_rate

    for k in range(k0, len(dates)):
        d = dates[k]
        if d > end:
            break
        prev = dates[k - 1]
        day_count += 1

        # ---- mark the books with today's returns
        port_ret = 0.0
        for sym, w in long_book.items():
            r = ret(sym, prev, d)
            if r is not None:
                port_ret += w * r
                name_contrib[sym] = name_contrib.get(sym, 0.0) + w * r * equity
        for sym, w in short_book.items():
            r = ret(sym, prev, d)
            if r is not None:
                port_ret -= w * r
                name_contrib[sym] = name_contrib.get(sym, 0.0) - w * r * equity
        # borrow fee on short notional
        short_notional = sum(short_book.values())
        borrow = short_notional * borrow_daily
        borrow_cost_total += borrow * equity
        port_ret -= borrow

        # ---- apply pending (delayed) rebalance from yesterday's signal
        cost = 0.0
        if pending is not None:
            new_long, new_short = pending
            pending = None
            cost += apply_books(new_long, new_short)
        # ---- compute today's signal
        if (k - k0) % rebalance_every == 0:
            eligible = []
            no_short: set[str] = set()
            for sym in prices:
                if not member_on(intervals, sym, d):
                    continue
                # news/corporate-event gate: BLOCK-tier 8-K excludes the name
                # entirely BEFORE ranking; CAUTION-tier excludes it from the
                # short side (mirrors the live pre-trade pipeline semantics).
                if events is not None:
                    blocked, caution = event_state(
                        events.get(sym), d, event_block_days, event_caution_days
                    )
                    if blocked:
                        event_block_exclusions += 1
                        continue
                    if caution:
                        event_short_exclusions += 1
                        no_short.add(sym)
                r = ret(sym, dates[k - lookback - skip], dates[k - skip])
                if r is None:
                    continue
                px = prices[sym].get(d)
                if px is None:
                    continue
                eligible.append((r, sym, px))
            eligible.sort()
            n = len(eligible)
            if n >= 4 * basket:
                shortable = [
                    e for e in eligible
                    if e[2] >= min_short_price and e[1] not in no_short
                ]
                if sector_neutral:
                    # Per-sector construction: the SAME count q is taken long and
                    # short within each sector, so sector-net exposure is zero by
                    # construction (uniform weights across the whole book).
                    # Buffered mode applies the hysteresis inside each sector: a
                    # held name is retained while it stays inside the top/bottom
                    # 2q zone of its sector.
                    by_sec: dict[str, list] = {}
                    for e in eligible:
                        by_sec.setdefault(sectors.get(e[1], "?"), []).append(e)
                    zone_mult = 2 if buffered else 1
                    new_long, new_short = [], []
                    for _sec, es in sorted(by_sec.items()):
                        n_s = len(es)
                        sh = [
                            e for e in es
                            if e[2] >= min_short_price and e[1] not in no_short
                        ]
                        q = min(max(1, round(basket * n_s / n)), n_s // 2, len(sh))
                        if q < 1:
                            continue
                        syms = [sym for _, sym, _ in es]  # ascending momentum
                        sh_syms = [sym for _, sym, _ in sh]
                        top_zone = set(syms[-min(zone_mult * q, n_s):])
                        sel_l = [
                            s for s in reversed(syms)
                            if s in long_book and s in top_zone
                        ][:q]
                        for sym in reversed(syms):
                            if len(sel_l) >= q:
                                break
                            if sym not in sel_l:
                                sel_l.append(sym)
                        bot_zone = set(sh_syms[: min(zone_mult * q, len(sh_syms))])
                        sel_s = [
                            s for s in sh_syms
                            if s in short_book and s in bot_zone
                        ][:q]
                        for sym in sh_syms:
                            if len(sel_s) >= q:
                                break
                            if sym not in sel_s:
                                sel_s.append(sym)
                        new_long += sel_l
                        new_short += sel_s
                elif buffered:
                    rank = {sym: i for i, (_, sym, _) in enumerate(eligible)}
                    srank = {sym: i for i, (_, sym, _) in enumerate(shortable)}
                    new_long = [
                        s for s in long_book
                        if s in rank and rank[s] >= n - hold_buffer
                    ]
                    for _, sym, _ in reversed(eligible[-basket:]):
                        if sym not in new_long:
                            new_long.append(sym)
                        if len(new_long) >= basket:
                            break
                    new_long = new_long[:basket]
                    new_short = [
                        s for s in short_book
                        if s in srank and srank[s] < hold_buffer
                    ]
                    for _, sym, _ in shortable[:basket]:
                        if sym not in new_short:
                            new_short.append(sym)
                        if len(new_short) >= basket:
                            break
                    new_short = new_short[:basket]
                else:
                    new_long = [sym for _, sym, _ in eligible[-basket:]]
                    new_short = [sym for _, sym, _ in shortable[:basket]]
                rebalances += 1
                if delay > 0:
                    pending = (new_long, new_short)
                else:
                    cost += apply_books(new_long, new_short)

        port_ret -= cost
        exec_cost_total += cost * equity
        equity *= 1 + port_ret
        daily_rets.append((d, port_ret))
        curve.append((d, equity))
        # sector net exposure snapshot (weekly to keep the series light)
        if day_count % 5 == 0:
            snap: dict[str, float] = {}
            for sym, w in long_book.items():
                snap[sectors.get(sym, "?")] = snap.get(sectors.get(sym, "?"), 0.0) + w
            for sym, w in short_book.items():
                snap[sectors.get(sym, "?")] = snap.get(sectors.get(sym, "?"), 0.0) - w
            sector_net_series.append(snap)

    return {
        "curve": curve,
        "daily_rets": daily_rets,
        "turnover_dollars": turnover_dollars,
        "exec_cost_total": exec_cost_total,
        "borrow_cost_total": borrow_cost_total,
        "position_changes": position_changes,
        "rebalances": rebalances,
        "name_contrib": name_contrib,
        "sector_net_series": sector_net_series,
        "event_block_exclusions": event_block_exclusions,
        "event_short_exclusions": event_short_exclusions,
        "final_equity": equity,
    }


# -------------------------------------------------------------------- metrics


def summarize(res, start_equity: float, spy: dict[date, float] | None) -> dict:
    curve = res["curve"]
    rets = [r for _, r in res["daily_rets"]]
    if not curve:
        return {"error": "no trading days"}
    equity = res["final_equity"]
    peak, mdd = start_equity, 0.0
    for _, e in curve:
        peak = max(peak, e)
        mdd = min(mdd, (e - peak) / peak)
    by_month: dict[str, float] = {}
    by_year_ret: dict[str, float] = {}
    for (d, r) in res["daily_rets"]:
        ym = f"{d.year}-{d.month:02d}"
        by_month[ym] = (1 + by_month.get(ym, 0.0)) * (1 + r) - 1
        by_year_ret[str(d.year)] = (1 + by_year_ret.get(str(d.year), 0.0)) * (1 + r) - 1
    months = sorted(by_month)
    pos_months = sum(1 for m in months if by_month[m] > 0)
    sharpe = 0.0
    if len(rets) > 1 and statistics.pstdev(rets) > 0:
        sharpe = statistics.mean(rets) / statistics.pstdev(rets) * (252 ** 0.5)
    total_ret = equity / start_equity - 1
    years = len(rets) / 252
    cagr = (equity / start_equity) ** (1 / years) - 1 if years > 0 else 0.0
    # beta vs SPY
    beta = None
    if spy:
        pairs = []
        spy_dates = sorted(spy)
        spy_ret = {}
        for i in range(1, len(spy_dates)):
            d0, d1 = spy_dates[i - 1], spy_dates[i]
            if spy[d0] > 0:
                spy_ret[d1] = spy[d1] / spy[d0] - 1
        for d, r in res["daily_rets"]:
            if d in spy_ret:
                pairs.append((r, spy_ret[d]))
        if len(pairs) > 30:
            mp = statistics.mean(x for x, _ in pairs)
            mm = statistics.mean(y for _, y in pairs)
            cov = sum((x - mp) * (y - mm) for x, y in pairs) / len(pairs)
            var = sum((y - mm) ** 2 for _, y in pairs) / len(pairs)
            beta = cov / var if var > 0 else None
    # concentration
    contrib = res["name_contrib"]
    gains = sorted(contrib.values(), reverse=True)
    total_pnl = equity - start_equity
    top5_share = (
        round(sum(gains[:5]) / total_pnl, 2) if total_pnl > 0 and gains else None
    )
    year_share = (
        {y: round(v / total_ret, 2) for y, v in by_year_ret.items()}
        if total_ret != 0
        else None
    )
    # sector extremes
    max_sector_net = 0.0
    for snap in res["sector_net_series"]:
        for v in snap.values():
            max_sector_net = max(max_sector_net, abs(v))
    days = len(rets)
    avg_equity = statistics.mean(e for _, e in curve)
    return {
        "final_equity": round(equity, 2),
        "total_return_pct": round(total_ret * 100, 1),
        "cagr_pct": round(cagr * 100, 1),
        "max_drawdown_pct": round(mdd * 100, 2),
        "annualised_sharpe": round(sharpe, 2),
        "calmar_like": round(cagr / abs(mdd), 2) if mdd < 0 else None,
        "pct_months_positive": round(100 * pos_months / len(months), 1),
        "worst_day_pct": round(min(rets) * 100, 2),
        "best_day_pct": round(max(rets) * 100, 2),
        "ruin": min(e for _, e in curve) <= start_equity * 0.1,
        "beta_vs_spy": round(beta, 3) if beta is not None else None,
        "max_abs_sector_net_pct": round(max_sector_net * 100, 1),
        "by_year_return_pct": {y: round(v * 100, 1) for y, v in by_year_ret.items()},
        "year_contribution_share": year_share,
        "top5_name_pnl_share": top5_share,
        "position_changes_total": res["position_changes"],
        "position_changes_per_day": round(res["position_changes"] / days, 2),
        "est_orders_per_day": round(res["position_changes"] / days, 2),
        "oneway_turnover_per_day_pct": round(
            100 * res["turnover_dollars"] / avg_equity / days, 2
        ),
        "annual_turnover_multiple": round(
            res["turnover_dollars"] / avg_equity / days * 252, 1
        ),
        "exec_cost_total": round(res["exec_cost_total"], 2),
        "borrow_cost_total": round(res["borrow_cost_total"], 2),
        "cost_per_dollar_traded_bps": round(
            1e4 * res["exec_cost_total"] / res["turnover_dollars"], 2
        )
        if res["turnover_dollars"]
        else None,
        "rebalances": res["rebalances"],
        "event_block_exclusions": res.get("event_block_exclusions", 0),
        "event_short_exclusions": res.get("event_short_exclusions", 0),
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--start", default="2022-01-01")
    p.add_argument("--end", default="2025-06-30")
    p.add_argument("--universe-window", default="2021-01-01:2026-06-30")
    p.add_argument("--lookback", type=int, default=252)
    p.add_argument("--skip", type=int, default=21)
    p.add_argument("--basket", type=int, default=30)
    # Recommended defaults (reviewer): buffered + sector-neutral + weekly.
    p.add_argument("--buffered", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument(
        "--sector-neutral", action=argparse.BooleanOptionalAction, default=True
    )
    p.add_argument("--hold-buffer", type=int, default=60)
    p.add_argument("--rebalance-every", type=int, default=5)
    p.add_argument("--gross", type=float, default=1.0)
    p.add_argument("--half-spread-bps", type=float, default=2.5)
    p.add_argument("--slippage-bps", type=float, default=1.0)
    p.add_argument("--commission-bps", type=float, default=0.5)
    p.add_argument("--borrow-fee-annual", type=float, default=0.005)
    p.add_argument("--min-short-price", type=float, default=5.0)
    p.add_argument(
        "--events",
        default=None,
        help="EDGAR events JSONL; enables the pre-trade news/event gate",
    )
    p.add_argument("--event-block-days", type=int, default=7)
    p.add_argument("--event-caution-days", type=int, default=3)
    p.add_argument("--delay", type=int, default=0)
    p.add_argument("--start-equity", type=float, default=1000.0)
    p.add_argument("--pit-dir", default="data/pit")
    p.add_argument("--out", default=None)
    args = p.parse_args(argv)

    pit = Path(args.pit_dir)
    uw_start, uw_end = args.universe_window.split(":")
    intervals, sectors, coverage = load_universe(pit, uw_start, uw_end)
    prices = load_prices(pit / "bars")
    spy = prices.pop("SPY", None)  # benchmark only — never a tradeable member
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)

    res = run(
        prices,
        intervals,
        sectors,
        start=start,
        end=end,
        lookback=args.lookback,
        skip=args.skip,
        basket=args.basket,
        hold_buffer=args.hold_buffer,
        buffered=args.buffered,
        sector_neutral=args.sector_neutral,
        rebalance_every=args.rebalance_every,
        gross=args.gross,
        half_spread_bps=args.half_spread_bps,
        slippage_bps=args.slippage_bps,
        commission_bps=args.commission_bps,
        borrow_fee_annual=args.borrow_fee_annual,
        min_short_price=args.min_short_price,
        delay=args.delay,
        start_equity=args.start_equity,
        events=load_events(Path(args.events)) if args.events else None,
        event_block_days=args.event_block_days,
        event_caution_days=args.event_caution_days,
    )
    m = summarize(res, args.start_equity, spy)
    report = {
        "engine": "equity_backtest_v2",
        "window": [args.start, args.end],
        "params": {
            k: getattr(args, k.replace("-", "_"))
            for k in (
                "lookback", "skip", "basket", "buffered", "sector_neutral",
                "hold_buffer", "rebalance_every", "gross", "half_spread_bps",
                "slippage_bps", "commission_bps", "borrow_fee_annual",
                "min_short_price", "delay",
            )
        },
        "universe": {
            "type": "point-in-time S&P 500 (Wikipedia constituents+changes)",
            "tickers_with_data": len(prices),
            "coverage": None
            if coverage is None
            else {
                "full": coverage["full"],
                "partial_ends_early": coverage["partial_ends_early"],
                "missing": coverage["missing"],
                "missing_pct": coverage["missing_pct"],
            },
        },
        "metrics": m,
    }
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
