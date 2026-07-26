"""Read-only desk API: projects the REAL mini PC data for the dashboard.

The governed IG/FX Operations views read the SQLite journal, which is
empty on this machine because that program is dormant here. Everything a
supervisor actually needs lives in plain files: the equity paper account
(data/paper), the forward shadow evidence (data/shadow) and the research
verdicts (data/pit). These endpoints serve all of it, strictly GET,
fail-soft on missing files.
"""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from trading_desk.confidence import CalibrationLedger


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return dict(json.loads(path.read_text(encoding="utf-8")))


def _sessions(journal_path: Path) -> list[dict[str, Any]]:
    sessions: list[dict[str, Any]] = []
    for row in _read_jsonl(journal_path):
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
                "news_exits": row.get("news_exits", 0),
                "entries_rejected": row.get("entries_rejected", {}),
                "gross_target": row.get("gross_target"),
            }
        )
    return sessions


def attach_equity_paper(app: FastAPI, paper_dir: Path) -> None:
    data_root = Path(paper_dir).parent
    shadow_dir = data_root / "shadow"
    pit_dir = data_root / "pit"

    @app.get("/api/v1/equity-paper/summary")
    async def equity_paper_summary():  # type: ignore[no-untyped-def]
        sessions = _sessions(paper_dir / "journal.jsonl")
        if not sessions:
            return {
                "available": False,
                "reason": f"no equity-paper session journal under {paper_dir}",
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
        open_confidence = _read_json(paper_dir / "confidence_positions.json") or {}
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

    @app.get("/api/v1/equity-paper/positions")
    async def equity_paper_positions():  # type: ignore[no-untyped-def]
        state = _read_json(paper_dir / "paper_state.json")
        if state is None:
            return {"available": False, "reason": "no paper state"}
        marks_doc = _read_json(paper_dir / "marks.json") or {}
        marks = marks_doc.get("marks", {})
        sidecar = _read_json(paper_dir / "confidence_positions.json") or {}
        rows = []
        long_pnl = short_pnl = 0.0
        winners = losers = 0
        for sym, pos in sorted(state.get("positions", {}).items()):
            qty = float(pos["quantity"])
            entry = float(pos["entry_price"])
            mark = marks.get(sym, {}).get("price")
            pnl = pnl_pct = None
            if mark is not None:
                pnl = (float(mark) - entry) * qty
                pnl_pct = (float(mark) / entry - 1) * (1 if qty > 0 else -1)
                if qty > 0:
                    long_pnl += pnl
                else:
                    short_pnl += pnl
                if pnl >= 0:
                    winners += 1
                else:
                    losers += 1
            meta = sidecar.get(sym, {})
            rows.append(
                {
                    "symbol": sym,
                    "side": "LONG" if qty > 0 else "SHORT",
                    "quantity": qty,
                    "entry": round(entry, 4),
                    "mark": round(float(mark), 4) if mark is not None else None,
                    "pnl": round(pnl, 4) if pnl is not None else None,
                    "pnl_pct": round(pnl_pct, 4) if pnl_pct is not None else None,
                    "confidence": meta.get("confidence"),
                    "target_r": meta.get("target_r"),
                }
            )
        rows.sort(key=lambda r: (r["pnl"] is None, -(r["pnl"] or 0)))
        return {
            "available": True,
            "marked_at": marks_doc.get("refreshed_at"),
            "winners": winners,
            "losers": losers,
            "long_pnl": round(long_pnl, 2),
            "short_pnl": round(short_pnl, 2),
            "positions": rows,
        }

    @app.get("/api/v1/equity-paper/journal")
    async def equity_paper_journal(limit: int = 60):  # type: ignore[no-untyped-def]
        rows = _read_jsonl(paper_dir / "journal.jsonl")
        return {"rows": rows[-max(1, min(limit, 500)) :][::-1]}

    @app.get("/api/v1/evidence/shadow")
    async def shadow_evidence():  # type: ignore[no-untyped-def]
        def stream(name: str, path: Path) -> dict[str, Any]:
            rows = _read_jsonl(path)
            points = []
            cumulative = 0.0
            for r in rows:
                cumulative += float(r.get("net", 0.0))
                points.append(
                    {"date": r.get("date"), "net": r.get("net"), "cum": round(cumulative, 6)}
                )
            return {
                "name": name,
                "n": len(points),
                "cumulative": round(cumulative, 6),
                "latest": points[-1] if points else None,
                "points": points,
            }

        return {
            "decision_date": "2026-09-15",
            "streams": [
                stream(
                    "Short-volume sleeve (composite forward proof)",
                    shadow_dir / "shortvol_forward.jsonl",
                ),
                stream(
                    "DTC challenge book (prop decision forward proof)",
                    shadow_dir / "dtc_cfd_forward.jsonl",
                ),
            ],
        }

    @app.get("/api/v1/research/challenge")
    async def research_challenge():  # type: ignore[no-untyped-def]
        docs = {
            "short_interest_gauntlet": _read_json(pit_dir / "short_interest_result.json"),
            "short_interest_analysis": _read_json(pit_dir / "short_interest_analysis.json"),
            "challenge_dtc_variant": _read_json(pit_dir / "challenge_dtc_variant_result.json"),
            "challenge_momentum_variant": _read_json(pit_dir / "challenge_cfd_variant_result.json"),
            "challenge_shortvol_variant": _read_json(
                pit_dir / "challenge_shortvol_variant_result.json"
            ),
        }
        return {
            "decision_date": "2026-09-15",
            "fee_plan": "FTMO 2-Step Swing $100k, ~EUR 540, budget cap $1,650 (3 attempts max)",
            "status": "WAIT FOR FORWARD PROOF (user decision 2026-07-24)",
            "documents": {k: v for k, v in docs.items() if v is not None},
        }

    @app.get("/api/v1/ops/desk")
    async def desk_ops():  # type: ignore[no-untyped-def]
        sessions = _sessions(paper_dir / "journal.jsonl")
        latest = sessions[-1] if sessions else None
        rejections: dict[str, int] = {}
        news_exit_count = 0
        for row in _read_jsonl(paper_dir / "journal.jsonl"):
            if row.get("type") == "rejection":
                key = str(row.get("session"))
                rejections[key] = rejections.get(key, 0) + 1
            if row.get("type") == "held_news_exit":
                news_exit_count += 1
        jobs = []
        for label, path in (
            ("paper session", paper_dir / "session.log"),
            ("short-volume shadow", shadow_dir / "shadow.log"),
            ("DTC shadow", shadow_dir / "shadow_dtc.log"),
            ("marks refresh", paper_dir / "marks.json"),
        ):
            jobs.append(
                {
                    "job": label,
                    "last_output": (
                        datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).isoformat()
                        if path.exists()
                        else None
                    ),
                }
            )
        usage = shutil.disk_usage(Path.cwd())
        return {
            "equity": latest["equity"] if latest else None,
            "last_session": latest["session"] if latest else None,
            "open_positions": latest["positions"] if latest else None,
            "sessions_recorded": len(sessions),
            "held_news_exits_total": news_exit_count,
            "rejections_by_session": dict(sorted(rejections.items())[-7:]),
            "jobs": jobs,
            "disk_free_gb": round(usage.free / 1e9, 1),
            "disk_used_pct": round(100 * usage.used / usage.total, 1),
        }
