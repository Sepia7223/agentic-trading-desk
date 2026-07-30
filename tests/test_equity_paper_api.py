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


def test_positions_with_marks_and_ops(tmp_path: Path) -> None:
    paper = tmp_path / "paper"
    paper.mkdir()
    (paper / "paper_state.json").write_text(
        json.dumps(
            {
                "positions": {
                    "AAA": {"quantity": "2", "entry_price": "10"},
                    "BBB": {"quantity": "-1", "entry_price": "50"},
                }
            }
        ),
        encoding="utf-8",
    )
    (paper / "marks.json").write_text(
        json.dumps(
            {
                "refreshed_at": "2026-07-25T00:00:00+00:00",
                "marks": {"AAA": {"price": 11.0}, "BBB": {"price": 55.0}},
            }
        ),
        encoding="utf-8",
    )
    (paper / "journal.jsonl").write_text(
        json.dumps(
            {
                "type": "session",
                "session": "2026-07-24",
                "equity": "997",
                "positions": 2,
                "entries_approved": 1,
                "exits_queued": 0,
                "entries_rejected": {},
                "gross_target": "0.375",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    client = _client(paper)

    body = client.get("/api/v1/equity-paper/positions").json()
    assert body["available"] is True
    assert body["winners"] == 1 and body["losers"] == 1
    aaa = next(r for r in body["positions"] if r["symbol"] == "AAA")
    assert aaa["pnl"] == 2.0 and aaa["side"] == "LONG"
    bbb = next(r for r in body["positions"] if r["symbol"] == "BBB")
    assert bbb["pnl"] == -5.0 and bbb["pnl_pct"] == -0.1

    ops = client.get("/api/v1/ops/desk").json()
    assert ops["equity"] == 997.0
    assert ops["sessions_recorded"] == 1
    assert ops["disk_free_gb"] > 0

    journal = client.get("/api/v1/equity-paper/journal").json()
    assert journal["rows"][0]["type"] == "session"


def test_evidence_and_research_endpoints(tmp_path: Path) -> None:
    paper = tmp_path / "paper"
    shadow = tmp_path / "shadow"
    pit = tmp_path / "pit"
    for d in (paper, shadow, pit):
        d.mkdir()
    (shadow / "dtc_cfd_forward.jsonl").write_text(
        json.dumps({"date": "2026-07-23", "net": -0.0136})
        + "\n"
        + json.dumps({"date": "2026-07-24", "net": 0.002})
        + "\n",
        encoding="utf-8",
    )
    (pit / "challenge_dtc_variant_result.json").write_text(
        json.dumps({"sharpe_after_cfd_financing": 0.906, "dsr": 0.971}),
        encoding="utf-8",
    )
    client = _client(paper)

    evidence = client.get("/api/v1/evidence/shadow").json()
    dtc = next(s for s in evidence["streams"] if "DTC" in s["name"])
    assert dtc["n"] == 2
    assert dtc["points"][-1]["cum"] == -0.0116
    assert evidence["decision_date"] == "2026-09-15"

    research = client.get("/api/v1/research/challenge").json()
    assert research["documents"]["challenge_dtc_variant"]["dsr"] == 0.971
    assert "WAIT FOR FORWARD PROOF" in research["status"]
