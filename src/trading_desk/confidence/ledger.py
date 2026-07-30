"""Append-only calibration ledger: confidence bucket -> realized outcomes.

This is the accountability half of the design: 'how many times that high
percentage confidence works'. Every CLOSED trade appends one row; rows are
never edited. Bucket statistics pool only rows from the same score
version. Kelly sizing reads these stats and nothing else - declared
confidence has no sizing power until it shows up here as realized R.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from trading_desk.confidence.models import SCORE_VERSION


@dataclass(frozen=True)
class BucketStats:
    bucket: str
    n: int
    win_rate: float
    average_win_r: float
    average_loss_r: float

    @property
    def payoff_ratio(self) -> float:
        """avg win R over avg |loss| R; 0 when no losses observed yet."""

        return self.average_win_r / abs(self.average_loss_r) if self.average_loss_r else 0.0

    @property
    def expectancy_r(self) -> float:
        return self.win_rate * self.average_win_r + (1 - self.win_rate) * self.average_loss_r

    def kelly_fraction(self) -> float:
        """Discrete Kelly f* = W - (1-W)/R; clamped at >= 0.

        Degenerate cases fail SAFE: no losses yet (payoff undefined) or no
        wins yet -> 0, i.e. no sizing power.
        """

        if self.n == 0 or self.payoff_ratio <= 0:
            return 0.0
        f = self.win_rate - (1 - self.win_rate) / self.payoff_ratio
        return max(0.0, f)


class CalibrationLedger:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(
        self,
        *,
        trade_id: str,
        symbol: str,
        confidence: float,
        bucket: str,
        outcome_r: float,
        opened: str,
        closed: str,
    ) -> None:
        """Append one CLOSED trade outcome. outcome_r is the realized
        R-multiple (profit / initial dollar risk); losses are negative."""

        row = {
            "trade_id": trade_id,
            "symbol": symbol,
            "score_version": SCORE_VERSION,
            "confidence": round(confidence, 4),
            "bucket": bucket,
            "outcome_r": round(outcome_r, 6),
            "opened": opened,
            "closed": closed,
            "recorded_at": datetime.now(UTC).isoformat(),
        }
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")

    def rows(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [
            json.loads(line)
            for line in self.path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def bucket_stats(self, bucket: str) -> BucketStats:
        outcomes = [
            float(r["outcome_r"])
            for r in self.rows()
            if r["bucket"] == bucket and r.get("score_version") == SCORE_VERSION
        ]
        if not outcomes:
            return BucketStats(bucket, 0, 0.0, 0.0, 0.0)
        wins = [r for r in outcomes if r > 0]
        losses = [r for r in outcomes if r <= 0]
        return BucketStats(
            bucket=bucket,
            n=len(outcomes),
            win_rate=len(wins) / len(outcomes),
            average_win_r=sum(wins) / len(wins) if wins else 0.0,
            average_loss_r=sum(losses) / len(losses) if losses else 0.0,
        )

    def report(self) -> list[BucketStats]:
        """Stats for every bucket that has at least one row (for the
        nightly journal: the user's 'how often does high confidence
        actually work' table)."""

        seen = sorted({r["bucket"] for r in self.rows() if r.get("score_version") == SCORE_VERSION})
        return [self.bucket_stats(b) for b in seen]
