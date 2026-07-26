"""Equity-paper dashboard endpoint: projects the mini PC files read-only."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from trading_desk.api.equity_paper import attach_equity_paper
from trading_desk.confidence import CalibrationLedger


def _client(paper_dir: Path) -> TestClient:
    app = FastAPI()
    attach_equity_paper(app, paper_dir)
    return TestClient(app)


def test_unavailable_when_no_journal(tmp_path: Path) -> None:
    response = _client(tmp_path).get("/api/v1/equity-paper/summary")
    assert response.status_code == 200
    body = response.json()
    assert body["available"] is False


def test_summary_projects_sessions_and_confidence(tmp_path: Path) -> None:
    rows = [
        {"type": "rejection", "session": "2026-07-21", "symbol": "X", "codes": ["A"]},
        {
            "type": "session",
            "session": "2026-07-21",
            "equity": "1000",
            "positions": 0,
            "exits_queued": 0,
            "entries_approved": 47,
            "entries_rejected": {"NEWS_OR_CORPORATE_EVENT": 15},
            "gross_target": "0.375",
        },
        {
            "type": "session",
            "session": "2026-07-22",
            "equity": "1002.6689",
            "positions": 47,
            "exits_queued": 0,
            "target_exits": 1,
            "entries_approved": 3,
            "entries_rejected": {},
            "gross_target": "0.375",
        },
    ]
    (tmp_path / "journal.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows), encoding="utf-8"
    )
    ledger = CalibrationLedger(tmp_path / "confidence_calibration.jsonl")
    ledger.record(
        trade_id="AAA-2026-07-21",
        symbol="AAA",
        confidence=0.72,
        bucket="high",
        outcome_r=1.8,
        opened="2026-07-21",
        closed="2026-07-22",
    )
    (tmp_path / "confidence_positions.json").write_text(
        json.dumps({"BBB": {"confidence": 0.61, "bucket": "elevated", "target_r": 2.4}}),
        encoding="utf-8",
    )

    body = _client(tmp_path).get("/api/v1/equity-paper/summary").json()
    assert body["available"] is True
    assert body["authority"] == "READ ONLY"
    assert body["last_session"] == "2026-07-22"
    assert body["equity"] == 1002.6689
    assert len(body["sessions"]) == 2  # rejection rows are not sessions
    assert body["sessions"][1]["target_exits"] == 1
    assert body["confidence_buckets"] == [
        {"bucket": "high", "n": 1, "win_rate": 1.0, "expectancy_r": 1.8, "payoff_ratio": 0.0}
    ]
    assert body["open_position_confidence"]["BBB"]["bucket"] == "elevated"
