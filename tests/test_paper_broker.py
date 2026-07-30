"""Tests for the paper broker, state, health producers, and correlation."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from trading_desk.paper import (
    PaperBroker,
    PaperOrder,
    load_state,
    save_state,
)
from trading_desk.paper.broker import SessionBar
from trading_desk.paper.health import build_account_state, build_system_health
from trading_desk.paper.state import (
    INCIDENT_LOCK_FILE,
    activate_incident_lock,
)
from trading_desk.pretrade.correlation import max_correlated_cluster_weight

D = Decimal
TODAY = date(2026, 7, 21)


def bar(o: str, h: str, low: str, c: str) -> SessionBar:
    return SessionBar(open=D(o), high=D(h), low=D(low), close=D(c))


def buy(symbol: str, qty: str, stop: str = "0.15") -> PaperOrder:
    return PaperOrder(
        order_id=f"o-{symbol}",
        symbol=symbol,
        direction="BUY",
        quantity=D(qty),
        stop_distance_fraction=D(stop),
    )


def short(symbol: str, qty: str, stop: str = "0.15") -> PaperOrder:
    return PaperOrder(
        order_id=f"o-{symbol}",
        symbol=symbol,
        direction="SELL_SHORT",
        quantity=D(qty),
        stop_distance_fraction=D(stop),
    )


# -------------------------------------------------------------------- broker


def test_fill_at_open_with_adverse_costs_and_protection_armed():
    b = PaperBroker(D("10000"))
    b.queue(buy("AAA", "10"))
    fills, stops, unprotected = b.settle({"AAA": bar("100", "101", "99", "100.5")}, TODAY)
    assert len(fills) == 1 and not stops and not unprotected
    f = fills[0]
    assert f.price > D("100")  # buys pay up (spread + slippage)
    assert f.protection_armed and f.stop_price is not None
    assert f.stop_price < f.price
    assert b.positions["AAA"].quantity == D("10")


def test_long_stop_triggers_adverse_first_with_gap():
    b = PaperBroker(D("10000"))
    b.queue(buy("AAA", "10", stop="0.05"))
    b.settle({"AAA": bar("100", "101", "99", "100")}, TODAY)
    stop_px = b.positions["AAA"].stop_price
    assert stop_px is not None
    # next session gaps far below the stop: exit at the (worse) open
    _, stops, _ = b.settle({"AAA": bar("90", "92", "89", "91")}, date(2026, 7, 22))
    assert len(stops) == 1
    assert stops[0].price == D("90")  # gap-through: open, not the stop level
    assert "AAA" not in b.positions


def test_short_stop_triggers_on_high():
    b = PaperBroker(D("10000"))
    b.queue(short("BBB", "10", stop="0.05"))
    b.settle({"BBB": bar("100", "100.5", "99", "100")}, TODAY)
    assert b.positions["BBB"].quantity == D("-10")
    _, stops, _ = b.settle({"BBB": bar("104", "107", "103", "106")}, date(2026, 7, 22))
    assert len(stops) == 1
    assert stops[0].direction == "BUY_TO_COVER"
    assert "BBB" not in b.positions


def test_failed_protection_reports_unprotected_symbol():
    b = PaperBroker(D("10000"), fail_protection=True)
    b.queue(buy("AAA", "10"))
    _, _, unprotected = b.settle({"AAA": bar("100", "101", "99", "100")}, TODAY)
    assert unprotected == ["AAA"]  # incident path must fire in the caller


def test_exit_order_closes_position_and_cash_reconciles():
    b = PaperBroker(D("10000"), half_spread_bps=D("0"), slippage_bps=D("0"))
    b.queue(buy("AAA", "10", stop="0.5"))
    b.settle({"AAA": bar("100", "100", "100", "100")}, TODAY)
    assert b.cash == D("10000") - D("1000")
    b.queue(
        PaperOrder(
            order_id="x-AAA",
            symbol="AAA",
            direction="SELL",
            quantity=D("10"),
            stop_distance_fraction=D("0"),
        )
    )
    b.settle({"AAA": bar("110", "110", "110", "110")}, date(2026, 7, 22))
    assert "AAA" not in b.positions
    assert b.cash == D("10000") + D("100")  # +10% on $1,000


def test_equity_marks_positions_to_close():
    b = PaperBroker(D("10000"), half_spread_bps=D("0"), slippage_bps=D("0"))
    b.queue(buy("AAA", "10", stop="0.5"))
    b.settle({"AAA": bar("100", "100", "100", "100")}, TODAY)
    eq = b.equity({"AAA": D("105")})
    assert eq == D("10000") + D("50")
    assert b.gross_exposure({"AAA": D("105")}, eq) > D("0.1")


# --------------------------------------------------------------------- state


def test_state_persistence_roundtrip(tmp_path: Path):
    st = load_state(tmp_path, D("1000"))
    st.cash = D("900")
    st.seen_idempotency_keys.append("abc")
    st.roll_day(TODAY, D("990"))
    save_state(tmp_path, st)
    st2 = load_state(tmp_path, D("1000"))
    assert st2.cash == D("900")
    assert "abc" in st2.seen_idempotency_keys
    assert st2.equity_by_day[TODAY.isoformat()] == D("990")


def test_daily_loss_and_drawdown_and_streak(tmp_path: Path):
    st = load_state(tmp_path, D("1000"))
    st.roll_day(TODAY, D("1000"))
    assert st.daily_loss_fraction(D("992")) == D("0.008")
    st.peak_equity = D("1100")
    assert st.drawdown_fraction(D("990")) == (D("110") / D("1100"))
    st.record_round_trip(D("-5"))
    st.record_round_trip(D("-5"))
    assert st.consecutive_losses == 2
    st.record_round_trip(D("3"))
    assert st.consecutive_losses == 0


# -------------------------------------------------------------------- health


def test_system_health_reads_kill_switch_files(tmp_path: Path):
    h = build_system_health(tmp_path, latest_bar_date=TODAY, today=TODAY, reconciled=True)
    assert h.kill_switch_inactive and not h.incident_lock_active
    activate_incident_lock(tmp_path, "protection rejected")
    (tmp_path / "KILL_GLOBAL").write_text("x", encoding="utf-8")
    h2 = build_system_health(tmp_path, latest_bar_date=TODAY, today=TODAY, reconciled=True)
    assert not h2.kill_switch_inactive
    assert h2.incident_lock_active
    assert (tmp_path / INCIDENT_LOCK_FILE).exists()


def test_stale_market_data_flagged(tmp_path: Path):
    h = build_system_health(
        tmp_path,
        latest_bar_date=date(2026, 7, 10),
        today=TODAY,
        reconciled=True,
    )
    assert not h.market_data_current


def test_account_state_open_risk_is_stress_based(tmp_path: Path):
    """Calibration note: the binding default scenario is the correlation spike
    (gross x 2%), so the 0.75% open-risk budget implies max gross ~= 0.375x.
    A 0.25x-gross book must fit comfortably; a 0.5x book must NOT."""

    st = load_state(tmp_path, D("1000"))
    st.roll_day(TODAY, D("1000"))
    acct = build_account_state(
        st,
        D("1000"),
        gross_exposure=D("0.25"),
        net_exposure=D("0.005"),
        max_single_name_weight=D("0.00625"),
        max_short_name_weight=D("0.00625"),
    )
    assert D("0") < acct.open_risk_fraction <= D("0.0075")
    too_big = build_account_state(
        st,
        D("1000"),
        gross_exposure=D("0.5"),
        net_exposure=D("0.01"),
        max_single_name_weight=D("0.0125"),
        max_short_name_weight=D("0.0125"),
    )
    assert too_big.open_risk_fraction > D("0.0075")


# --------------------------------------------------------------- correlation


def test_correlated_cluster_weight_groups_comovers():
    base = [0.01, -0.02, 0.015, -0.01, 0.02, -0.005, 0.01, -0.015] * 5
    noisy = [x + ((i % 7) - 3) * 1e-4 for i, x in enumerate(base)]
    inverse = [-x for x in base]
    returns = {"A": base, "B": noisy, "C": inverse}
    weights = {"A": D("0.05"), "B": D("0.04"), "C": D("0.08")}
    w = max_correlated_cluster_weight(returns, weights, threshold=0.7)
    assert w == D("0.09")  # A+B cluster; C anti-correlated stays alone


def test_uncorrelated_names_stay_separate():
    import random

    rng = random.Random(7)
    returns = {s: [rng.gauss(0, 0.01) for _ in range(120)] for s in ("A", "B", "C")}
    weights = {s: D("0.03") for s in returns}
    w = max_correlated_cluster_weight(returns, weights, threshold=0.7)
    assert w == D("0.03")
