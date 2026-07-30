"""Tests for the mandatory pre-trade validation pipeline and news gate."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from trading_desk.pretrade import (
    AccountState,
    ExecutionQuality,
    InstrumentState,
    MarginState,
    MasterCondition,
    NewsAssessment,
    NewsStatus,
    OrderSpec,
    PortfolioProjection,
    RejectionCode,
    ShortSaleState,
    SignalState,
    StressReport,
    SystemHealth,
    TradeProposal,
    evaluate_trade,
)
from trading_desk.pretrade.news_gate import assess_headlines

NOW = datetime(2026, 7, 21, 14, 0, tzinfo=UTC)


def healthy() -> SystemHealth:
    return SystemHealth(
        market_data_current=True,
        broker_connected=True,
        account_data_reconciled=True,
        positions_reconciled=True,
        clock_synchronized=True,
        strategy_enabled=True,
        kill_switch_inactive=True,
    )


def account_ok() -> AccountState:
    return AccountState(
        equity=Decimal("10000"),
        daily_loss_fraction=Decimal("0"),
        current_drawdown_fraction=Decimal("0.01"),
        daily_trade_count=0,
        consecutive_losses=0,
        open_risk_fraction=Decimal("0.002"),
    )


def good_proposal(**over: object) -> TradeProposal:
    base: dict = dict(
        signal=SignalState(
            strategy_id="EQUITY_MOMENTUM_V1",
            signal_type="LONG_ENTRY",
            symbol="XYZ",
            current_rank=18,
            previous_rank=36,
            momentum_score=Decimal("0.274"),
            rebalance_date=NOW,
            target_weight=Decimal("0.0167"),
            history_complete=True,
            point_in_time_clean=True,
            corporate_actions_adjusted=True,
            crossed_entry_threshold=True,
            already_acted_upon=False,
            rebalance_required=True,
        ),
        instrument=InstrumentState(
            symbol="XYZ",
            in_point_in_time_universe=True,
            active=True,
            delisted=False,
            halted=False,
            price=Decimal("50"),
            average_daily_dollar_volume=Decimal("50000000"),
            market_cap=Decimal("10000000000"),
            corporate_action_data_valid=True,
            quote_age_seconds=Decimal("1"),
            within_trading_hours=True,
        ),
        execution=ExecutionQuality(
            spread_bps=Decimal("3"),
            expected_slippage_bps=Decimal("2"),
            order_notional=Decimal("170"),
            quote_age_seconds=Decimal("1"),
        ),
        order=OrderSpec(
            symbol="XYZ",
            direction="BUY",
            quantity=Decimal("3"),
            order_type="LIMIT",
            limit_price=Decimal("50.10"),
            time_in_force="DAY",
            account_id="ACC-1",
            strategy_id="EQUITY_MOMENTUM_V1",
            protection_attached=True,
        ),
        projection=PortfolioProjection(
            gross_exposure=Decimal("0.95"),
            net_exposure=Decimal("0.01"),
            max_abs_sector_net=Decimal("0.03"),
            max_single_name_weight=Decimal("0.017"),
            estimated_beta=Decimal("0.05"),
        ),
        stress=StressReport(
            normal_stop_loss_fraction=Decimal("0.002"),
            double_volatility_loss_fraction=Decimal("0.004"),
            overnight_gap_loss_fraction=Decimal("0.006"),
            short_squeeze_loss_fraction=Decimal("0"),
            correlation_spike_loss_fraction=Decimal("0.008"),
            failed_hedge_loss_fraction=Decimal("0.005"),
        ),
        margin=MarginState(
            available_buying_power=Decimal("5000"),
            initial_margin_required=Decimal("170"),
            maintenance_margin_required=Decimal("100"),
            post_trade_margin_buffer_fraction=Decimal("0.60"),
        ),
        news=NewsAssessment(symbol="XYZ", status=NewsStatus.CLEAR, checked_at=NOW),
        exit_plan="exit when rank > 40; catastrophe stop -1%; portfolio halt -1%",
        max_loss_fraction=Decimal("0.002"),
        expected_gross_edge_bps=Decimal("25"),
        expected_cost_bps=Decimal("6"),
        reference_price=Decimal("50"),
    )
    base.update(over)
    return TradeProposal(**base)


def test_clean_trade_is_approved_with_all_master_conditions():
    decision = evaluate_trade(good_proposal(), healthy(), account_ok())
    assert decision.approved, decision.rejections
    assert all(decision.master_conditions.values())
    assert decision.rejections == ()


def test_kill_switch_rejects_and_fails_system_condition():
    bad = healthy().model_copy(update={"kill_switch_inactive": False})
    decision = evaluate_trade(good_proposal(), bad, account_ok())
    assert not decision.approved
    assert not decision.master_conditions[MasterCondition.SYSTEM_HEALTHY]
    assert any(r.code is RejectionCode.SYSTEM_UNHEALTHY for r in decision.rejections)


def test_daily_loss_limit_blocks_new_trades():
    acct = account_ok().model_copy(update={"daily_loss_fraction": Decimal("0.011")})
    decision = evaluate_trade(good_proposal(), healthy(), acct)
    assert any(r.code is RejectionCode.DAILY_LOSS_LIMIT for r in decision.rejections)
    assert not decision.master_conditions[MasterCondition.ACCOUNT_WITHIN_LIMITS]


def test_consecutive_loss_shutdown():
    acct = account_ok().model_copy(update={"consecutive_losses": 4})
    decision = evaluate_trade(good_proposal(), healthy(), acct)
    assert any(r.code is RejectionCode.CONSECUTIVE_LOSS_SHUTDOWN for r in decision.rejections)


def test_symbol_outside_pit_universe_is_ineligible():
    inst = good_proposal().instrument.model_copy(update={"in_point_in_time_universe": False})
    decision = evaluate_trade(good_proposal(instrument=inst), healthy(), account_ok())
    assert any(r.code is RejectionCode.INELIGIBLE_SYMBOL for r in decision.rejections)
    assert not decision.master_conditions[MasterCondition.INSTRUMENT_ELIGIBLE]


def test_negative_net_edge_rejected():
    decision = evaluate_trade(
        good_proposal(expected_gross_edge_bps=Decimal("4")),
        healthy(),
        account_ok(),
    )
    assert any(r.code is RejectionCode.NEGATIVE_NET_EDGE for r in decision.rejections)
    assert not decision.master_conditions[MasterCondition.EXPECTED_EDGE_POSITIVE_AFTER_COSTS]


def test_order_price_collar():
    order = good_proposal().order.model_copy(
        update={"limit_price": Decimal("50.50")}  # > 0.5% above reference 50
    )
    decision = evaluate_trade(good_proposal(order=order), healthy(), account_ok())
    assert any(r.code is RejectionCode.ORDER_VALIDATION_FAILED for r in decision.rejections)


def test_missing_protection_rejected():
    order = good_proposal().order.model_copy(update={"protection_attached": False})
    decision = evaluate_trade(good_proposal(order=order), healthy(), account_ok())
    assert any(r.code is RejectionCode.PROTECTION_UNAVAILABLE for r in decision.rejections)


def test_short_without_borrow_rejected():
    order = good_proposal().order.model_copy(
        update={"direction": "SELL_SHORT", "limit_price": Decimal("49.90")}
    )
    decision = evaluate_trade(good_proposal(order=order), healthy(), account_ok())
    assert any(r.code is RejectionCode.BORROW_UNAVAILABLE for r in decision.rejections)


def test_short_with_confirmed_borrow_passes():
    order = good_proposal().order.model_copy(
        update={"direction": "SELL_SHORT", "limit_price": Decimal("49.90")}
    )
    short = ShortSaleState(
        borrow_available=True,
        borrow_rate_annual=Decimal("0.005"),
        locate_confirmed=True,
        short_sale_permitted=True,
        recall_risk_acceptable=True,
    )
    decision = evaluate_trade(good_proposal(order=order, short_sale=short), healthy(), account_ok())
    assert decision.approved, decision.rejections


def test_sector_concentration_rejected():
    proj = good_proposal().projection.model_copy(update={"max_abs_sector_net": Decimal("0.08")})
    decision = evaluate_trade(good_proposal(projection=proj), healthy(), account_ok())
    assert any(r.code is RejectionCode.SECTOR_CONCENTRATION for r in decision.rejections)
    assert not decision.master_conditions[MasterCondition.PORTFOLIO_WITHIN_LIMITS]


def test_stress_breach_rejected():
    stress = good_proposal().stress.model_copy(
        update={"short_squeeze_loss_fraction": Decimal("0.02")}
    )
    decision = evaluate_trade(good_proposal(stress=stress), healthy(), account_ok())
    assert any(r.code is RejectionCode.STRESS_SCENARIO_BREACH for r in decision.rejections)


def test_unread_news_fails_closed():
    decision = evaluate_trade(good_proposal(news=None), healthy(), account_ok())
    assert any(r.code is RejectionCode.NEWS_OR_CORPORATE_EVENT for r in decision.rejections)


def test_blocking_news_rejects_trade():
    news = NewsAssessment(
        symbol="XYZ",
        status=NewsStatus.BLOCK,
        matched_keywords=("merger",),
        checked_at=NOW,
    )
    decision = evaluate_trade(good_proposal(news=news), healthy(), account_ok())
    assert any(r.code is RejectionCode.NEWS_OR_CORPORATE_EVENT for r in decision.rejections)


def test_caution_news_blocks_short_but_warns_long():
    news = NewsAssessment(
        symbol="XYZ",
        status=NewsStatus.CAUTION,
        matched_keywords=("earnings",),
        checked_at=NOW,
    )
    long_decision = evaluate_trade(good_proposal(news=news), healthy(), account_ok())
    assert long_decision.approved
    assert long_decision.warnings

    order = good_proposal().order.model_copy(
        update={"direction": "SELL_SHORT", "limit_price": Decimal("49.90")}
    )
    short = ShortSaleState(
        borrow_available=True,
        borrow_rate_annual=Decimal("0.005"),
        locate_confirmed=True,
        short_sale_permitted=True,
        recall_risk_acceptable=True,
    )
    short_decision = evaluate_trade(
        good_proposal(order=order, short_sale=short, news=news),
        healthy(),
        account_ok(),
    )
    assert not short_decision.approved


def test_regime_shutdown_rejects():
    regime = good_proposal().regime.model_copy(update={"strategy_drawdown_state": "SHUTDOWN"})
    decision = evaluate_trade(good_proposal(regime=regime), healthy(), account_ok())
    assert any(r.code is RejectionCode.REGIME_REJECTED for r in decision.rejections)


def test_rejections_carry_exact_codes_only_from_taxonomy():
    bad_health = healthy().model_copy(update={"broker_connected": False})
    acct = account_ok().model_copy(update={"daily_loss_fraction": Decimal("0.02")})
    decision = evaluate_trade(good_proposal(expected_gross_edge_bps=Decimal("0")), bad_health, acct)
    assert not decision.approved
    assert len(decision.rejections) >= 3  # all failures collected, not just first
    for r in decision.rejections:
        assert isinstance(r.code, RejectionCode)
        assert r.detail


# ------------------------------------------------------------------ news gate


def test_headline_block_keyword_detected():
    a = assess_headlines(
        "XYZ",
        [("XYZ agrees to merger with ABC in $10B deal", NOW)],
        now=NOW,
    )
    assert a.status is NewsStatus.BLOCK
    assert "merger" in a.matched_keywords


def test_headline_caution_keyword_detected():
    a = assess_headlines(
        "XYZ",
        [("XYZ earnings preview: what to expect", NOW)],
        now=NOW,
    )
    assert a.status is NewsStatus.CAUTION


def test_old_headlines_outside_window_ignored():
    old = datetime(2026, 7, 1, tzinfo=UTC)
    a = assess_headlines(
        "XYZ",
        [("XYZ bankruptcy filing shocks investors", old)],
        now=NOW,
        recency_hours=48.0,
    )
    assert a.status is NewsStatus.CLEAR


def test_clear_when_no_risk_headlines():
    a = assess_headlines(
        "XYZ",
        [("XYZ announces new product line", NOW)],
        now=NOW,
    )
    assert a.status is NewsStatus.CLEAR
