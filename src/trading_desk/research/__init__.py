"""Governed offline strategy research and optimization (Milestone 15).

This package has no operational authority: it must not import broker
adapters, HTTP clients, credentials, Risk, execution, lifecycle, journal
writers, or dashboard services, and nothing it produces can change strategy
lifecycle state.
"""

from trading_desk.research.models import (
    ExperimentRecord,
    ExperimentSpecification,
    ExperimentStatus,
    ParameterRange,
    ResourceBudget,
    create_specification,
)
from trading_desk.research.registry import ExperimentRegistry
from trading_desk.research.runner import run_experiment

__all__ = [
    "ExperimentRecord",
    "ExperimentRegistry",
    "ExperimentSpecification",
    "ExperimentStatus",
    "ParameterRange",
    "ResourceBudget",
    "create_specification",
    "run_experiment",
]
