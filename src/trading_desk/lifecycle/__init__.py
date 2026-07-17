"""Deterministic IG Demo position management and exit lifecycle."""

from trading_desk.lifecycle.config import LifecycleConfiguration
from trading_desk.lifecycle.engine import DemoPositionLifecycleEngine
from trading_desk.lifecycle.evaluator import evaluate_exit
from trading_desk.lifecycle.models import (
    CloseExecutionResult,
    CloseRequest,
    DemoPositionSnapshot,
    ExitDecision,
    ExitReason,
    LifecycleOutcome,
    LifecyclePostTradeReview,
    PaperDemoExitComparison,
)

__all__ = [
    "CloseExecutionResult",
    "CloseRequest",
    "DemoPositionLifecycleEngine",
    "DemoPositionSnapshot",
    "ExitDecision",
    "ExitReason",
    "LifecycleConfiguration",
    "LifecycleOutcome",
    "LifecyclePostTradeReview",
    "PaperDemoExitComparison",
    "evaluate_exit",
]
