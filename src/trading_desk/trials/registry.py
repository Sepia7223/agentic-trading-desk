"""Append-only trial registry: the honest N for every multiplicity test.

The backtest runner (not a human) records every configuration it evaluates.
Records are JSONL, append-only, deduplicated by params fingerprint; the
registry supplies the trial count and cross-trial Sharpe variance that the
Deflated Sharpe Ratio requires. Deleting or editing records is not supported
by design.
"""

from __future__ import annotations

import hashlib
import json
import statistics
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TrialRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    family: str = Field(min_length=1)  # e.g. "insider-cluster", "composite-v1"
    params: dict[str, Any]
    sharpe: float
    n_observations: int = Field(ge=2)
    window: str = Field(min_length=1)  # e.g. "2022-01..2025-06"
    recorded_at: datetime
    fingerprint: str = ""

    @staticmethod
    def make_fingerprint(family: str, params: dict[str, Any], window: str) -> str:
        seed = json.dumps(
            {"family": family, "params": params, "window": window},
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]


class TrialRegistry:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(
        self,
        family: str,
        params: dict[str, Any],
        sharpe: float,
        n_observations: int,
        window: str,
    ) -> TrialRecord:
        rec = TrialRecord(
            family=family,
            params=params,
            sharpe=sharpe,
            n_observations=n_observations,
            window=window,
            recorded_at=datetime.now(UTC),
            fingerprint=TrialRecord.make_fingerprint(family, params, window),
        )
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(rec.model_dump_json() + "\n")
        return rec

    def load(self) -> list[TrialRecord]:
        if not self.path.exists():
            return []
        out: list[TrialRecord] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                out.append(TrialRecord.model_validate_json(line))
        return out

    def trial_count(self, family: str | None = None) -> int:
        """Unique configurations tried (re-runs of the same config count once)."""

        records = self.load()
        if family is not None:
            records = [r for r in records if r.family == family]
        return len({r.fingerprint for r in records})

    def sharpe_variance(self, family: str | None = None) -> float:
        """Cross-trial variance of Sharpe estimates (latest run per config)."""

        records = self.load()
        if family is not None:
            records = [r for r in records if r.family == family]
        latest: dict[str, float] = {}
        for r in records:  # file order == chronological; last write wins
            latest[r.fingerprint] = r.sharpe
        values = list(latest.values())
        if len(values) < 2:
            return 0.0
        return float(statistics.pvariance(values))

    def dsr_inputs(self, family: str | None = None) -> tuple[int, float]:
        """(honest trial count, cross-trial Sharpe variance) for the DSR."""

        return self.trial_count(family), self.sharpe_variance(family)
