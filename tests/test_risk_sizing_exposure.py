from __future__ import annotations

from decimal import Decimal

import pytest
from tests.risk_helpers import EPIC, NOW, account, candidate, market

from trading_desk.risk.config import RiskConfiguration
from trading_desk.risk.engine import RiskEngine
from trading_desk.risk.models import (
    AssetClass,
    ExposureAmount,
    PositionCount,
    RiskDecisionStatus,
    RiskReasonCode,
)
from trading_desk.risk.sizing import round_quantity_down


def evaluate(
    *,
    candidate_updates: dict[str, object] | None = None,
    account_updates: dict[str, object] | None = None,
    market_updates: dict[str, object] | None = None,
    configuration: RiskConfiguration | None = None,
):
    return RiskEngine(configuration).evaluate(
        candidate(**(candidate_updates or {})),
        account(**(account_updates or {})),
        market(**(market_updates or {})),
        NOW,
    )


def test_normal_decimal_sizing_and_final_recalculation() -> None:
    decision = evaluate()

    assert decision.status is RiskDecisionStatus.APPROVED
    assert decision.risk_budget == Decimal("1000")
    assert decision.proposed_quantity == Decimal("200")
    assert decision.approved_quantity == Decimal("200")
    assert decision.risk_amount == Decimal("1000")
    assert decision.risk_fraction == Decimal("0.01")
    assert decision.notional_exposure == Decimal("20000")


def test_quantity_rounds_down_never_up() -> None:
    decision = evaluate(candidate_updates={"stop_reference": Decimal("94")})

    assert decision.proposed_quantity == Decimal("166.6666666666666666666666667")
    assert decision.approved_quantity == Decimal("166.66")
    assert decision.risk_amount == Decimal("999.96")
    assert round_quantity_down(Decimal("1.239"), Decimal("0.01")) == Decimal("1.23")


def test_market_increment_and_maximum_quantity_constrain_approval() -> None:
    incremented = evaluate(market_updates={"quantity_increment": Decimal("0.03")})
    capped = evaluate(configuration=RiskConfiguration(maximum_approved_quantity=Decimal("10")))

    assert incremented.approved_quantity == Decimal("199.98")
    assert capped.approved_quantity == Decimal("10")


def test_incompatible_quantity_increment_rejects() -> None:
    config = RiskConfiguration(quantity_increment=Decimal("0.02"))
    decision = evaluate(
        configuration=config,
        market_updates={"quantity_increment": Decimal("0.03")},
    )

    assert RiskReasonCode.INVALID_QUANTITY_INCREMENT in decision.reason_codes


def test_minimum_deal_size_and_insufficient_capital_fail_closed() -> None:
    minimum = evaluate(market_updates={"minimum_deal_size": Decimal("250")})
    capital = evaluate(account_updates={"available_capital": Decimal("0.50")})

    assert RiskReasonCode.SIZE_BELOW_MINIMUM in minimum.reason_codes
    assert RiskReasonCode.SIZE_BELOW_MINIMUM in capital.reason_codes
    assert RiskReasonCode.INSUFFICIENT_AVAILABLE_CAPITAL in capital.reason_codes


def test_small_valid_stop_is_capped_by_exposure_and_large_stop_rejects() -> None:
    small = evaluate(
        candidate_updates={"stop_reference": Decimal("99.9999")},
        market_updates={"minimum_stop_distance": Decimal("0.0001")},
    )
    large = evaluate(candidate_updates={"stop_reference": Decimal("70")})

    assert small.status is RiskDecisionStatus.APPROVED
    assert small.approved_quantity == Decimal("200")
    assert small.risk_amount == Decimal("0.0200")
    assert RiskReasonCode.STOP_TOO_FAR in large.reason_codes


@pytest.mark.parametrize(
    ("realized", "unrealized", "configuration", "reason", "approved"),
    [
        (
            Decimal("-3000"),
            Decimal("0"),
            RiskConfiguration(),
            RiskReasonCode.DAILY_REALIZED_LOSS_LIMIT_REACHED,
            False,
        ),
        (Decimal("-2999.99"), Decimal("0"), RiskConfiguration(), None, True),
        (
            Decimal("-2000"),
            Decimal("-3000"),
            RiskConfiguration(),
            RiskReasonCode.DAILY_TOTAL_LOSS_LIMIT_REACHED,
            False,
        ),
        (
            Decimal("0"),
            None,
            RiskConfiguration(include_unrealized_in_daily_loss=False),
            None,
            True,
        ),
    ],
)
def test_daily_loss_policies(
    realized: Decimal,
    unrealized: Decimal | None,
    configuration: RiskConfiguration,
    reason: RiskReasonCode | None,
    approved: bool,
) -> None:
    decision = evaluate(
        account_updates={"realized_daily_pnl": realized, "unrealized_pnl": unrealized},
        configuration=configuration,
    )

    assert (decision.status is RiskDecisionStatus.APPROVED) is approved
    if reason is not None:
        assert reason in decision.reason_codes


def test_missing_required_pnl_state_fails_closed() -> None:
    decision = evaluate(account_updates={"unrealized_pnl": None})

    assert RiskReasonCode.ACCOUNT_STATE_UNKNOWN in decision.reason_codes


@pytest.mark.parametrize(
    ("drawdown", "approved"),
    [(Decimal("0.0999"), True), (Decimal("0.10"), False), (Decimal("0.1001"), False)],
)
def test_drawdown_boundary(drawdown: Decimal, approved: bool) -> None:
    decision = evaluate(account_updates={"current_drawdown_fraction": drawdown})

    assert (decision.status is RiskDecisionStatus.APPROVED) is approved
    if not approved:
        assert RiskReasonCode.DRAWDOWN_LIMIT_REACHED in decision.reason_codes


@pytest.mark.parametrize(
    ("account_updates", "reason"),
    [
        (
            {"gross_exposure": Decimal("100000")},
            RiskReasonCode.GROSS_EXPOSURE_LIMIT,
        ),
        (
            {"instrument_exposure": (ExposureAmount(key=EPIC, amount=Decimal("20000")),)},
            RiskReasonCode.INSTRUMENT_EXPOSURE_LIMIT,
        ),
        (
            {
                "asset_class_exposure": (
                    ExposureAmount(key=AssetClass.FOREX.value, amount=Decimal("50000")),
                )
            },
            RiskReasonCode.ASSET_CLASS_EXPOSURE_LIMIT,
        ),
    ],
)
def test_projected_exposure_without_minimum_capacity_rejects(
    account_updates: dict[str, object], reason: RiskReasonCode
) -> None:
    decision = evaluate(account_updates=account_updates)

    assert decision.status is RiskDecisionStatus.REJECTED
    assert reason in decision.reason_codes


def test_projected_exposure_exact_boundary_passes() -> None:
    decision = evaluate()

    assert decision.status is RiskDecisionStatus.APPROVED
    assert decision.notional_exposure == Decimal("20000")


@pytest.mark.parametrize(
    ("updates", "reason"),
    [
        ({"open_position_count": 5}, RiskReasonCode.MAX_OPEN_POSITIONS_REACHED),
        (
            {"instrument_position_count": (PositionCount(key=EPIC, count=1),)},
            RiskReasonCode.MAX_INSTRUMENT_POSITIONS_REACHED,
        ),
    ],
)
def test_position_count_limits(updates: dict[str, object], reason: RiskReasonCode) -> None:
    decision = evaluate(account_updates=updates)

    assert reason in decision.reason_codes


@pytest.mark.parametrize(("losses", "approved"), [(2, True), (3, False), (4, False)])
def test_consecutive_loss_boundaries(losses: int, approved: bool) -> None:
    decision = evaluate(account_updates={"consecutive_losses": losses})

    assert (decision.status is RiskDecisionStatus.APPROVED) is approved
    if not approved:
        assert RiskReasonCode.MAX_CONSECUTIVE_LOSSES_REACHED in decision.reason_codes


def test_consecutive_loss_policy_can_be_disabled_explicitly() -> None:
    config = RiskConfiguration(consecutive_loss_limit_enabled=False)
    decision = evaluate(account_updates={"consecutive_losses": 100}, configuration=config)

    assert decision.status is RiskDecisionStatus.APPROVED
