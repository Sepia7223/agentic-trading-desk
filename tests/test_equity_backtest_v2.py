"""Unit tests for the v2 equity backtest engine (synthetic, hand-checkable data).

Verifies the accounting the reviewer gates depend on: PIT membership filtering,
turnover measurement, borrow-fee accrual, shortability screening, and the
direction of long/short attribution. All series are deterministic geometric
walks so expected behaviour is analytic, not fitted.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from equity_backtest_v2 import event_state, run  # noqa: E402


def weekdays(start: date, n: int) -> list[date]:
    out = []
    d = start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def geometric(dates: list[date], start_price: float, daily: float) -> dict[date, float]:
    px = start_price
    out = {}
    for d in dates:
        out[d] = px
        px *= 1 + daily
    return out


DATES = weekdays(date(2024, 1, 1), 260)
START, END = DATES[0], DATES[-1]
FULL = [(START, END)]


def make_universe():
    """Six names with a strict momentum ordering."""
    prices = {
        "UP1": geometric(DATES, 100, 0.0020),
        "UP2": geometric(DATES, 100, 0.0010),
        "MID1": geometric(DATES, 100, 0.0001),
        "MID2": geometric(DATES, 100, -0.0001),
        "DN1": geometric(DATES, 100, -0.0010),
        "DN2": geometric(DATES, 100, -0.0020),
    }
    intervals = {sym: FULL for sym in prices}
    sectors = dict.fromkeys(prices, "Test")
    return prices, intervals, sectors


BASE = dict(
    lookback=20,
    skip=0,
    basket=1,
    hold_buffer=2,
    buffered=False,
    sector_neutral=False,
    rebalance_every=1,
    gross=1.0,
    half_spread_bps=0.0,
    slippage_bps=0.0,
    commission_bps=0.0,
    borrow_fee_annual=0.0,
    min_short_price=5.0,
    delay=0,
    start_equity=1000.0,
)


def run_case(prices, intervals, sectors, **over):
    kw = {**BASE, **over}
    return run(prices, intervals, sectors, start=START, end=END, **kw)


def test_long_short_attribution_and_profit():
    prices, intervals, sectors = make_universe()
    res = run_case(prices, intervals, sectors)
    # long the strongest (UP1), short the weakest (DN2): both legs profit
    assert res["name_contrib"]["UP1"] > 0
    assert res["name_contrib"]["DN2"] > 0
    assert res["final_equity"] > 1000.0


def test_turnover_is_one_gross_then_stable():
    prices, intervals, sectors = make_universe()
    res = run_case(prices, intervals, sectors)
    # books never change after the first build (deterministic ordering), so
    # total one-way dollar turnover ~= gross x equity at first rebalance.
    assert res["turnover_dollars"] < 1.5 * 1000.0
    assert res["position_changes"] == 2  # one long entry + one short entry


def test_pit_membership_removal_switches_the_book():
    prices, intervals, sectors = make_universe()
    cut = DATES[130]
    intervals = dict(intervals)
    intervals["UP1"] = [(START, cut)]  # UP1 leaves the index mid-window
    res = run_case(prices, intervals, sectors)
    # after removal the long book must rotate into UP2
    assert res["name_contrib"].get("UP2", 0.0) > 0
    assert res["position_changes"] >= 3  # initial 2 + at least the rotation


def test_shortability_screen_excludes_cheap_names():
    prices, intervals, sectors = make_universe()
    prices = dict(prices)
    prices["DN2"] = geometric(DATES, 3.0, -0.0020)  # below $5 floor
    res = run_case(prices, intervals, sectors)
    # DN2 may never be shorted; the short book must hold DN1 instead
    assert res["name_contrib"].get("DN2", 0.0) == 0.0
    assert res["name_contrib"].get("DN1", 0.0) > 0


def test_borrow_fee_accrues_on_short_notional():
    prices, intervals, sectors = make_universe()
    free = run_case(prices, intervals, sectors)
    paid = run_case(prices, intervals, sectors, borrow_fee_annual=0.02)
    assert paid["borrow_cost_total"] > 0
    assert paid["final_equity"] < free["final_equity"]
    # ~0.5 weight x 2%/yr on ~$1k equity over ~0.95yr ≈ $9-11 of drag
    assert 3.0 < paid["borrow_cost_total"] < 20.0


def test_execution_costs_charged_on_turnover():
    prices, intervals, sectors = make_universe()
    free = run_case(prices, intervals, sectors)
    costly = run_case(
        prices, intervals, sectors,
        half_spread_bps=10.0, slippage_bps=5.0, commission_bps=5.0,
    )
    assert costly["exec_cost_total"] > 0
    assert costly["final_equity"] < free["final_equity"]


def test_delay_mode_still_trades():
    prices, intervals, sectors = make_universe()
    res = run_case(prices, intervals, sectors, delay=1)
    assert res["position_changes"] >= 2
    assert res["final_equity"] > 1000.0  # trend persists; 1-day delay still profits


def test_event_state_causality_and_windows():
    d = date(2024, 6, 14)
    evs = [(date(2024, 6, 10), "BLOCK")]
    # 4 days old, inside 7-day block window
    assert event_state(evs, d, 7, 3) == (True, False)
    # same-day acceptance is NOT knowable yet (accepted after the close)
    assert event_state([(d, "BLOCK")], d, 7, 3) == (False, False)
    # expired block window
    assert event_state(evs, date(2024, 6, 25), 7, 3) == (False, False)
    # caution only affects its own (shorter) window
    cevs = [(date(2024, 6, 12), "CAUTION")]
    assert event_state(cevs, d, 7, 3) == (False, True)
    assert event_state(cevs, date(2024, 6, 18), 7, 3) == (False, False)


def test_block_event_excludes_name_from_book():
    prices, intervals, sectors = make_universe()
    # UP1 files a BLOCK-tier 8-K mid-window: it must leave the long book and
    # UP2 must take its place while the exclusion window is active.
    mid = DATES[130]
    events = {"UP1": [(mid, "BLOCK")]}
    res = run_case(prices, intervals, sectors, events=events, event_block_days=30)
    assert res["event_block_exclusions"] > 0
    assert res["name_contrib"].get("UP2", 0.0) > 0


def test_caution_event_blocks_short_side_only():
    prices, intervals, sectors = make_universe()
    mid = DATES[130]
    events = {"DN2": [(mid, "CAUTION")], "UP1": [(mid, "CAUTION")]}
    res = run_case(
        prices, intervals, sectors, events=events, event_caution_days=30
    )
    # DN2 (short candidate) is displaced by DN1 during the caution window...
    assert res["event_short_exclusions"] > 0
    assert res["name_contrib"].get("DN1", 0.0) > 0
    # ...but UP1 (long candidate) is unaffected by caution and stays long.
    assert res["name_contrib"].get("UP1", 0.0) > 0


def test_sector_neutral_balances_each_sector():
    """Two sectors with opposite-trend names: every sector snapshot must net to
    ~zero because each sector contributes the same count long and short."""
    prices = {
        "T_UP1": geometric(DATES, 100, 0.0020),
        "T_UP2": geometric(DATES, 100, 0.0015),
        "T_DN1": geometric(DATES, 100, -0.0015),
        "T_DN2": geometric(DATES, 100, -0.0020),
        "F_UP1": geometric(DATES, 100, 0.0018),
        "F_UP2": geometric(DATES, 100, 0.0012),
        "F_DN1": geometric(DATES, 100, -0.0012),
        "F_DN2": geometric(DATES, 100, -0.0018),
    }
    intervals = {sym: FULL for sym in prices}
    sectors = {s: ("Tech" if s.startswith("T_") else "Fin") for s in prices}
    res = run_case(
        prices, intervals, sectors, sector_neutral=True, basket=2, hold_buffer=4
    )
    assert res["sector_net_series"], "expected sector snapshots"
    for snap in res["sector_net_series"]:
        for sector, net in snap.items():
            assert abs(net) < 1e-9, f"sector {sector} not neutral: {net}"
    # and both sectors actually participated
    contrib_sectors = {sectors[s] for s in res["name_contrib"]}
    assert contrib_sectors == {"Tech", "Fin"}
