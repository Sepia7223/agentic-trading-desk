"""Typed adapter around the unchanged three-pillar score engine."""

from __future__ import annotations

from typing import Any

from trading_desk.strategy import score
from trading_desk.strategy.models import BaselineResult, StrategyContext, StrategyMarketData

BASELINE_MODEL_VERSION = "three-pillar-legacy-v1"


def evaluate_baseline(data: StrategyMarketData, context: StrategyContext) -> BaselineResult:
    card: dict[str, Any] = score.score_symbol(
        list(data.close_midpoints),
        macro_score=context.macro_score,
        symbol=data.epic,
        holding=context.holding,
    )
    pillars = card["pillars"]
    decision = card["decision"]
    flags = decision["flags"]
    exhaustion = tuple(str(value) for value in flags.get("exhaustion", ()))
    bearish = tuple(str(value) for value in flags.get("bearish", ()))
    rebound = tuple(str(value) for value in flags.get("rebound", ()))
    death_cross = bool(flags.get("death_cross", False))
    relentless = len(bearish) >= 3 or (death_cross and len(bearish) >= 2)
    all_flags = tuple(
        [*(f"exhaustion: {value}" for value in exhaustion)]
        + [*(f"bearish: {value}" for value in bearish)]
        + [*(f"rebound: {value}" for value in rebound)]
        + (["death-cross"] if death_cross else [])
    )
    return BaselineResult(
        trend_score=int(pillars["trend"]["score"]),
        trend_detail=str(pillars["trend"]["detail"]),
        momentum_score=int(pillars["momentum"]["score"]),
        momentum_detail=str(pillars["momentum"]["detail"]),
        macro_score=context.macro_score,
        total_pillar_score=int(card["pillar_total"]),
        original_decision=str(decision["action"]),
        original_flags=all_flags,
        exhaustion_flags=exhaustion,
        bearish_flags=bearish,
        rebound_flags=rebound,
        death_cross=death_cross,
        relentless_bearish=relentless,
    )
