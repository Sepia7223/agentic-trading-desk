"""Pre-trade validation pipeline (mandatory checklist before any order).

Every proposed trade passes the ordered pipeline: system health -> account
limits -> instrument eligibility -> signal validity -> regime -> thesis ->
invalidation/exit -> risk sizing -> net edge after costs -> execution quality ->
short-sale conditions -> post-trade portfolio -> stress -> margin -> order
validation -> protection. A trade is approved only when every master condition
holds; every rejection carries one exact machine-readable code.
"""

from trading_desk.pretrade.lifecycle import (
    LifecycleAction,
    LifecycleDecision,
    LifecyclePolicy,
    OrderPhase,
    OrderSnapshot,
    evaluate_order,
)
from trading_desk.pretrade.models import (
    AccountState,
    ExecutionQuality,
    InstrumentState,
    MarginState,
    MasterCondition,
    NewsAssessment,
    NewsStatus,
    OrderSpec,
    PortfolioProjection,
    PreTradeDecision,
    PreTradeLimits,
    RegimeState,
    Rejection,
    RejectionCode,
    ShortSaleState,
    SignalState,
    StressReport,
    SystemHealth,
    TradeProposal,
)
from trading_desk.pretrade.pipeline import evaluate_trade
from trading_desk.pretrade.stress import (
    PortfolioSnapshot,
    StressParameters,
    compute_stress_report,
)
from trading_desk.pretrade.throttle import (
    OrderThrottle,
    ThrottleLimits,
    idempotency_key,
)

__all__ = [
    "AccountState",
    "ExecutionQuality",
    "InstrumentState",
    "LifecycleAction",
    "LifecycleDecision",
    "LifecyclePolicy",
    "MarginState",
    "MasterCondition",
    "NewsAssessment",
    "NewsStatus",
    "OrderPhase",
    "OrderSnapshot",
    "OrderSpec",
    "OrderThrottle",
    "PortfolioProjection",
    "PortfolioSnapshot",
    "PreTradeDecision",
    "PreTradeLimits",
    "RegimeState",
    "Rejection",
    "RejectionCode",
    "ShortSaleState",
    "SignalState",
    "StressParameters",
    "StressReport",
    "SystemHealth",
    "ThrottleLimits",
    "TradeProposal",
    "compute_stress_report",
    "evaluate_order",
    "evaluate_trade",
    "idempotency_key",
]
