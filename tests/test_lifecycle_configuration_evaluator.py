from datetime import timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from lifecycle_helpers import NOW, enabled_configuration, risk, snapshot
from trading_desk.lifecycle.config import LifecycleConfiguration
from trading_desk.lifecycle.evaluator import evaluate_exit
from trading_desk.lifecycle.models import (
    ExitDecisionStatus,
    ExitReason,
    LifecycleMarketStatus,
    StrategyExitState,
)


def evaluate(**updates: object):  # type: ignore[no-untyped-def]
    snap = updates.pop("snapshot", snapshot())
    risk_state = updates.pop("risk", risk())
    strategy = updates.pop("strategy_exit", StrategyExitState.HOLD)
    config = updates.pop("configuration", enabled_configuration())
    return evaluate_exit(snap, risk_state, strategy, NOW, config, **updates)  # type: ignore[arg-type]


def test_configuration_defaults_are_disabled_demo_long_full_close_only() -> None:
    config = LifecycleConfiguration()
    assert not config.enabled
    assert not config.automatic_exit_enabled
    assert config.broker_environment.value == "DEMO"
    assert config.allow_full_close
    assert not config.allow_partial_close
    assert not config.allow_short_positions
    assert not config.allow_position_amendment
    assert not config.allow_live_trading
    assert config.stop_after_ambiguous_close


def test_configuration_is_immutable_and_fingerprint_stable() -> None:
    first = LifecycleConfiguration()
    assert first.configuration_fingerprint == LifecycleConfiguration().configuration_fingerprint
    with pytest.raises(ValidationError):
        first.enabled = True  # type: ignore[misc]


@pytest.mark.parametrize(
    "updates",
    [
        {"broker_environment": "LIVE"},
        {"allow_live_trading": True},
        {"allow_short_positions": True},
        {"allow_partial_close": True},
        {"allow_position_amendment": True},
        {"demo_gateway": "https://api.ig.com/gateway/deal"},
        {"maximum_market_data_age": 1.5},
    ],
)
def test_configuration_rejects_unsafe_values(updates: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        LifecycleConfiguration.model_validate(updates)


def test_hold_is_deterministic() -> None:
    assert evaluate() == evaluate()
    assert evaluate().status is ExitDecisionStatus.HOLD


def test_protective_stop_uses_bid() -> None:
    result = evaluate(snapshot=snapshot(current_bid=Decimal("95"), current_mark=Decimal("95")))
    assert result.primary_reason is ExitReason.PROTECTIVE_STOP


def test_profit_target_uses_bid() -> None:
    result = evaluate(
        snapshot=snapshot(
            current_bid=Decimal("110"),
            current_ask=Decimal("110.1"),
            current_mark=Decimal("110"),
        )
    )
    assert result.primary_reason is ExitReason.PROFIT_TARGET


def test_stop_precedes_target_under_ambiguous_levels() -> None:
    result = evaluate(
        snapshot=snapshot(
            current_bid=Decimal("100"),
            current_ask=Decimal("100.1"),
            current_mark=Decimal("100"),
            stop_level=Decimal("101"),
            target_level=Decimal("99"),
        )
    )
    assert result.primary_reason is ExitReason.PROTECTIVE_STOP
    assert ExitReason.PROFIT_TARGET in result.secondary_reasons


def test_strategy_and_maximum_holding_exits() -> None:
    assert (
        evaluate(strategy_exit=StrategyExitState.EXIT).primary_reason
        is ExitReason.STRATEGY_INVALIDATED
    )
    result = evaluate(
        snapshot=snapshot(holding_duration=timedelta(days=31)),
        configuration=enabled_configuration(maximum_position_age=timedelta(days=30)),
    )
    assert result.primary_reason is ExitReason.MAXIMUM_HOLDING_PERIOD


@pytest.mark.parametrize(
    ("risk_updates", "reason"),
    [
        ({"kill_switch_active": True}, ExitReason.KILL_SWITCH),
        ({"emergency_exit_required": True}, ExitReason.EMERGENCY_OPERATOR_POLICY),
        ({"daily_loss_limit_reached": True}, ExitReason.DAILY_LOSS_LIMIT),
        ({"drawdown_limit_reached": True}, ExitReason.DRAWDOWN_LIMIT),
        ({"risk_limit_breached": True}, ExitReason.RISK_LIMIT_BREACH),
    ],
)
def test_risk_exit_precedence(risk_updates: dict[str, object], reason: ExitReason) -> None:
    result = evaluate(risk=risk(**risk_updates))
    assert result.primary_reason is reason
    assert result.status is ExitDecisionStatus.EMERGENCY_EXIT_REQUIRED


def test_stale_or_unknown_state_fails_closed() -> None:
    stale = evaluate(snapshot=snapshot(market_timestamp=NOW - timedelta(minutes=2)))
    assert stale.status is ExitDecisionStatus.INVALID_STATE
    assert stale.primary_reason is ExitReason.DATA_STALE
    unknown = evaluate(risk=risk(state_complete=False))
    assert unknown.status is ExitDecisionStatus.INVALID_STATE


def test_required_exit_is_blocked_when_market_closed() -> None:
    result = evaluate(
        snapshot=snapshot(
            current_bid=Decimal("94"),
            current_mark=Decimal("94"),
            market_status=LifecycleMarketStatus.CLOSED,
        )
    )
    assert result.status is ExitDecisionStatus.EXIT_BLOCKED
