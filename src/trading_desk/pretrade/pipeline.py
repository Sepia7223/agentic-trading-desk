"""The mandatory pre-trade validation pipeline.

Order (fixed): system -> account -> instrument -> signal -> regime -> risk ->
edge-after-costs -> execution -> short-sale -> portfolio -> stress -> margin ->
order -> protection -> news. ALL rejections are collected (observability over
short-circuiting); the trade is approved only when every master condition holds:

    APPROVE_TRADE =
        SYSTEM_HEALTHY AND ACCOUNT_WITHIN_LIMITS AND SIGNAL_VALID
        AND INSTRUMENT_ELIGIBLE AND EXPECTED_EDGE_POSITIVE_AFTER_COSTS
        AND PORTFOLIO_WITHIN_LIMITS AND EXECUTION_SAFE

Pure logic: no I/O, no broker calls — every input is a typed snapshot supplied
by the caller, so the pipeline is deterministic and unit-testable. The news
assessment is produced separately (see news_gate) and injected.
"""

from __future__ import annotations

from datetime import UTC, datetime

from trading_desk.pretrade.models import (
    AccountState,
    MasterCondition,
    NewsStatus,
    PreTradeDecision,
    PreTradeLimits,
    Rejection,
    RejectionCode,
    SystemHealth,
    TradeProposal,
)


def _reject(code: RejectionCode, detail: str) -> Rejection:
    return Rejection(code=code, detail=detail)


def check_system(health: SystemHealth, limits: PreTradeLimits) -> list[Rejection]:
    out: list[Rejection] = []
    if not health.market_data_current:
        out.append(_reject(RejectionCode.STALE_DATA, "market data stale or missing"))
    for flag, name in (
        (health.broker_connected, "broker disconnected"),
        (health.account_data_reconciled, "account data not reconciled"),
        (health.positions_reconciled, "broker/internal positions disagree"),
        (health.clock_synchronized, "clock not synchronized"),
        (health.strategy_enabled, "strategy disabled"),
        (health.kill_switch_inactive, "GLOBAL kill switch active"),
        (health.strategy_kill_switch_inactive, "strategy kill switch active"),
        (not health.incident_lock_active, "incident lock active (human reset only)"),
        (health.protective_orders_submittable, "protective order cannot be submitted"),
    ):
        if not flag:
            out.append(_reject(RejectionCode.SYSTEM_UNHEALTHY, name))
    if health.clock_skew_ms > limits.maximum_clock_skew_ms:
        out.append(
            _reject(
                RejectionCode.SYSTEM_UNHEALTHY,
                f"clock skew {health.clock_skew_ms}ms > {limits.maximum_clock_skew_ms}ms",
            )
        )
    if health.recently_restarted_unreconciled:
        out.append(_reject(RejectionCode.SYSTEM_UNHEALTHY, "recent restart not reconciled"))
    if health.abnormal_order_rejections:
        out.append(_reject(RejectionCode.SYSTEM_UNHEALTHY, "orders rejected abnormally"))
    return out


def check_account(account: AccountState, limits: PreTradeLimits) -> list[Rejection]:
    out: list[Rejection] = []
    if limits.minimum_equity > 0 and account.equity < limits.minimum_equity:
        out.append(
            _reject(
                RejectionCode.EQUITY_FLOOR,
                f"equity {account.equity} below floor {limits.minimum_equity}",
            )
        )
    if account.daily_loss_fraction >= limits.daily_loss_limit_fraction:
        out.append(
            _reject(
                RejectionCode.DAILY_LOSS_LIMIT,
                f"daily loss {account.daily_loss_fraction} >= {limits.daily_loss_limit_fraction}",
            )
        )
    if account.current_drawdown_fraction >= limits.strategy_shutdown_drawdown_fraction:
        out.append(
            _reject(
                RejectionCode.DRAWDOWN_LIMIT,
                f"drawdown {account.current_drawdown_fraction} >= "
                f"{limits.strategy_shutdown_drawdown_fraction}",
            )
        )
    if account.daily_trade_count >= limits.maximum_daily_trades:
        out.append(
            _reject(
                RejectionCode.DAILY_TRADE_LIMIT,
                f"{account.daily_trade_count} trades today >= {limits.maximum_daily_trades}",
            )
        )
    if account.consecutive_losses >= limits.consecutive_loss_shutdown:
        out.append(
            _reject(
                RejectionCode.CONSECUTIVE_LOSS_SHUTDOWN,
                f"{account.consecutive_losses} consecutive losses",
            )
        )
    if account.open_risk_fraction >= limits.total_open_risk_fraction:
        out.append(
            _reject(
                RejectionCode.RISK_LIMIT_EXCEEDED,
                f"open risk {account.open_risk_fraction} >= {limits.total_open_risk_fraction}",
            )
        )
    return out


def check_instrument(p: TradeProposal, limits: PreTradeLimits) -> list[Rejection]:
    inst = p.instrument
    out: list[Rejection] = []
    if not inst.in_point_in_time_universe:
        out.append(
            _reject(
                RejectionCode.INELIGIBLE_SYMBOL,
                f"{inst.symbol} not in point-in-time universe",
            )
        )
    if not inst.active or inst.delisted:
        out.append(_reject(RejectionCode.INELIGIBLE_SYMBOL, f"{inst.symbol} inactive/delisted"))
    if inst.halted:
        out.append(_reject(RejectionCode.INELIGIBLE_SYMBOL, f"{inst.symbol} halted"))
    if inst.price < limits.minimum_price:
        out.append(
            _reject(
                RejectionCode.INELIGIBLE_SYMBOL,
                f"price {inst.price} below floor {limits.minimum_price}",
            )
        )
    if inst.average_daily_dollar_volume < limits.minimum_average_daily_dollar_volume:
        out.append(_reject(RejectionCode.INSUFFICIENT_LIQUIDITY, "ADV below minimum"))
    if inst.market_cap < limits.minimum_market_cap:
        out.append(_reject(RejectionCode.INELIGIBLE_SYMBOL, "market cap below minimum"))
    if not inst.corporate_action_data_valid:
        out.append(
            _reject(
                RejectionCode.NEWS_OR_CORPORATE_EVENT,
                "corporate-action data invalid/abnormal",
            )
        )
    if inst.quote_age_seconds > limits.maximum_quote_age_seconds:
        out.append(_reject(RejectionCode.STALE_DATA, "quote too old"))
    if not inst.within_trading_hours:
        out.append(_reject(RejectionCode.INELIGIBLE_SYMBOL, "outside approved trading hours"))
    if inst.price_spike_suspected:
        out.append(_reject(RejectionCode.STALE_DATA, "price spike/outlier suspected in data"))
    if not inst.adjustment_sane:
        out.append(_reject(RejectionCode.STALE_DATA, "corporate-action adjustment implausible"))
    if not inst.market_session_normal:
        out.append(
            _reject(
                RejectionCode.INELIGIBLE_SYMBOL,
                "abnormal session (holiday/half-day/auction window)",
            )
        )
    return out


def check_signal(p: TradeProposal) -> list[Rejection]:
    s = p.signal
    out: list[Rejection] = []
    if not s.history_complete:
        out.append(_reject(RejectionCode.INVALID_SIGNAL, "required history incomplete"))
    if not s.point_in_time_clean:
        out.append(_reject(RejectionCode.INVALID_SIGNAL, "future information in calculation"))
    if not s.corporate_actions_adjusted:
        out.append(_reject(RejectionCode.INVALID_SIGNAL, "corporate actions not adjusted"))
    if not s.crossed_entry_threshold:
        out.append(_reject(RejectionCode.INVALID_SIGNAL, "entry threshold not crossed"))
    if s.already_acted_upon:
        out.append(_reject(RejectionCode.DUPLICATE_SIGNAL, "signal already acted on"))
    if not s.rebalance_required:
        out.append(
            _reject(
                RejectionCode.INVALID_SIGNAL,
                "no rebalance genuinely required (buffer holds current position)",
            )
        )
    return out


def check_regime(p: TradeProposal) -> list[Rejection]:
    """A regime filter may only act if it was pre-registered before testing."""

    r = p.regime
    out: list[Rejection] = []
    if not r.filter_was_pre_registered:
        out.append(
            _reject(
                RejectionCode.REGIME_REJECTED,
                "regime filter not pre-registered — may not be applied",
            )
        )
        return out
    if not r.volatility_ok:
        out.append(_reject(RejectionCode.REGIME_REJECTED, "volatility above emergency level"))
    if not r.dispersion_ok:
        out.append(_reject(RejectionCode.REGIME_REJECTED, "cross-sectional dispersion too low"))
    if not r.liquidity_ok:
        out.append(_reject(RejectionCode.REGIME_REJECTED, "market liquidity impaired"))
    if r.strategy_drawdown_state == "SHUTDOWN":
        out.append(_reject(RejectionCode.REGIME_REJECTED, "strategy in SHUTDOWN state"))
    return out


def check_risk(p: TradeProposal, limits: PreTradeLimits) -> list[Rejection]:
    out: list[Rejection] = []
    if p.max_loss_fraction > limits.risk_per_trade_fraction:
        out.append(
            _reject(
                RejectionCode.RISK_LIMIT_EXCEEDED,
                f"max loss {p.max_loss_fraction} > per-trade {limits.risk_per_trade_fraction}",
            )
        )
    return out


def check_edge(p: TradeProposal) -> list[Rejection]:
    net = p.expected_gross_edge_bps - p.expected_cost_bps
    if net <= 0:
        return [
            _reject(
                RejectionCode.NEGATIVE_NET_EDGE,
                f"expected net edge {net} bps <= 0 "
                f"(gross {p.expected_gross_edge_bps} - cost {p.expected_cost_bps})",
            )
        ]
    return []


def check_execution(p: TradeProposal, limits: PreTradeLimits) -> list[Rejection]:
    e = p.execution
    out: list[Rejection] = []
    if e.spread_bps > limits.maximum_spread_bps:
        out.append(_reject(RejectionCode.SPREAD_TOO_WIDE, f"spread {e.spread_bps}bps"))
    if e.expected_slippage_bps > limits.maximum_slippage_bps:
        out.append(
            _reject(RejectionCode.SLIPPAGE_TOO_HIGH, f"slippage {e.expected_slippage_bps}bps")
        )
    adv = p.instrument.average_daily_dollar_volume
    if adv > 0 and e.order_notional > adv * limits.maximum_adv_fraction:
        out.append(
            _reject(
                RejectionCode.INSUFFICIENT_LIQUIDITY,
                f"order {e.order_notional} > {limits.maximum_adv_fraction} of ADV",
            )
        )
    if e.quote_age_seconds > limits.maximum_quote_age_seconds:
        out.append(_reject(RejectionCode.STALE_DATA, "execution quote too old"))
    return out


def check_short_sale(p: TradeProposal, limits: PreTradeLimits) -> list[Rejection]:
    if p.order.direction != "SELL_SHORT":
        return []
    s = p.short_sale
    if s is None:
        return [_reject(RejectionCode.BORROW_UNAVAILABLE, "no short-sale state provided")]
    out: list[Rejection] = []
    if not (s.borrow_available and s.locate_confirmed and s.short_sale_permitted):
        out.append(_reject(RejectionCode.BORROW_UNAVAILABLE, "borrow/locate/permission failed"))
    if s.borrow_rate_annual > limits.maximum_borrow_rate_annual:
        out.append(
            _reject(
                RejectionCode.BORROW_TOO_EXPENSIVE,
                f"borrow {s.borrow_rate_annual} > {limits.maximum_borrow_rate_annual}",
            )
        )
    if not s.recall_risk_acceptable:
        out.append(_reject(RejectionCode.BORROW_UNAVAILABLE, "recall risk unacceptable"))
    if s.squeeze_event_risk:
        out.append(
            _reject(
                RejectionCode.NEWS_OR_CORPORATE_EVENT,
                "corporate event creates extreme squeeze risk",
            )
        )
    return out


def check_portfolio(p: TradeProposal, limits: PreTradeLimits) -> list[Rejection]:
    proj = p.projection
    out: list[Rejection] = []
    if proj.gross_exposure > limits.maximum_gross_exposure:
        out.append(
            _reject(
                RejectionCode.PORTFOLIO_EXPOSURE,
                f"gross {proj.gross_exposure} > {limits.maximum_gross_exposure}",
            )
        )
    if abs(proj.net_exposure) > limits.maximum_abs_net_exposure:
        out.append(
            _reject(
                RejectionCode.PORTFOLIO_EXPOSURE,
                f"|net| {proj.net_exposure} > {limits.maximum_abs_net_exposure}",
            )
        )
    if proj.max_single_name_weight > limits.maximum_single_name_weight:
        out.append(
            _reject(
                RejectionCode.POSITION_TOO_LARGE,
                f"single-name weight {proj.max_single_name_weight}",
            )
        )
    if proj.max_abs_sector_net > limits.maximum_abs_sector_net:
        out.append(
            _reject(
                RejectionCode.SECTOR_CONCENTRATION,
                f"sector net {proj.max_abs_sector_net}",
            )
        )
    if abs(proj.estimated_beta) > limits.maximum_abs_beta:
        out.append(_reject(RejectionCode.FACTOR_CONCENTRATION, f"beta {proj.estimated_beta}"))
    if proj.max_correlated_cluster_weight > limits.maximum_correlated_cluster_weight:
        out.append(
            _reject(
                RejectionCode.FACTOR_CONCENTRATION,
                f"correlated cluster {proj.max_correlated_cluster_weight} > "
                f"{limits.maximum_correlated_cluster_weight}",
            )
        )
    return out


def check_stress(p: TradeProposal, limits: PreTradeLimits) -> list[Rejection]:
    worst = p.stress.worst()
    if worst > limits.stress_loss_limit_fraction:
        return [
            _reject(
                RejectionCode.STRESS_SCENARIO_BREACH,
                f"worst stress loss {worst} > {limits.stress_loss_limit_fraction}",
            )
        ]
    return []


def check_margin(p: TradeProposal, limits: PreTradeLimits) -> list[Rejection]:
    m = p.margin
    out: list[Rejection] = []
    if m.initial_margin_required > m.available_buying_power:
        out.append(_reject(RejectionCode.MARGIN_INSUFFICIENT, "initial margin > buying power"))
    if m.post_trade_margin_buffer_fraction < limits.minimum_margin_buffer_fraction:
        out.append(
            _reject(
                RejectionCode.MARGIN_INSUFFICIENT,
                f"post-trade buffer {m.post_trade_margin_buffer_fraction} < "
                f"{limits.minimum_margin_buffer_fraction}",
            )
        )
    return out


def check_order(p: TradeProposal, limits: PreTradeLimits) -> list[Rejection]:
    o = p.order
    out: list[Rejection] = []
    if o.symbol != p.instrument.symbol or o.symbol != p.signal.symbol:
        out.append(_reject(RejectionCode.ORDER_VALIDATION_FAILED, "symbol mismatch"))
    if o.strategy_id != p.signal.strategy_id:
        out.append(_reject(RejectionCode.ORDER_VALIDATION_FAILED, "strategy id mismatch"))
    if o.is_duplicate:
        out.append(_reject(RejectionCode.ORDER_VALIDATION_FAILED, "duplicate order"))
    if o.order_type == "LIMIT":
        if o.limit_price is None:
            out.append(_reject(RejectionCode.ORDER_VALIDATION_FAILED, "limit without price"))
        else:
            collar = p.reference_price * limits.price_collar_fraction
            buying = o.direction in ("BUY", "BUY_TO_COVER")
            if buying and o.limit_price > p.reference_price + collar:
                out.append(
                    _reject(
                        RejectionCode.ORDER_VALIDATION_FAILED,
                        "buy price above collar",
                    )
                )
            if not buying and o.limit_price < p.reference_price - collar:
                out.append(
                    _reject(
                        RejectionCode.ORDER_VALIDATION_FAILED,
                        "sell price below collar",
                    )
                )
    if not o.protection_attached:
        out.append(
            _reject(
                RejectionCode.PROTECTION_UNAVAILABLE,
                "entry has no linked protective exit",
            )
        )
    return out


def check_news(p: TradeProposal, limits: PreTradeLimits) -> tuple[list[Rejection], list[str]]:
    """News must be read before the trade. Missing assessment rejects; BLOCK
    rejects; CAUTION rejects shorts (configurable) and warns on longs."""

    out: list[Rejection] = []
    warnings: list[str] = []
    n = p.news
    if n is None or n.status is NewsStatus.UNAVAILABLE:
        out.append(
            _reject(
                RejectionCode.NEWS_OR_CORPORATE_EVENT,
                "news not read / source unavailable — trade may not proceed unread",
            )
        )
        return out, warnings
    if n.status is NewsStatus.BLOCK:
        out.append(
            _reject(
                RejectionCode.NEWS_OR_CORPORATE_EVENT,
                f"blocking news: {', '.join(n.matched_keywords) or 'flagged'}",
            )
        )
    elif n.status is NewsStatus.CAUTION:
        if limits.caution_news_blocks_shorts and p.order.direction == "SELL_SHORT":
            out.append(
                _reject(
                    RejectionCode.NEWS_OR_CORPORATE_EVENT,
                    "caution-level news blocks new shorts",
                )
            )
        else:
            warnings.append(f"news caution for {n.symbol}: {', '.join(n.matched_keywords)}")
    return out, warnings


_ACCOUNT_CODES = {
    RejectionCode.DAILY_LOSS_LIMIT,
    RejectionCode.DRAWDOWN_LIMIT,
    RejectionCode.DAILY_TRADE_LIMIT,
    RejectionCode.CONSECUTIVE_LOSS_SHUTDOWN,
    RejectionCode.RISK_LIMIT_EXCEEDED,
}
_SIGNAL_CODES = {
    RejectionCode.INVALID_SIGNAL,
    RejectionCode.DUPLICATE_SIGNAL,
    RejectionCode.REGIME_REJECTED,
}
_INSTRUMENT_CODES = {
    RejectionCode.INELIGIBLE_SYMBOL,
    RejectionCode.NEWS_OR_CORPORATE_EVENT,
}
_PORTFOLIO_CODES = {
    RejectionCode.PORTFOLIO_EXPOSURE,
    RejectionCode.POSITION_TOO_LARGE,
    RejectionCode.SECTOR_CONCENTRATION,
    RejectionCode.FACTOR_CONCENTRATION,
    RejectionCode.STRESS_SCENARIO_BREACH,
}
_EXECUTION_CODES = {
    RejectionCode.SPREAD_TOO_WIDE,
    RejectionCode.SLIPPAGE_TOO_HIGH,
    RejectionCode.INSUFFICIENT_LIQUIDITY,
    RejectionCode.STALE_DATA,
    RejectionCode.BORROW_UNAVAILABLE,
    RejectionCode.BORROW_TOO_EXPENSIVE,
    RejectionCode.MARGIN_INSUFFICIENT,
    RejectionCode.ORDER_VALIDATION_FAILED,
    RejectionCode.PROTECTION_UNAVAILABLE,
}


def evaluate_trade(
    proposal: TradeProposal,
    health: SystemHealth,
    account: AccountState,
    limits: PreTradeLimits | None = None,
) -> PreTradeDecision:
    """Run the full ordered checklist; approve only if every master condition
    holds. All rejections are collected with exact codes so blocked-signal
    statistics can distinguish 'no opportunity' from 'blocked by risk'."""

    limits = limits or PreTradeLimits()
    rejections: list[Rejection] = []
    warnings: list[str] = []

    rejections += check_system(health, limits)
    rejections += check_account(account, limits)
    rejections += check_instrument(proposal, limits)
    rejections += check_signal(proposal)
    rejections += check_regime(proposal)
    rejections += check_risk(proposal, limits)
    rejections += check_edge(proposal)
    rejections += check_execution(proposal, limits)
    rejections += check_short_sale(proposal, limits)
    rejections += check_portfolio(proposal, limits)
    rejections += check_stress(proposal, limits)
    rejections += check_margin(proposal, limits)
    rejections += check_order(proposal, limits)
    news_rej, news_warn = check_news(proposal, limits)
    rejections += news_rej
    warnings += news_warn

    codes = {r.code for r in rejections}
    conditions = {
        MasterCondition.SYSTEM_HEALTHY: not ({RejectionCode.SYSTEM_UNHEALTHY} & codes),
        MasterCondition.ACCOUNT_WITHIN_LIMITS: not (_ACCOUNT_CODES & codes),
        MasterCondition.SIGNAL_VALID: not (_SIGNAL_CODES & codes),
        MasterCondition.INSTRUMENT_ELIGIBLE: not (_INSTRUMENT_CODES & codes),
        MasterCondition.EXPECTED_EDGE_POSITIVE_AFTER_COSTS: (
            RejectionCode.NEGATIVE_NET_EDGE not in codes
        ),
        MasterCondition.PORTFOLIO_WITHIN_LIMITS: not (_PORTFOLIO_CODES & codes),
        MasterCondition.EXECUTION_SAFE: not (_EXECUTION_CODES & codes),
    }
    return PreTradeDecision(
        approved=not rejections,
        rejections=tuple(rejections),
        warnings=tuple(warnings),
        master_conditions=conditions,
        evaluated_at=datetime.now(UTC),
    )
