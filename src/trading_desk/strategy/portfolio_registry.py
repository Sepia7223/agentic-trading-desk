"""Deterministic registry for all Milestone 12 strategy evaluators."""

from __future__ import annotations

from trading_desk.strategy.contracts import StrategyEvaluator
from trading_desk.strategy.range_mean_reversion import RangeMeanReversionEvaluator
from trading_desk.strategy.trend_pullback import TrendPullbackEvaluator
from trading_desk.strategy.volatility_breakout import VolatilityBreakoutEvaluator


class PortfolioStrategyRegistry:
    def __init__(self, evaluators: tuple[StrategyEvaluator, ...] | None = None) -> None:
        values = evaluators or (
            TrendPullbackEvaluator(),
            VolatilityBreakoutEvaluator(),
            RangeMeanReversionEvaluator(),
        )
        identifiers = tuple(item.strategy_id for item in values)
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("portfolio strategy identifiers must be unique")
        self._evaluators = tuple(sorted(values, key=lambda item: item.strategy_id))

    @property
    def evaluators(self) -> tuple[StrategyEvaluator, ...]:
        return self._evaluators

    def require(self, strategy_id: str) -> StrategyEvaluator:
        match = next((item for item in self._evaluators if item.strategy_id == strategy_id), None)
        if match is None:
            raise KeyError(f"unknown strategy: {strategy_id}")
        return match
