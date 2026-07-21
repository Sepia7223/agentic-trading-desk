"""Tests for stress calculator, order lifecycle, throttle, and new checks."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from test_pretrade_pipeline import account_ok, good_proposal, healthy
from trading_desk.pretrade import (
    LifecycleAction,
    OrderPhase,
    OrderSnapshot,
    OrderThrottle,
    PortfolioSnapshot,
    PreTradeLimits,
    RejectionCode,
    StressParameters,
    ThrottleLimits,
    compute_stress_report,
    evaluate_order,
    idempotency_key,
)
from trading_desk.pretrade.pipeline import check_account, check_system

T0 = datetime(2026, 7, 21, 15, 0, tzinfo=UTC)


# ------------------------------------------------------------------- stress


def test_stress_report_scales_with_exposures():
    small = compute_stress_report(
        PortfolioSnapshot(
            gross_exposure=Decimal("0.5"),
            net_exposure=Decimal("0.01"),
            max_single_name_weight=Decimal("0.01"),
            max_short_name_weight=Decimal("0.01"),
        )
    )
    big = compute_stress_report(
        PortfolioSnapshot(
            gross_exposure=Decimal("1.0"),
            net_exposure=Decimal("0.05"),
            max_single_name_weight=Decimal("0.02"),
            max_short_name_weight=Decimal("0.02"),
        )
    )
    assert big.worst() > small.worst()
    # shorts get the harshest single-name shock by construction
    assert big.short_squeeze_loss_fraction == Decimal("0.02") * Decimal("0.40")


def test_stress_neutral_book_within_default_limit():
    """A tight market-neutral book must pass the 1% stress budget — this is the
    reconciled portfolio-level open-risk gate."""

    report = compute_stress_report(
        PortfolioSnapshot(
            gross_exposure=Decimal("0.5"),
            net_exposure=Decimal("0.01"),
            max_single_name_weight=Decimal("0.0125"),
            max_short_name_weight=Decimal("0.0125"),
        ),
        StressParameters(),
    )
    assert report.worst() <= Decimal("0.01")


# ----------------------------------------------------------------- lifecycle


def snap(**over: object) -> OrderSnapshot:
    base: dict = dict(
        submitted_at=T0,
        quantity=Decimal("10"),
        filled_quantity=Decimal("0"),
    )
    base.update(over)
    return OrderSnapshot(**base)


def test_unfilled_within_timeout_waits():
    d = evaluate_order(snap(), T0 + timedelta(seconds=30))
    assert d.phase is OrderPhase.SUBMITTED
    assert d.actions == (LifecycleAction.WAIT,)


def test_unfilled_past_timeout_cancels():
    d = evaluate_order(snap(), T0 + timedelta(seconds=200))
    assert d.phase is OrderPhase.CANCELLED
    assert LifecycleAction.CANCEL_REMAINDER in d.actions


def test_fill_without_protection_submits_protection():
    d = evaluate_order(
        snap(filled_quantity=Decimal("10"), first_fill_at=T0),
        T0 + timedelta(seconds=5),
    )
    assert d.phase is OrderPhase.FILLED_UNPROTECTED
    assert LifecycleAction.SUBMIT_PROTECTION in d.actions


def test_protection_rejected_closes_and_locks():
    d = evaluate_order(
        snap(
            filled_quantity=Decimal("10"),
            first_fill_at=T0,
            protection_submitted=True,
            protection_rejected=True,
        ),
        T0 + timedelta(seconds=5),
    )
    assert d.phase is OrderPhase.INCIDENT
    assert LifecycleAction.CLOSE_UNPROTECTED_POSITION in d.actions
    assert LifecycleAction.ACTIVATE_INCIDENT_LOCK in d.actions


def test_protection_unconfirmed_timeout_escalates():
    d = evaluate_order(
        snap(
            filled_quantity=Decimal("10"),
            first_fill_at=T0,
            protection_submitted=True,
        ),
        T0 + timedelta(seconds=45),
    )
    assert d.phase is OrderPhase.INCIDENT
    assert LifecycleAction.ACTIVATE_INCIDENT_LOCK in d.actions


def test_partial_fill_past_timeout_keeps_protected_part():
    d = evaluate_order(
        snap(
            filled_quantity=Decimal("4"),
            first_fill_at=T0,
            protection_submitted=True,
            protection_confirmed=True,
        ),
        T0 + timedelta(seconds=200),
    )
    assert d.phase is OrderPhase.PROTECTED
    assert LifecycleAction.CANCEL_REMAINDER in d.actions


def test_fill_quality_breach_recorded():
    d = evaluate_order(
        snap(
            filled_quantity=Decimal("10"),
            first_fill_at=T0,
            protection_submitted=True,
            protection_confirmed=True,
            modeled_cost_bps=Decimal("5"),
            realized_cost_bps=Decimal("25"),
        ),
        T0 + timedelta(seconds=5),
    )
    assert d.phase is OrderPhase.PROTECTED
    assert LifecycleAction.RECORD_FILL_QUALITY_BREACH in d.actions


# ------------------------------------------------------------------ throttle


def test_idempotency_key_deterministic_and_duplicate_detected():
    p = good_proposal()
    key1 = idempotency_key(p.signal, p.order)
    key2 = idempotency_key(p.signal, p.order)
    assert key1 == key2
    th = OrderThrottle()
    ok, _ = th.admit(key1, T0)
    assert ok
    ok, rejections = th.admit(key2, T0 + timedelta(seconds=1))
    assert not ok
    assert rejections[0].code is RejectionCode.ORDER_VALIDATION_FAILED


def test_idempotency_survives_restart_via_seen_keys():
    p = good_proposal()
    key = idempotency_key(p.signal, p.order)
    th1 = OrderThrottle()
    th1.admit(key, T0)
    # simulate restart: seen keys persisted and reloaded
    th2 = OrderThrottle(seen_keys=set(th1.seen_keys))
    ok, rejections = th2.admit(key, T0 + timedelta(minutes=5))
    assert not ok
    assert rejections[0].code is RejectionCode.ORDER_VALIDATION_FAILED


def test_rate_limit_per_minute():
    th = OrderThrottle(ThrottleLimits(max_orders_per_minute=3))
    for i in range(3):
        ok, _ = th.admit(f"k{i}", T0 + timedelta(seconds=i))
        assert ok
    ok, rejections = th.admit("k3", T0 + timedelta(seconds=10))
    assert not ok
    assert rejections[0].code is RejectionCode.RATE_LIMITED
    # window slides: a minute later it admits again
    ok, _ = th.admit("k4", T0 + timedelta(seconds=75))
    assert ok


def test_open_order_cap_and_release():
    th = OrderThrottle(ThrottleLimits(max_open_orders=1, max_orders_per_minute=10))
    ok, _ = th.admit("a", T0)
    assert ok
    ok, rejections = th.admit("b", T0 + timedelta(seconds=1))
    assert not ok
    assert rejections[0].code is RejectionCode.RATE_LIMITED
    th.order_closed()
    ok, _ = th.admit("c", T0 + timedelta(seconds=2))
    assert ok


# ------------------------------------------------- new pipeline field checks


def test_equity_floor_blocks_trading():
    limits = PreTradeLimits(minimum_equity=Decimal("500"))
    acct = account_ok().model_copy(update={"equity": Decimal("400")})
    rejections = check_account(acct, limits)
    assert any(r.code is RejectionCode.EQUITY_FLOOR for r in rejections)


def test_incident_lock_and_clock_skew_reject():
    limits = PreTradeLimits()
    locked = healthy().model_copy(update={"incident_lock_active": True})
    assert any(r.code is RejectionCode.SYSTEM_UNHEALTHY for r in check_system(locked, limits))
    skewed = healthy().model_copy(update={"clock_skew_ms": Decimal("5000")})
    assert any(r.code is RejectionCode.SYSTEM_UNHEALTHY for r in check_system(skewed, limits))


def test_data_sanity_flags_reject():
    from trading_desk.pretrade import evaluate_trade

    inst = good_proposal().instrument.model_copy(update={"price_spike_suspected": True})
    decision = evaluate_trade(good_proposal(instrument=inst), healthy(), account_ok())
    assert any(r.code is RejectionCode.STALE_DATA for r in decision.rejections)


def test_correlated_cluster_limit():
    from trading_desk.pretrade import evaluate_trade

    proj = good_proposal().projection.model_copy(
        update={"max_correlated_cluster_weight": Decimal("0.30")}
    )
    decision = evaluate_trade(good_proposal(projection=proj), healthy(), account_ok())
    assert any(r.code is RejectionCode.FACTOR_CONCENTRATION for r in decision.rejections)
