"""Append-only artifact store + forward calibration log.

Artifacts are recorded as JSONL, never edited; the calibration log pairs each
scored artifact with its realized forward outcome so per-agent Brier scores
accumulate on FORWARD data only (the only trustworthy evaluation for LLM
outputs). Deleting or rewriting records is unsupported by design.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel


class ArtifactStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def append(self, artifact: BaseModel) -> None:
        agent = getattr(artifact, "agent", "unknown")
        path = self.root / f"{agent}.jsonl"
        with path.open("a", encoding="utf-8") as fh:
            fh.write(artifact.model_dump_json() + "\n")

    def load_raw(self, agent: str) -> list[dict]:
        path = self.root / f"{agent}.jsonl"
        if not path.exists():
            return []
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def record_outcome(
        self,
        run_id: str,
        agent: str,
        predicted_confidence: float,
        outcome: bool,
    ) -> None:
        """Forward-scoring entry: (confidence, realized outcome) for Brier."""

        path = self.root / "calibration.jsonl"
        with path.open("a", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    {
                        "run_id": run_id,
                        "agent": agent,
                        "confidence": predicted_confidence,
                        "outcome": bool(outcome),
                        "scored_at": datetime.now(UTC).isoformat(),
                    }
                )
                + "\n"
            )

    def brier_score(self, agent: str) -> tuple[float | None, int]:
        """(Brier score, n) for an agent; None until any outcomes exist."""

        path = self.root / "calibration.jsonl"
        if not path.exists():
            return None, 0
        rows = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        rows = [r for r in rows if r["agent"] == agent]
        if not rows:
            return None, 0
        score = sum((r["confidence"] - (1.0 if r["outcome"] else 0.0)) ** 2 for r in rows) / len(
            rows
        )
        return score, len(rows)
