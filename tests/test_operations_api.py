from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from journal_helpers import NOW, append_record, configuration
from trading_desk.api import create_operations_app
from trading_desk.journal.models import (
    JournalLineage,
    JournalQuery,
    JournalQueryResult,
    JournalRecord,
    JournalRecordType,
)
from trading_desk.journal.sqlite import SQLiteJournalRepository
from trading_desk.operations.config import OperationsConfiguration
from trading_desk.operations.errors import OperationsDisabledError
from trading_desk.operations.service import OperationsService

READ_ENDPOINTS = (
    "/api/v1/health",
    "/api/v1/system",
    "/api/v1/context/latest",
    "/api/v1/router/latest",
    "/api/v1/risk/latest",
    "/api/v1/evaluations",
    "/api/v1/why-no-trade",
    "/api/v1/portfolio",
    "/api/v1/positions/open",
    "/api/v1/trades",
    "/api/v1/execution",
    "/api/v1/lifecycle",
    "/api/v1/reviews",
    "/api/v1/ai-reviews",
    "/api/v1/alerts",
    "/api/v1/journal/status",
    f"/api/v1/replay?cutoff_at={NOW.isoformat().replace('+', '%2B')}",
    "/api/v1/search?q=EUR",
    "/api/v1/performance",
    "/api/v1/opportunities",
    "/api/v1/activity",
    "/api/v1/strategy-leaderboard",
    "/api/v1/instrument-performance",
    "/api/v1/regime-performance",
    "/api/v1/inactivity-diagnostics",
    "/api/v1/demo-campaign",
    "/api/v1/configuration",
    "/api/v1/exports",
)


class MemoryReader:
    def __init__(self, records: tuple[JournalRecord, ...] = ()) -> None:
        self.records = records

    def query(self, query: JournalQuery) -> JournalQueryResult:
        matches = tuple(
            record
            for record in self.records
            if (query.record_type is None or record.record_type is query.record_type)
            and (query.cutoff_at is None or record.effective_at <= query.cutoff_at)
        )
        page = matches[query.offset : query.offset + query.limit]
        next_offset = query.offset + len(page) if query.offset + len(page) < len(matches) else None
        return JournalQueryResult(
            records=page,
            total_matches=len(matches),
            next_offset=next_offset,
            query_fingerprint=query.query_fingerprint,
        )

    def lineage(self, source_record_id: str) -> JournalLineage:
        matches = tuple(
            record for record in self.records if record.source_record_id == source_record_id
        )
        return JournalLineage(
            requested_id=source_record_id,
            records=matches,
            missing_parent_ids=() if matches else (source_record_id,),
        )


def _records(
    tmp_path: Path, *definitions: tuple[str, JournalRecordType, dict[str, object]]
) -> tuple[JournalRecord, ...]:
    with SQLiteJournalRepository(configuration(tmp_path / "journal.db")) as repository:
        return tuple(
            append_record(repository, source_id, record_type=record_type, payload=payload)
            for source_id, record_type, payload in definitions
        )


def _client(reader: MemoryReader | None = None) -> TestClient:
    settings = OperationsConfiguration(enabled=True)
    service = OperationsService(reader or MemoryReader(), settings)
    return TestClient(create_operations_app(service, settings))


def test_api_refuses_to_start_when_operations_are_disabled() -> None:
    settings = OperationsConfiguration()
    service = OperationsService(MemoryReader(), settings)
    with pytest.raises(OperationsDisabledError, match="disabled"):
        create_operations_app(service, settings)


def test_all_read_only_endpoints_return_sanitized_results(tmp_path: Path) -> None:
    records = _records(
        tmp_path,
        ("signal-1", JournalRecordType.STRATEGY_SIGNAL, {"action": "NO_TRADE"}),
    )
    with _client(MemoryReader(records)) as client:
        for endpoint in READ_ENDPOINTS:
            response = client.get(endpoint)
            assert response.status_code in {200, 404}, endpoint
            body = response.text.lower()
            assert "password" not in body
            assert "authorization" not in body
            assert "access_token" not in body
        health = client.get("/api/v1/health").json()
        assert health["environment"] == "IG DEMO"
        assert health["authority"] == "READ ONLY"
        assert health["live_trading"] == "DISABLED"


def test_operational_mutation_methods_are_rejected(tmp_path: Path) -> None:
    del tmp_path
    with _client() as client:
        for method in ("post", "put", "patch", "delete"):
            response = client.request(method.upper(), "/api/v1/system", json={"action": "mutate"})
            assert response.status_code == 405


def test_pagination_limits_and_invalid_queries_are_sanitized(tmp_path: Path) -> None:
    records = _records(
        tmp_path,
        ("signal-1", JournalRecordType.STRATEGY_SIGNAL, {"action": "NO_TRADE"}),
    )
    with _client(MemoryReader(records)) as client:
        page = client.get("/api/v1/search?q=EUR&limit=1&offset=0")
        assert page.status_code == 200
        assert page.json()["total_matches"] == 1
        invalid = client.get("/api/v1/evaluations?limit=100000")
        assert invalid.status_code == 422
        assert "traceback" not in invalid.text.lower()


def test_websocket_delivers_initial_sanitized_health_event(tmp_path: Path) -> None:
    del tmp_path
    with _client() as client, client.websocket_connect("/ws/events") as websocket:
        event = websocket.receive_json()
        assert event["event_type"] == "SYSTEM_HEALTH_UPDATED"
        assert event["payload"]["environment"] == "IG DEMO"
        serialized = str(event).lower()
        assert "password" not in serialized
        assert "authorization" not in serialized


def test_trade_detail_missing_lineage_is_404(tmp_path: Path) -> None:
    del tmp_path
    with _client() as client:
        response = client.get("/api/v1/trades/unknown-trade")
        assert response.status_code == 404
        assert response.json()["detail"] == "trade evidence is unavailable"


def test_latest_context_returns_record_when_available(tmp_path: Path) -> None:
    records = _records(
        tmp_path,
        ("context-1", JournalRecordType.MARKET_CONTEXT, {"status": "AVAILABLE"}),
    )
    with _client(MemoryReader(records)) as client:
        response = client.get("/api/v1/context/latest")
        assert response.status_code == 200
        assert response.json()["source_record_id"] == "context-1"
