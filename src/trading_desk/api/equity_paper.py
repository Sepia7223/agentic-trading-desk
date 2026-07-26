"""Read-only monitoring endpoints for the EQUITY paper account.

The $1,000 equity paper account (mini PC nightly session) writes plain
files under data/paper/ - a separate, simpler store from the governed
journal the rest of the Operations Center reads. These endpoints project
those files for the dashboard: session history (equity curve), the
current book, and the confidence-calibration table ('how often does each
confidence bucket actually work'). Strictly GET; missing files degrade to
available=false, never an error.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from trading_desk.confidence import CalibrationLedger


def _sessions(journal_path: Path) -> list[dict[str, Any]]:
    if not journal_path.exists():
        return []
    sessions: list[dict[str, Any]] = []
    for line in journal_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("type") != "session":
            continue
        sessions.append(
            {
                "session": row.get("session"),
                "equity": float(row.get("equity", 0)),
                "positions": row.get("positions"),
                "entries_approved": row.get("entries_approved"),
                "exits_queued": row.get("exits_queued"),
                "target_exits": row.get("target_exits", 0),
                "entries_rejected": row.get("entries_rejected", {}),
                "gross_target": row.get("gross_target"),
            }
        )
    return sessions


def attach_equity_paper(app: FastAPI, paper_dir: Path) -> None:
    @app.get("/api/v1/equity-paper/summary")
    async def equity_paper_summary():  # type: ignore[no-untyped-def]
        journal_path = paper_dir / "journal.jsonl"
        sessions = _sessions(journal_path)
        if not sessions:
            return {
                "available": False,
                "reason": f"no equity-paper session journal at {journal_path}",
            }
        buckets: list[dict[str, Any]] = []
        if (paper_dir / "confidence_calibration.jsonl").exists():
            ledger = CalibrationLedger(paper_dir / "confidence_calibration.jsonl")
            buckets = [
                {
                    "bucket": s.bucket,
                    "n": s.n,
                    "win_rate": round(s.win_rate, 4),
                    "expectancy_r": round(s.expectancy_r, 4),
                    "payoff_ratio": round(s.payoff_ratio, 4),
                }
                for s in ledger.report()
            ]
        sidecar_path = paper_dir / "confidence_positions.json"
        open_confidence: dict[str, Any] = (
            json.loads(sidecar_path.read_text(encoding="utf-8")) if sidecar_path.exists() else {}
        )
        latest = sessions[-1]
        return {
            "available": True,
            "environment": "EQUITY PAPER (mini PC nightly)",
            "authority": "READ ONLY",
            "last_session": latest["session"],
            "equity": latest["equity"],
            "positions": latest["positions"],
            "gross_target": latest["gross_target"],
            "sessions": sessions,
            "confidence_buckets": buckets,
            "open_position_confidence": open_confidence,
        }
