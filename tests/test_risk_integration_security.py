from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from tests.risk_helpers import NOW, account, market

from trading_desk.risk.engine import RiskEngine
from trading_desk.risk.mapping import map_strategy_candidate
from trading_desk.risk.models import AssetClass, RiskDecisionStatus, RiskMarketStatus
from trading_desk.strategy.configuration import StrategyConfiguration
from trading_desk.strategy.models import (
    BaselineResult,
    DataValidationResult,
    HMMRegimeResult,
    KalmanTrendResult,
    Regime,
    RegimeProbability,
    StrategyAction,
    StrategyContext,
    StrategyMarketData,
)
from trading_desk.strategy.signal_engine import generate_trade_candidate

ROOT = Path(__file__).parents[1]


def _strategy_candidate():
    timestamp = datetime(2026, 7, 15, 11, 59, 30, tzinfo=UTC)
    data = StrategyMarketData(
        epic="CS.D.TEST.CFD.IP",
        instrument_name="Test market",
        timestamps=(timestamp,),
        open_midpoints=(100.0,),
        high_midpoints=(101.0,),
        low_midpoints=(99.0,),
        close_midpoints=(100.0,),
        bids=(99.9,),
        asks=(100.0,),
        spreads=(0.1,),
        spread_bps=(10.0,),
        volume=(1000.0,),
        market_status="TRADEABLE",
        data_retrieval_time=timestamp,
        source_bar_count=1,
    )
    context = StrategyContext(
        holding=False,
        macro_score=1,
        current_spread=0.1,
        current_spread_bps=10.0,
        market_status="TRADEABLE",
        current_time=timestamp,
    )
    baseline = BaselineResult(
        trend_score=2,
        trend_detail="bullish",
        momentum_score=2,
        momentum_detail="rebound",
        macro_score=1,
        total_pillar_score=5,
        original_decision="RE-ENTRY",
        original_flags=("rebound: test",),
        exhaustion_flags=(),
        bearish_flags=(),
        rebound_flags=("test",),
        death_cross=False,
        relentless_bearish=False,
    )
    kalman = KalmanTrendResult(
        ready=True,
        current_filtered_level=100.0,
        current_slope=0.1,
        current_slope_uncertainty=0.1,
        current_normalized_slope=0.001,
        current_normalized_slope_uncertainty=0.001,
        normalized_price_deviation=0.0,
        observations_used=220,
    )
    regime = HMMRegimeResult(
        ready=True,
        current_regime=Regime.BULL_LOW_VOL,
        probabilities=(
            RegimeProbability(regime=Regime.BULL_LOW_VOL, probability=0.9),
            RegimeProbability(regime=Regime.TRANSITIONAL, probability=0.05),
            RegimeProbability(regime=Regime.BEAR_HIGH_VOL, probability=0.05),
        ),
        selected_regime_probability=0.9,
        uncertainty=0.2,
        converged=True,
        observations_used=200,
    )
    return generate_trade_candidate(
        data,
        context,
        DataValidationResult(valid=True, findings=()),
        baseline,
        kalman,
        regime,
        StrategyConfiguration(),
    )


def test_actual_strategy_output_maps_to_risk_and_approves() -> None:
    strategy_candidate = _strategy_candidate()
    assert strategy_candidate.action is StrategyAction.LONG_CANDIDATE
    risk_candidate = map_strategy_candidate(
        strategy_candidate,
        candidate_id="candidate-integrated",
        signal_id="signal-integrated",
        asset_class=AssetClass.FOREX,
        candidate_expiry=NOW + timedelta(minutes=4),
        entry_reference=Decimal("100"),
        stop_reference=Decimal("95"),
        target_reference=Decimal("110"),
        bid=Decimal("99.9"),
        ask=Decimal("100"),
        volatility_or_atr=Decimal("2"),
        market_status=RiskMarketStatus.TRADEABLE,
        holding_state=False,
    )

    decision = RiskEngine().evaluate(risk_candidate, account(), market(), NOW)

    assert decision.status is RiskDecisionStatus.APPROVED
    assert decision.approved_intent is not None
    assert decision.approved_intent.candidate_id == "candidate-integrated"


def test_mapper_rejects_missing_execution_references() -> None:
    with pytest.raises(ValueError, match="entry_reference"):
        map_strategy_candidate(
            _strategy_candidate(),
            candidate_id="candidate-integrated",
            signal_id="signal-integrated",
            asset_class=AssetClass.FOREX,
            candidate_expiry=NOW + timedelta(minutes=4),
            entry_reference=None,
            stop_reference=Decimal("95"),
            target_reference=None,
            bid=Decimal("99.9"),
            ask=Decimal("100"),
            volatility_or_atr=Decimal("2"),
            market_status=RiskMarketStatus.TRADEABLE,
            holding_state=False,
        )


def test_risk_package_has_no_broker_http_ai_or_credential_dependency() -> None:
    corpus = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "src" / "trading_desk" / "risk").glob("*.py")
    ).lower()
    prohibited = (
        "import httpx",
        "trading_desk.ig",
        "openai",
        "ai provider",
        "secretstr",
        "from_environment",
        "load_dotenv",
    )

    assert all(value not in corpus for value in prohibited)


def test_risk_package_contains_no_runtime_order_operation_surface() -> None:
    corpus = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "src" / "trading_desk" / "risk").glob("*.py")
    ).lower()
    prohibited = (
        "place_order",
        "preview_order",
        "execute_order",
        "close_position",
        "/positions/otc",
        "/working-orders/otc",
    )

    assert all(value not in corpus for value in prohibited)
