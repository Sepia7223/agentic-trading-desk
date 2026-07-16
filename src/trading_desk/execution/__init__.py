"""Controlled IG Demo execution boundary."""

from trading_desk.execution.config import (
    AutomatedDemoExecutionPolicy,
    ExecutionConfiguration,
    ExecutionMode,
)
from trading_desk.execution.engine import ExecutionEngine
from trading_desk.execution.models import (
    ExecutionOutcome,
    ExecutionPreflightResult,
    ExecutionRequest,
    ExecutionResult,
    OperatorConfirmation,
)

__all__ = [
    "AutomatedDemoExecutionPolicy",
    "ExecutionConfiguration",
    "ExecutionEngine",
    "ExecutionOutcome",
    "ExecutionPreflightResult",
    "ExecutionRequest",
    "ExecutionResult",
    "ExecutionMode",
    "OperatorConfirmation",
]
