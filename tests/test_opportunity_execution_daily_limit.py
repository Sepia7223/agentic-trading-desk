from __future__ import annotations

import asyncio
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import cast

import pytest
from pydantic import ValidationError
from tests.execution_helpers import (
    FakeExecutionBroker,
    enabled_configuration,
    request_and_confirmation,
)
from tests.risk_helpers import NOW, account, candidate, market

from trading_desk import cli
from trading_desk.execution.config import ExecutionConfiguration
from trading_desk.execution.engine import ExecutionEngine
from trading_desk.execution.errors import ExecutionBrokerError
from trading_desk.execution.idempotency import ExecutionIdempotencyStore
from trading_desk.execution.models import (
    ExecutionReasonCode,
    ExecutionStatus,
    PreflightStatus,
)
from trading_desk.execution.opportunity import ControlledOpportunityAuthority
from trading_desk.execution.preflight import run_preflight
from trading_desk.ig.execution import IGDemoExecutionAdapter
from trading_desk.opportunity.campaign import campaign_snapshot
from trading_desk.opportunity.config import (
    DemoCampaignConfiguration,
    DemoExplorationConfiguration,
    OpportunityEngineConfiguration,
)
from trading_desk.opportunity.exposure import CurrentExposureSnapshot
from trading_desk.opportunity.fingerprints import fingerprint
from trading_desk.opportunity.ledger import DemoTradeLedger, DemoTradeStatus
from trading_desk.opportunity.preflight import (
    ExplorationRejectionCode,
    exploration_preflight,
)
from trading_desk.risk.engine import RiskEngine


def _execution_preflight(orders_today: int):  # type: ignore[no-untyped-def]
    configuration = enabled_configuration(maximum_orders_per_day=20)
    request, confirmation, decision = request_and_confirmation(configuration=configuration)
    return run_preflight(
        request=request,
        decision=decision,
        candidate=candidate(),
        account=account(),
        market=market(),
        positions=(),
        confirmation=confirmation,
        evaluation_timestamp=NOW,
        configuration=configuration,
        risk_engine=RiskEngine(),
        idempotency=ExecutionIdempotencyStore(),
        orders_today=orders_today,
    )


@pytest.mark.parametrize("submitted", (0, 1, 19))
def test_shared_daily_limit_allows_submission_below_twenty(submitted: int) -> None:
    result = _execution_preflight(submitted)
    assert result.status is PreflightStatus.READY
    assert ExecutionReasonCode.MAX_ORDERS_PER_DAY_REACHED not in result.reason_codes


def test_shared_daily_limit_rejects_twenty_first_submission() -> None:
    result = _execution_preflight(20)
    assert result.status is PreflightStatus.REJECTED
    assert ExecutionReasonCode.MAX_ORDERS_PER_DAY_REACHED in result.reason_codes


def test_execution_configuration_supports_governed_exploration_limit() -> None:
    assert ExecutionConfiguration(maximum_orders_per_day=20).maximum_orders_per_day == 20
    with pytest.raises(ValidationError):
        ExecutionConfiguration(maximum_orders_per_day=101)


def _append_submission(ledger: DemoTradeLedger, sequence: int) -> None:
    ledger.append(
        ledger.create_record(
            occurred_at=NOW + timedelta(seconds=sequence),
            status=DemoTradeStatus.SUBMITTED,
            strategy="trend-regime-v1",
            instrument="EUR/USD",
            timeframe="MINUTE_5",
            regime="BULL_LOW_VOL",
            session="LONDON",
            candidate_id=f"candidate-{sequence}",
            execution_id=f"execution-{sequence}",
        )
    )


def test_twenty_submissions_remain_exhausted_after_restart(tmp_path: Path) -> None:
    path = tmp_path / "trade-ledger.json"
    ledger = DemoTradeLedger(path)
    for sequence in range(20):
        _append_submission(ledger, sequence)

    restarted = DemoTradeLedger(path)
    assert restarted.submitted_on(NOW.date()) == 20
    result = _execution_preflight(restarted.submitted_on(NOW.date()))
    assert result.status is PreflightStatus.REJECTED
    assert ExecutionReasonCode.MAX_ORDERS_PER_DAY_REACHED in result.reason_codes


def test_opportunity_and_execution_preflights_share_exact_daily_boundary(
    tmp_path: Path,
) -> None:
    from opportunity_helpers import candidate as opportunity_candidate

    ledger = DemoTradeLedger(tmp_path / "trade-ledger.json")
    for sequence in range(19):
        _append_submission(ledger, sequence)
    exploration = DemoExplorationConfiguration(enabled=True, maximum_trades_per_day=20)
    exposure_fields = {"observed_at": NOW, "positions": (), "recently_closed": ()}
    exposure = CurrentExposureSnapshot(
        **exposure_fields,
        snapshot_fingerprint=fingerprint(exposure_fields),
    )
    campaign = campaign_snapshot(
        campaign_id="campaign",
        campaign_name="Demo",
        started_at=NOW - timedelta(days=1),
        observed_at=NOW,
        current_balance=Decimal("20000"),
        current_equity=Decimal("20000"),
        maximum_equity=Decimal("20000"),
        daily_pnl=Decimal("0"),
        weekly_drawdown_percent=Decimal("0"),
        consecutive_losses=0,
        configuration=DemoCampaignConfiguration(enabled=True),
        starting_balance=Decimal("20000"),
    )

    opportunity_at_19 = exploration_preflight(
        opportunity_candidate(),
        observed_at=NOW,
        engine=OpportunityEngineConfiguration(enabled=True),
        exploration=exploration,
        explicit_authorization=True,
        exposure=exposure,
        ledger=ledger,
        campaign=campaign,
    )
    assert opportunity_at_19.ready
    assert _execution_preflight(19).status is PreflightStatus.READY

    _append_submission(ledger, 19)
    opportunity_at_20 = exploration_preflight(
        opportunity_candidate(),
        observed_at=NOW,
        engine=OpportunityEngineConfiguration(enabled=True),
        exploration=exploration,
        explicit_authorization=True,
        exposure=exposure,
        ledger=ledger,
        campaign=campaign,
    )
    assert not opportunity_at_20.ready
    assert ExplorationRejectionCode.DAILY_TRADE_LIMIT in opportunity_at_20.rejection_codes
    assert _execution_preflight(20).status is PreflightStatus.REJECTED


def test_ambiguous_submission_consumes_persisted_daily_slot(tmp_path: Path) -> None:
    path = tmp_path / "trade-ledger.json"
    ledger = DemoTradeLedger(path)
    configuration = enabled_configuration(maximum_orders_per_day=20)
    request, confirmation, decision = request_and_confirmation(configuration=configuration)
    broker = FakeExecutionBroker(
        failure=ExecutionBrokerError("safe timeout", operation="open_position", ambiguous=True)
    )

    def persist_submission() -> None:
        _append_submission(ledger, 0)

    outcome = asyncio.run(
        ExecutionEngine(
            broker,
            configuration=configuration,
            before_submission=persist_submission,
        ).execute(
            request=request,
            decision=decision,
            candidate=candidate(),
            account=account(),
            market=market(),
            positions=(),
            confirmation=confirmation,
            evaluation_timestamp=NOW,
            orders_today=ledger.submitted_on(NOW.date()),
        )
    )

    assert outcome.result.status is ExecutionStatus.RECONCILIATION_REQUIRED
    assert broker.submission_calls == 1
    assert DemoTradeLedger(path).submitted_on(NOW.date()) == 1


def test_authority_uses_exact_immutable_exploration_limit(tmp_path: Path) -> None:
    configuration = DemoExplorationConfiguration(enabled=True, maximum_trades_per_day=20)
    authority = ControlledOpportunityAuthority(
        cast(IGDemoExecutionAdapter, object()),
        DemoTradeLedger(tmp_path / "ledger.json"),
        configuration,
    )
    assert authority.exploration_configuration is configuration
    assert authority.maximum_orders_per_day == 20


def test_cli_composition_passes_exploration_configuration(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    received: list[DemoExplorationConfiguration] = []

    class CapturingAuthority:
        def __init__(self, broker, ledger, configuration):  # type: ignore[no-untyped-def]
            del broker, ledger
            received.append(configuration)

    monkeypatch.setattr(cli, "ControlledOpportunityAuthority", CapturingAuthority)
    configuration = DemoExplorationConfiguration(enabled=True, maximum_trades_per_day=20)
    result = cli._create_controlled_opportunity_authority(  # noqa: SLF001
        cast(IGDemoExecutionAdapter, object()),
        DemoTradeLedger(tmp_path / "ledger.json"),
        configuration,
    )

    assert isinstance(result, CapturingAuthority)
    assert received == [configuration]
