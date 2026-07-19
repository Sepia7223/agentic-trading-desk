"""Fingerprint-keyed trial-result cache for repeated research runs.

A cached trial is reusable only when every input that could change the
evidence matches: dataset fingerprint, experiment boundaries, pair and
timeframe selection, trial configuration fingerprint, and the research code
fingerprint. Any mismatch produces a different key, so stale reuse is
structurally impossible. Cached values are validated on read; corrupt
entries are ignored and recomputed.
"""

from __future__ import annotations

from pathlib import Path

from trading_desk.context.fingerprints import fingerprint
from trading_desk.research.models import TrialResult


def trial_cache_key(
    *,
    dataset_fingerprint: str,
    code_fingerprint: str,
    boundaries_fingerprint: str,
    pairs: tuple[str, ...],
    timeframes: tuple[str, ...],
    configuration_fingerprint: str,
) -> str:
    return fingerprint(
        {
            "dataset": dataset_fingerprint,
            "code": code_fingerprint,
            "boundaries": boundaries_fingerprint,
            "pairs": pairs,
            "timeframes": timeframes,
            "configuration": configuration_fingerprint,
        }
    )


class TrialCache:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.hits = 0
        self.misses = 0

    def _path(self, key: str) -> Path:
        return self.root / f"{key}.json"

    def load(self, key: str) -> TrialResult | None:
        path = self._path(key)
        if not path.is_file():
            self.misses += 1
            return None
        try:
            trial = TrialResult.model_validate_json(path.read_text(encoding="utf-8"))
        except ValueError:
            self.misses += 1
            return None
        self.hits += 1
        return trial

    def store(self, key: str, trial: TrialResult) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self._path(key).write_text(trial.model_dump_json(indent=2) + "\n", encoding="utf-8")
