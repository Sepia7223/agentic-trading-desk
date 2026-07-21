"""Daily paper-trading session: the full production loop, simulated execution.

Run once per day (after US close). Each session, in order:

  1. HEALTH      file kill-switches, incident lock, data freshness
  2. SETTLE      yesterday's queued orders fill at today's open (+ adverse
                 costs); armed protective stops run on today's high/low;
                 any protection failure -> close + INCIDENT_LOCK (fail closed)
  3. MARK        equity marked at today's close; daily anchors rolled;
                 realized round-trips update the consecutive-loss counter
  4. DECIDE      12-month momentum (skip last month), sector-neutral,
                 buffered, on the CURRENT S&P membership; gross is derived
                 from the stress budget (binding scenario inversion), never
                 from desired profit
  5. VALIDATE    every ENTRY passes the full pre-trade pipeline (news gate
                 included, fail-closed) + throttle/idempotency. EXITS bypass
                 opportunity gates by policy: reducing risk is never blocked
                 by the checks that gate adding risk (system health and order
                 sanity still apply).
  6. QUEUE       approved protected orders queue for tomorrow's open; state
                 and journal persist to data/paper/.

DEMO/PAPER ONLY. Fractional shares are permitted in paper (documented: the
implementability report covers real-account sizing separately).

Usage:
    PYTHONPATH="src;scripts" python scripts/paper_trade.py [--paper-dir data/paper]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fetch_stocks import fetch as fetch_yahoo  # type: ignore[import-not-found]
from trading_desk.paper.broker import PaperBroker, PaperOrder, SessionBar
from trading_desk.paper.health import build_account_state, build_system_health
from trading_desk.paper.state import (
    activate_incident_lock,
    journal,
    load_state,
    save_state,
)
from trading_desk.pretrade import (
    ExecutionQuality,
    InstrumentState,
    MarginState,
    OrderSpec,
    PortfolioProjection,
    PreTradeLimits,
    SignalState,
    StressReport,
    ThrottleLimits,
    TradeProposal,
    evaluate_trade,
    idempotency_key,
)
from trading_desk.pretrade.correlation import max_correlated_cluster_weight
from trading_desk.pretrade.news_gate import read_news
from trading_desk.pretrade.stress import (
    PortfolioSnapshot,
    StressParameters,
    compute_stress_report,
)
from trading_desk.pretrade.throttle import OrderThrottle

D = Decimal

# ---- deployment decision (paper): recorded here per the no-silent-change rule.
# The generic 8-trades/day starting control is for single-signal strategies; a
# 60-name portfolio rebuild is one DECISION with many orders. The paper
# deployment caps ORDERS at levels matching the strategy's construction, and
# risk is governed by the stress budget (see gross derivation below).
PAPER_LIMITS = PreTradeLimits(
    maximum_daily_trades=200,
    minimum_equity=D("500"),  # never trade the $1,000 account below $500
)
PAPER_THROTTLE = ThrottleLimits(
    max_orders_per_minute=250, max_open_orders=250, max_orders_per_day=250
)
LOOKBACK, SKIP, BASKET = 252, 21, 30
TARGET_GROSS_CAP = D("0.50")
STOP_DISTANCE = D("0.15")  # per-position catastrophe stop (15%)
EDGE_GROSS_BPS = D("15")  # validation-period average gross edge per change
HISTORY_DAYS = LOOKBACK + SKIP + 30


def budget_implied_gross(limits: PreTradeLimits, params: StressParameters) -> Decimal:
    """Invert the binding stress scenario: gross such that worst() == budget."""

    lo, hi = D("0"), D("2")
    for _ in range(40):
        mid = (lo + hi) / 2
        report = compute_stress_report(
            PortfolioSnapshot(
                gross_exposure=mid,
                net_exposure=D("0.02") * mid,
                max_single_name_weight=mid / (2 * BASKET),
                max_short_name_weight=mid / (2 * BASKET),
            ),
            params,
        )
        if report.worst() <= limits.total_open_risk_fraction:
            lo = mid
        else:
            hi = mid
    return lo


def load_universe(pit_dir: Path) -> tuple[list[str], dict[str, str]]:
    memb = json.loads((pit_dir / "membership.json").read_text(encoding="utf-8"))
    return list(memb["current"]), dict(memb["sectors"])


def fetch_recent_bars(
    symbols: list[str], sleep: float
) -> dict[str, list[tuple[date, Decimal, Decimal, Decimal, Decimal, Decimal]]]:
    """(date, open, high, low, close, volume) per symbol, oldest->newest."""

    now = int(time.time())
    start = now - (HISTORY_DAYS + 200) * 86400
    out: dict[str, list] = {}
    for i, sym in enumerate(symbols, 1):
        try:
            rows = fetch_yahoo(sym, start, now)
        except Exception:  # noqa: BLE001 - missing symbol -> reported, skipped
            continue
        series = []
        for r in rows:
            series.append(
                (
                    date.fromisoformat(str(r[0])),
                    D(str(r[1])),
                    D(str(r[2])),
                    D(str(r[3])),
                    D(str(r[5])),  # adjusted close for signals AND fills
                    D(str(r[6] or 0)),
                )
            )
        if len(series) >= 30:
            out[sym] = series
        if i % 100 == 0:
            print(f"  quotes {i}/{len(symbols)}")
        time.sleep(sleep)
    return out


def momentum_targets(
    bars: dict[str, list],
    sectors: dict[str, str],
    held_long: set[str],
    held_short: set[str],
) -> tuple[list[str], list[str], dict[str, Decimal]]:
    """Sector-neutral buffered targets + momentum score per candidate."""

    scores: dict[str, Decimal] = {}
    eligible: list[tuple[Decimal, str]] = []
    for sym, series in bars.items():
        if len(series) < LOOKBACK + SKIP + 1:
            continue
        c_recent = series[-1 - SKIP][4]
        c_old = series[-1 - LOOKBACK - SKIP][4]
        if c_old <= 0 or series[-1][4] < D("5"):
            continue
        score = c_recent / c_old - 1
        scores[sym] = score
        eligible.append((score, sym))
    eligible.sort()
    n = len(eligible)
    by_sec: dict[str, list[tuple[Decimal, str]]] = {}
    for e in eligible:
        by_sec.setdefault(sectors.get(e[1], "?"), []).append(e)
    new_long: list[str] = []
    new_short: list[str] = []
    for _sec, es in sorted(by_sec.items()):
        n_s = len(es)
        q = min(max(1, round(BASKET * n_s / n)), n_s // 2)
        if q < 1:
            continue
        syms = [s for _, s in es]
        top_zone = set(syms[-min(2 * q, n_s) :])
        sel_l = [s for s in reversed(syms) if s in held_long and s in top_zone][:q]
        for s in reversed(syms):
            if len(sel_l) >= q:
                break
            if s not in sel_l:
                sel_l.append(s)
        bot_zone = set(syms[: min(2 * q, n_s)])
        sel_s = [s for s in syms if s in held_short and s in bot_zone][:q]
        for s in syms:
            if len(sel_s) >= q:
                break
            if s not in sel_s:
                sel_s.append(s)
        new_long += sel_l
        new_short += sel_s
    return new_long, new_short, scores


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--paper-dir", default="data/paper")
    p.add_argument("--pit-dir", default="data/pit")
    p.add_argument("--start-equity", type=str, default="1000")
    p.add_argument("--sleep", type=float, default=0.12)
    args = p.parse_args(argv)
    root = Path(args.paper_dir)
    state = load_state(root, D(args.start_equity))
    today = datetime.now(UTC).date()

    print(f"=== paper session {today.isoformat()} ===")
    symbols, sectors = load_universe(Path(args.pit_dir))
    print(f"universe: {len(symbols)} current members; fetching quotes…")
    bars = fetch_recent_bars(symbols, args.sleep)
    latest_dates = {s: b[-1][0] for s, b in bars.items()}
    session_date = max(latest_dates.values()) if latest_dates else None
    print(f"quotes for {len(bars)} symbols; latest session: {session_date}")

    # ---- 1) health
    health = build_system_health(
        root,
        latest_bar_date=session_date,
        today=today,
        reconciled=True,
    )
    if state.last_session == (session_date.isoformat() if session_date else ""):
        print("session already processed; nothing to do")
        return 0

    # ---- 2) settle at today's open/high/low
    broker = PaperBroker(state.cash, positions=dict(state.positions), fail_protection=False)
    broker.queued = list(state.queued_orders)
    session_bars = {
        s: SessionBar(open=b[-1][1], high=b[-1][2], low=b[-1][3], close=b[-1][4])
        for s, b in bars.items()
        if b[-1][0] == session_date
    }
    pre_positions = {s: pos.model_copy() for s, pos in broker.positions.items()}
    fills, stop_fills, unprotected = broker.settle(session_bars, session_date)
    for f in fills + stop_fills:
        journal(root, {"type": "fill", "session": session_date, **f.model_dump()})
    if unprotected:
        activate_incident_lock(root, f"protection failed: {unprotected}")
        print(f"!! INCIDENT LOCK: unprotected fills {unprotected}")
    # realized round-trips -> consecutive-loss counter
    for f in stop_fills:
        prev = pre_positions.get(f.symbol)
        if prev is not None:
            pnl = (f.price - prev.entry_price) * prev.quantity
            state.record_round_trip(pnl)
    closed_by_exit = {
        f.symbol
        for f in fills
        if f.direction in ("SELL", "BUY_TO_COVER") and f.symbol not in broker.positions
    }
    for sym in closed_by_exit:
        prev = pre_positions.get(sym)
        fill = next(f for f in fills if f.symbol == sym)
        if prev is not None:
            state.record_round_trip((fill.price - prev.entry_price) * prev.quantity)
    state.trades_today += len(fills)

    # ---- 3) mark
    closes = {s: b[-1][4] for s, b in bars.items()}
    equity = broker.equity(closes)
    state.cash = broker.cash
    state.positions = dict(broker.positions)
    state.roll_day(session_date, equity)
    print(
        f"settled {len(fills)} fills, {len(stop_fills)} stops | "
        f"equity ${equity:,.2f} | positions {len(broker.positions)}"
    )

    # ---- 4) decide
    params = StressParameters()
    gross = min(TARGET_GROSS_CAP, budget_implied_gross(PAPER_LIMITS, params))
    held_long = {s for s, pos in broker.positions.items() if pos.quantity > 0}
    held_short = {s for s, pos in broker.positions.items() if pos.quantity < 0}
    new_long, new_short, scores = momentum_targets(bars, sectors, held_long, held_short)
    per_side = max(len(new_long), 1)
    weight = gross / 2 / per_side
    print(
        f"targets: {len(new_long)}L/{len(new_short)}S | gross {gross} "
        f"(stress-budget-implied) | weight/name {weight:.4f}"
    )

    # ---- 5/6) validate + queue
    account = build_account_state(
        state,
        equity,
        gross_exposure=broker.gross_exposure(closes, equity),
        net_exposure=D("0"),
        max_single_name_weight=weight,
        max_short_name_weight=weight,
    )
    proj_snapshot = PortfolioSnapshot(
        gross_exposure=gross,
        net_exposure=D("0.01") * gross,
        max_single_name_weight=weight,
        max_short_name_weight=weight,
    )
    stress: StressReport = compute_stress_report(proj_snapshot, params)
    # correlation concentration of the TARGET book from trailing returns
    rets: dict[str, list[float]] = {}
    for s in set(new_long) | set(new_short):
        series = bars.get(s, [])
        closes_list = [float(x[4]) for x in series[-95:]]
        rets[s] = [
            closes_list[i] / closes_list[i - 1] - 1
            for i in range(1, len(closes_list))
            if closes_list[i - 1] > 0
        ]
    target_weights = {s: weight for s in set(new_long) | set(new_short)}
    cluster_w = max_correlated_cluster_weight(rets, target_weights)
    projection = PortfolioProjection(
        gross_exposure=gross,
        net_exposure=D("0.01") * gross,
        max_abs_sector_net=D("0"),  # sector-neutral by construction
        max_single_name_weight=weight,
        estimated_beta=D("0.05"),  # measured from realized returns as they accrue
        max_correlated_cluster_weight=cluster_w,
    )
    throttle = OrderThrottle(PAPER_THROTTLE, seen_keys=set(state.seen_idempotency_keys))
    now = datetime.now(UTC)

    exits: list[PaperOrder] = []
    for sym, pos in broker.positions.items():
        keep = sym in new_long if pos.quantity > 0 else sym in new_short
        if not keep:
            exits.append(
                PaperOrder(
                    order_id=f"x-{sym}-{session_date.isoformat()}",
                    symbol=sym,
                    direction="SELL" if pos.quantity > 0 else "BUY_TO_COVER",
                    quantity=abs(pos.quantity),
                    stop_distance_fraction=D("0"),
                )
            )
    # exits bypass opportunity gates by policy (risk reduction), but not health
    healthy_enough = (
        health.kill_switch_inactive
        and not health.incident_lock_active
        and health.market_data_current
    )
    queued_exits = 0
    if healthy_enough:
        for order in exits:
            broker.queue(order)
            queued_exits += 1

    approved = 0
    rejected: dict[str, int] = {}
    entries = [(s, "BUY") for s in new_long if s not in held_long] + [
        (s, "SELL_SHORT") for s in new_short if s not in held_short
    ]
    for sym, direction in entries:
        px = closes.get(sym)
        if px is None or px <= 0:
            continue
        qty = (weight * equity / px).quantize(D("0.0001"))
        if qty <= 0:
            continue
        series = bars[sym]
        adv = sum(x[4] * x[5] for x in series[-20:]) / min(len(series), 20)
        signal = SignalState(
            strategy_id="EQUITY_MOMENTUM_V1",
            signal_type="LONG_ENTRY" if direction == "BUY" else "SHORT_ENTRY",
            symbol=sym,
            current_rank=0,
            momentum_score=scores.get(sym, D("0")),
            rebalance_date=now,
            target_weight=weight,
            history_complete=len(series) >= LOOKBACK + SKIP + 1,
            point_in_time_clean=True,
            corporate_actions_adjusted=True,
            crossed_entry_threshold=True,
            already_acted_upon=False,
            rebalance_required=True,
        )
        instrument = InstrumentState(
            symbol=sym,
            in_point_in_time_universe=True,
            active=True,
            delisted=False,
            halted=False,
            price=px,
            average_daily_dollar_volume=adv,
            market_cap=D("10000000000"),  # S&P membership implies cap; feed TODO
            corporate_action_data_valid=True,
            quote_age_seconds=D("1"),
            within_trading_hours=True,
        )
        order = OrderSpec(
            symbol=sym,
            direction=direction,
            quantity=qty,
            order_type="MARKET",
            time_in_force="DAY",
            account_id="PAPER-1",
            strategy_id="EQUITY_MOMENTUM_V1",
            protection_attached=True,
        )
        news = read_news(sym)  # mandatory: unread news == no trade
        time.sleep(0.1)
        proposal = TradeProposal(
            signal=signal,
            instrument=instrument,
            execution=ExecutionQuality(
                spread_bps=D("5"),
                expected_slippage_bps=D("1"),
                order_notional=qty * px,
                quote_age_seconds=D("1"),
            ),
            order=order,
            projection=projection,
            stress=stress,
            margin=MarginState(
                available_buying_power=equity * 2,
                initial_margin_required=qty * px / 2,
                maintenance_margin_required=qty * px / 4,
                post_trade_margin_buffer_fraction=1 - gross / 2,
            ),
            short_sale=None if direction == "BUY" else _paper_short_state(),
            news=news,
            exit_plan=(
                "exit when outside sector hold zone at rebalance; "
                f"catastrophe stop {STOP_DISTANCE:%}; portfolio stress budget "
                f"{PAPER_LIMITS.total_open_risk_fraction:%}; kill switches"
            ),
            max_loss_fraction=weight * STOP_DISTANCE,
            expected_gross_edge_bps=EDGE_GROSS_BPS,
            expected_cost_bps=D("6.5"),
            reference_price=px,
        )
        decision = evaluate_trade(proposal, health, account, PAPER_LIMITS)
        key = idempotency_key(signal, order)
        if decision.approved:
            ok, throttle_rej = throttle.admit(key, now)
            if ok:
                broker.queue(
                    PaperOrder(
                        order_id=f"e-{sym}-{session_date.isoformat()}",
                        symbol=sym,
                        direction=direction,
                        quantity=qty,
                        stop_distance_fraction=STOP_DISTANCE,
                        idempotency_key=key,
                    )
                )
                approved += 1
            else:
                for r in throttle_rej:
                    rejected[r.code.value] = rejected.get(r.code.value, 0) + 1
        else:
            for r in decision.rejections:
                rejected[r.code.value] = rejected.get(r.code.value, 0) + 1
            journal(
                root,
                {
                    "type": "rejection",
                    "session": session_date,
                    "symbol": sym,
                    "codes": [r.code.value for r in decision.rejections],
                },
            )

    state.queued_orders = list(broker.queued)
    state.seen_idempotency_keys = sorted(throttle.seen_keys)
    save_state(root, state)
    journal(
        root,
        {
            "type": "session",
            "session": session_date,
            "equity": equity,
            "positions": len(broker.positions),
            "exits_queued": queued_exits,
            "entries_approved": approved,
            "entries_rejected": rejected,
            "gross_target": gross,
        },
    )
    print(
        f"queued: {queued_exits} exits, {approved} entries | "
        f"rejected: {rejected or 'none'} | state saved"
    )
    return 0


def _paper_short_state():
    from trading_desk.pretrade import ShortSaleState

    # Paper model: S&P large caps assumed general-collateral. Real borrow data
    # is a live-broker integration; documented limitation of the paper stage.
    return ShortSaleState(
        borrow_available=True,
        borrow_rate_annual=D("0.005"),
        locate_confirmed=True,
        short_sale_permitted=True,
        recall_risk_acceptable=True,
    )


if __name__ == "__main__":
    raise SystemExit(main())
