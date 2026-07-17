import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest

from trading_desk.operations.alerts import ALERT_SEVERITY, derive_alerts
from trading_desk.operations.config import OperationsConfiguration
from trading_desk.operations.events import OperationsEventBus
from trading_desk.operations.fingerprints import fingerprint
from trading_desk.operations.models import (
    OperationsEvent,
    OperationsEventType,
    RuntimeSubsystemHealth,
    SystemStatus,
)


def test_every_required_alert_has_stable_severity() -> None:
    assert set(ALERT_SEVERITY) == {
        "SCHEDULER_STOPPED",
        "SCHEDULER_STALE",
        "MARKET_DATA_STALE",
        "MARKET_CONTEXT_UNAVAILABLE",
        "EVENT_CONTEXT_UNAVAILABLE",
        "HOLIDAY_CONTEXT_UNAVAILABLE",
        "BROKER_DISCONNECTED",
        "BROKER_SESSION_EXPIRED",
        "JOURNAL_INTEGRITY_FAILURE",
        "JOURNAL_RECOVERY_REQUIRED",
        "KILL_SWITCH_ACTIVE",
        "DAILY_LOSS_LIMIT_REACHED",
        "DRAWDOWN_LIMIT_REACHED",
        "MAX_CONSECUTIVE_LOSSES_REACHED",
        "AUTOMATED_EXECUTION_HALTED",
        "BROKER_CONFIRMATION_UNKNOWN",
        "RECONCILIATION_REQUIRED",
        "RECONCILIATION_MISMATCH",
        "UNEXPECTED_OPEN_POSITION",
        "BACKUP_OVERDUE",
        "AI_PROVIDER_FAILURE",
    }


def test_alert_fingerprints_and_order_are_deterministic() -> None:
    now = datetime(2026, 7, 16, tzinfo=UTC)
    state = RuntimeSubsystemHealth(
        name="execution",
        status=SystemStatus.HALTED,
        observed_at=now,
        reason_codes=("RECONCILIATION_REQUIRED", "BROKER_CONFIRMATION_UNKNOWN"),
    )
    assert derive_alerts((state,), now) == derive_alerts((state,), now)
    assert all(alert.alert_id == alert.alert_fingerprint for alert in derive_alerts((state,), now))


def test_event_bus_delivers_ordered_immutable_events_and_cleans_up() -> None:
    async def scenario() -> None:
        bus = OperationsEventBus(OperationsConfiguration(maximum_websocket_clients=1))
        now = datetime(2026, 7, 16, tzinfo=UTC)
        fields = {
            "event_type": OperationsEventType.JOURNAL_STATUS_UPDATED,
            "created_at": now,
            "source_record_ids": (),
            "payload": {"status": "HEALTHY"},
        }
        identity = fingerprint(fields)
        event = OperationsEvent.model_validate(
            {**fields, "event_id": identity, "event_fingerprint": identity}
        )
        iterator = bus.subscribe()
        pending = asyncio.create_task(anext(iterator))
        await asyncio.sleep(0)
        bus.publish(event)
        assert await pending == event
        await iterator.aclose()
        assert bus.client_count == 0

    asyncio.run(scenario())


def test_operations_source_has_no_mutation_or_secret_dependencies() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "trading_desk"
    operations_source = "\n".join(
        path.read_text(encoding="utf-8")
        for package in (root / "operations", root / "api")
        for path in package.rglob("*.py")
    ).lower()
    forbidden = (
        "ig_identifier",
        "ig_password",
        "ig_api_key",
        "access_token",
        "refresh_token",
        "authorization header",
        "submit_order",
        "close_position",
        "amend_position",
        "switch_account",
        "riskengine",
        "paperportfolioengine",
        "durablejournalwriter",
    )
    for term in forbidden:
        assert term not in operations_source


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_api_defines_no_operational_mutation_routes(method: str) -> None:
    source = (
        Path(__file__).resolve().parents[1] / "src" / "trading_desk" / "api" / "app.py"
    ).read_text(encoding="utf-8")
    assert f"@app.{method}(" not in source.lower()
