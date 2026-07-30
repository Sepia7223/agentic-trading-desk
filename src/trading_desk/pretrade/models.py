"""Typed contracts for the mandatory pre-trade validation pipeline."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


class RejectionCode(StrEnum):
    """One exact code per rejection (recommended set + explicit extensions)."""

    SYSTEM_UNHEALTHY = "SYSTEM_UNHEALTHY"
    DAILY_LOSS_LIMIT = "DAILY_LOSS_LIMIT"
    DRAWDOWN_LIMIT = "DRAWDOWN_LIMIT"
    STALE_DATA = "STALE_DATA"
    INVALID_SIGNAL = "INVALID_SIGNAL"
    DUPLICATE_SIGNAL = "DUPLICATE_SIGNAL"
    INELIGIBLE_SYMBOL = "INELIGIBLE_SYMBOL"
    INSUFFICIENT_LIQUIDITY = "INSUFFICIENT_LIQUIDITY"
    SPREAD_TOO_WIDE = "SPREAD_TOO_WIDE"
    SLIPPAGE_TOO_HIGH = "SLIPPAGE_TOO_HIGH"
    NEGATIVE_NET_EDGE = "NEGATIVE_NET_EDGE"
    POSITION_TOO_LARGE = "POSITION_TOO_LARGE"
    PORTFOLIO_EXPOSURE = "PORTFOLIO_EXPOSURE"
    SECTOR_CONCENTRATION = "SECTOR_CONCENTRATION"
    FACTOR_CONCENTRATION = "FACTOR_CONCENTRATION"
    BORROW_UNAVAILABLE = "BORROW_UNAVAILABLE"
    BORROW_TOO_EXPENSIVE = "BORROW_TOO_EXPENSIVE"
    MARGIN_INSUFFICIENT = "MARGIN_INSUFFICIENT"
    NEWS_OR_CORPORATE_EVENT = "NEWS_OR_CORPORATE_EVENT"
    ORDER_VALIDATION_FAILED = "ORDER_VALIDATION_FAILED"
    PROTECTION_UNAVAILABLE = "PROTECTION_UNAVAILABLE"
    # explicit extensions for checks the recommended set does not cover
    DAILY_TRADE_LIMIT = "DAILY_TRADE_LIMIT"
    CONSECUTIVE_LOSS_SHUTDOWN = "CONSECUTIVE_LOSS_SHUTDOWN"
    RISK_LIMIT_EXCEEDED = "RISK_LIMIT_EXCEEDED"
    REGIME_REJECTED = "REGIME_REJECTED"
    STRESS_SCENARIO_BREACH = "STRESS_SCENARIO_BREACH"
    EQUITY_FLOOR = "EQUITY_FLOOR"
    RATE_LIMITED = "RATE_LIMITED"


class MasterCondition(StrEnum):
    SYSTEM_HEALTHY = "SYSTEM_HEALTHY"
    ACCOUNT_WITHIN_LIMITS = "ACCOUNT_WITHIN_LIMITS"
    SIGNAL_VALID = "SIGNAL_VALID"
    INSTRUMENT_ELIGIBLE = "INSTRUMENT_ELIGIBLE"
    EXPECTED_EDGE_POSITIVE_AFTER_COSTS = "EXPECTED_EDGE_POSITIVE_AFTER_COSTS"
    PORTFOLIO_WITHIN_LIMITS = "PORTFOLIO_WITHIN_LIMITS"
    EXECUTION_SAFE = "EXECUTION_SAFE"


class NewsStatus(StrEnum):
    CLEAR = "CLEAR"
    CAUTION = "CAUTION"
    BLOCK = "BLOCK"
    UNAVAILABLE = "UNAVAILABLE"


class Rejection(_Frozen):
    code: RejectionCode
    detail: str


class SystemHealth(_Frozen):
    """Checked BEFORE signal generation, not after order submission.

    Kill-switch granularity: ``kill_switch_inactive`` is the GLOBAL switch;
    ``strategy_kill_switch_inactive`` is per-strategy. ``incident_lock_active``
    is set by the order lifecycle on protection failures and may only be reset
    by a human.
    """

    market_data_current: bool
    broker_connected: bool
    account_data_reconciled: bool
    positions_reconciled: bool
    clock_synchronized: bool
    strategy_enabled: bool
    kill_switch_inactive: bool
    strategy_kill_switch_inactive: bool = True
    incident_lock_active: bool = False
    clock_skew_ms: Decimal = Field(default=Decimal("0"), ge=0)
    recently_restarted_unreconciled: bool = False
    abnormal_order_rejections: bool = False
    protective_orders_submittable: bool = True


class AccountState(_Frozen):
    """RISK-BUDGET SEMANTICS (reconciled): ``risk_per_trade`` governs each
    INCREMENTAL order's maximum loss. ``open_risk_fraction`` is NOT a sum of
    per-position stops (which ignores long-short netting and would forbid a
    60-name book); it is the portfolio's NETTED stress-based open risk — the
    worst loss across the pre-registered stress scenarios for the CURRENT
    book (see stress.compute_stress_report). The portfolio-level cap is
    therefore enforced twice: here on the current book, and in check_stress
    on the post-trade projection."""

    equity: Decimal = Field(gt=0)
    daily_loss_fraction: Decimal = Field(ge=0)
    current_drawdown_fraction: Decimal = Field(ge=0)
    daily_trade_count: int = Field(ge=0)
    consecutive_losses: int = Field(ge=0)
    open_risk_fraction: Decimal = Field(ge=0)


class InstrumentState(_Frozen):
    symbol: str
    in_point_in_time_universe: bool
    active: bool
    delisted: bool
    halted: bool
    price: Decimal = Field(ge=0)
    average_daily_dollar_volume: Decimal = Field(ge=0)
    market_cap: Decimal = Field(ge=0)
    corporate_action_data_valid: bool
    quote_age_seconds: Decimal = Field(ge=0)
    within_trading_hours: bool
    # data-sanity flags: a bad tick can fabricate a momentum rank
    price_spike_suspected: bool = False
    adjustment_sane: bool = True
    # holidays / half-days / opening-closing auction windows
    market_session_normal: bool = True


class SignalState(_Frozen):
    """The machine-readable thesis. Vague reasons are structurally impossible:
    every field maps to a frozen strategy rule."""

    strategy_id: str = Field(min_length=1)
    signal_type: Literal["LONG_ENTRY", "SHORT_ENTRY", "EXIT", "REBALANCE"]
    symbol: str = Field(min_length=1)
    current_rank: int = Field(ge=0)
    previous_rank: int | None = None
    momentum_score: Decimal
    rebalance_date: datetime
    target_weight: Decimal
    history_complete: bool
    point_in_time_clean: bool
    corporate_actions_adjusted: bool
    crossed_entry_threshold: bool
    already_acted_upon: bool
    rebalance_required: bool


class RegimeState(_Frozen):
    volatility_ok: bool = True
    dispersion_ok: bool = True
    liquidity_ok: bool = True
    strategy_drawdown_state: Literal["NORMAL", "DEFENSIVE", "SHUTDOWN"] = "NORMAL"
    filter_was_pre_registered: bool = True


class ExecutionQuality(_Frozen):
    spread_bps: Decimal = Field(ge=0)
    expected_slippage_bps: Decimal = Field(ge=0)
    order_notional: Decimal = Field(ge=0)
    quote_age_seconds: Decimal = Field(ge=0)


class ShortSaleState(_Frozen):
    borrow_available: bool
    borrow_rate_annual: Decimal = Field(ge=0)
    locate_confirmed: bool
    short_sale_permitted: bool
    recall_risk_acceptable: bool
    squeeze_event_risk: bool = False


class PortfolioProjection(_Frozen):
    """Computed AFTER the proposed trade, not before it."""

    gross_exposure: Decimal = Field(ge=0)
    net_exposure: Decimal
    max_abs_sector_net: Decimal = Field(ge=0)
    max_single_name_weight: Decimal = Field(ge=0)
    estimated_beta: Decimal
    # largest gross weight of any highly-correlated cluster of names (a
    # measurable stand-in for "correlation concentration"; supplied by the
    # caller's correlation model, conservatively gross if unknown)
    max_correlated_cluster_weight: Decimal = Field(default=Decimal("0"), ge=0)


class StressReport(_Frozen):
    """Worst projected loss fractions of equity under adverse scenarios."""

    normal_stop_loss_fraction: Decimal = Field(ge=0)
    double_volatility_loss_fraction: Decimal = Field(ge=0)
    overnight_gap_loss_fraction: Decimal = Field(ge=0)
    short_squeeze_loss_fraction: Decimal = Field(ge=0)
    correlation_spike_loss_fraction: Decimal = Field(ge=0)
    failed_hedge_loss_fraction: Decimal = Field(ge=0)

    def worst(self) -> Decimal:
        return max(
            self.normal_stop_loss_fraction,
            self.double_volatility_loss_fraction,
            self.overnight_gap_loss_fraction,
            self.short_squeeze_loss_fraction,
            self.correlation_spike_loss_fraction,
            self.failed_hedge_loss_fraction,
        )


class MarginState(_Frozen):
    available_buying_power: Decimal = Field(ge=0)
    initial_margin_required: Decimal = Field(ge=0)
    maintenance_margin_required: Decimal = Field(ge=0)
    post_trade_margin_buffer_fraction: Decimal


class OrderSpec(_Frozen):
    symbol: str = Field(min_length=1)
    direction: Literal["BUY", "SELL", "SELL_SHORT", "BUY_TO_COVER"]
    quantity: Decimal = Field(gt=0)
    order_type: Literal["LIMIT", "MARKET"]
    limit_price: Decimal | None = None
    time_in_force: Literal["DAY", "GTC", "IOC"]
    account_id: str = Field(min_length=1)
    strategy_id: str = Field(min_length=1)
    is_duplicate: bool = False
    protection_attached: bool = False


class NewsAssessment(_Frozen):
    """Result of the pre-trade news read for the symbol (live/paper only —
    there is no point-in-time news archive for backtests; documented)."""

    symbol: str
    status: NewsStatus
    headlines: tuple[str, ...] = ()
    matched_keywords: tuple[str, ...] = ()
    checked_at: datetime | None = None


class TradeProposal(_Frozen):
    """Everything the pipeline needs. The five absolute requirements are
    structural: thesis (signal), invalidation (exit_plan), maximum loss
    (max_loss_fraction), portfolio impact (projection), protection (order)."""

    signal: SignalState
    instrument: InstrumentState
    execution: ExecutionQuality
    order: OrderSpec
    projection: PortfolioProjection
    stress: StressReport
    margin: MarginState
    short_sale: ShortSaleState | None = None
    news: NewsAssessment | None = None
    regime: RegimeState = RegimeState()
    exit_plan: str = Field(min_length=1)
    max_loss_fraction: Decimal = Field(ge=0)
    expected_gross_edge_bps: Decimal
    expected_cost_bps: Decimal = Field(ge=0)
    reference_price: Decimal = Field(gt=0)


class PreTradeLimits(_Frozen):
    """Starting controls (not proof of profitability); every limit adjustable
    only by a written decision."""

    risk_per_trade_fraction: Decimal = Decimal("0.0025")
    total_open_risk_fraction: Decimal = Decimal("0.0075")
    daily_loss_limit_fraction: Decimal = Decimal("0.01")
    consecutive_loss_shutdown: int = 4
    maximum_daily_trades: int = 8
    strategy_shutdown_drawdown_fraction: Decimal = Decimal("0.08")
    minimum_price: Decimal = Decimal("5")
    minimum_average_daily_dollar_volume: Decimal = Decimal("1000000")
    minimum_market_cap: Decimal = Decimal("250000000")
    maximum_quote_age_seconds: Decimal = Decimal("10")
    maximum_spread_bps: Decimal = Decimal("20")
    maximum_slippage_bps: Decimal = Decimal("10")
    maximum_adv_fraction: Decimal = Decimal("0.01")
    maximum_borrow_rate_annual: Decimal = Decimal("0.03")
    maximum_gross_exposure: Decimal = Decimal("1.00")
    maximum_abs_net_exposure: Decimal = Decimal("0.05")
    maximum_single_name_weight: Decimal = Decimal("0.02")
    maximum_abs_sector_net: Decimal = Decimal("0.05")
    maximum_abs_beta: Decimal = Decimal("0.10")
    maximum_correlated_cluster_weight: Decimal = Decimal("0.15")
    stress_loss_limit_fraction: Decimal = Decimal("0.01")
    minimum_margin_buffer_fraction: Decimal = Decimal("0.25")
    price_collar_fraction: Decimal = Decimal("0.005")
    caution_news_blocks_shorts: bool = True
    # absolute floor: below this equity, no new trades (0 = must be set per
    # deployment; ties to the never-blow-the-account mandate)
    minimum_equity: Decimal = Field(default=Decimal("0"), ge=0)
    maximum_clock_skew_ms: Decimal = Decimal("1000")


class PreTradeDecision(_Frozen):
    approved: bool
    rejections: tuple[Rejection, ...]
    warnings: tuple[str, ...]
    master_conditions: dict[MasterCondition, bool]
    evaluated_at: datetime
