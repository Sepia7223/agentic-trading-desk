"""Append-only point-in-time feature store over parquet.

Design (from the information-edge blueprint):

- Rows are appended, never rewritten. A correction is a NEW row with the same
  ``event_time`` and a later ``knowledge_time``; historical queries therefore
  return exactly what was knowable at their as-of moment (cheap bi-temporality).
- The only read API is :meth:`FeatureStore.get_features` — an as-of query that
  structurally excludes the future: rows with ``knowledge_time > as_of`` are
  filtered before selection, and the latest surviving row per (ticker, field)
  wins. A ``tolerance`` drops stale features (returned as missing) instead of
  letting them silently persist.
- Replay stability: because storage is append-only and the query filters on
  ``knowledge_time``, re-running any historical query after new appends yields
  the identical result (verified by unit test).

Storage layout: ``root/{source}/{batch-uuid}.parquet``; one file per append.
RESEARCH/OPERATIONS infrastructure; grants no trading authority.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd  # type: ignore[import-untyped]

REQUIRED_COLUMNS = ("ticker", "event_time", "knowledge_time")


class FeatureStoreError(ValueError):
    """Raised on malformed appends or queries."""


@dataclass(frozen=True)
class FeatureQueryResult:
    """Result of an as-of query, with its audit fields."""

    frame: pd.DataFrame
    as_of: datetime
    sources: tuple[str, ...]


def _ensure_utc(series: pd.Series, name: str) -> pd.Series:
    converted = pd.to_datetime(series, utc=True, errors="coerce")
    if converted.isna().any():
        raise FeatureStoreError(f"column {name!r} contains unparseable timestamps")
    return converted


class FeatureStore:
    """Append-only PIT store; the single choke point for feature reads."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ write

    def append(self, source: str, frame: pd.DataFrame) -> Path:
        """Append a batch of feature rows for ``source``.

        The frame must contain ticker/event_time/knowledge_time plus at least
        one feature column. knowledge_time must be >= event_time (you cannot
        know something before it happens) — violations reject the whole batch.
        """

        if not source or "/" in source or "\\" in source:
            raise FeatureStoreError(f"invalid source name: {source!r}")
        missing = [c for c in REQUIRED_COLUMNS if c not in frame.columns]
        if missing:
            raise FeatureStoreError(f"missing required columns: {missing}")
        feature_cols = [c for c in frame.columns if c not in REQUIRED_COLUMNS]
        if not feature_cols:
            raise FeatureStoreError("no feature columns in batch")
        out = frame.copy()
        out["event_time"] = _ensure_utc(out["event_time"], "event_time")
        out["knowledge_time"] = _ensure_utc(out["knowledge_time"], "knowledge_time")
        if (out["knowledge_time"] < out["event_time"]).any():
            raise FeatureStoreError("knowledge_time earlier than event_time — impossible knowledge")
        out["ticker"] = out["ticker"].astype(str)
        target_dir = self.root / source
        target_dir.mkdir(parents=True, exist_ok=True)
        path = target_dir / f"{uuid.uuid4().hex}.parquet"
        out.to_parquet(path, index=False)
        return path

    # ------------------------------------------------------------------- read

    def sources(self) -> list[str]:
        return sorted(p.name for p in self.root.iterdir() if p.is_dir())

    def get_features(
        self,
        universe: list[str],
        as_of: datetime,
        sources: list[str] | None = None,
        tolerance: timedelta | None = None,
    ) -> FeatureQueryResult:
        """Latest knowable value per (ticker, feature) at ``as_of``.

        Returns one row per ticker in ``universe`` (tickers with no knowable
        data appear with NaN features). Rows with knowledge_time > as_of are
        structurally excluded; rows older than ``tolerance`` are dropped.
        """

        if as_of.tzinfo is None:
            raise FeatureStoreError("as_of must be timezone-aware (UTC)")
        as_of = as_of.astimezone(UTC)
        chosen = sources if sources is not None else self.sources()
        pieces: list[pd.DataFrame] = []
        for source in chosen:
            source_dir = self.root / source
            if not source_dir.is_dir():
                raise FeatureStoreError(f"unknown source: {source!r}")
            for path in sorted(source_dir.glob("*.parquet")):
                piece = pd.read_parquet(path)
                pieces.append(piece)
        base = pd.DataFrame({"ticker": [str(t) for t in universe]})
        if not pieces:
            return FeatureQueryResult(frame=base, as_of=as_of, sources=tuple(chosen))
        data = pd.concat(pieces, ignore_index=True)
        # feature columns are defined by what exists in storage, so that an
        # all-filtered result still returns those columns as NaN (never a
        # silently narrower frame).
        feature_cols = [c for c in data.columns if c not in REQUIRED_COLUMNS]
        # the leakage guarantee: the future does not exist for this query
        data = data[data["knowledge_time"] <= pd.Timestamp(as_of)]
        if tolerance is not None:
            cutoff = pd.Timestamp(as_of - tolerance)
            data = data[data["knowledge_time"] >= cutoff]
        data = data[data["ticker"].isin(set(base["ticker"]))]
        if data.empty:
            empty = base.reindex(columns=["ticker", *feature_cols])
            return FeatureQueryResult(frame=empty, as_of=as_of, sources=tuple(chosen))
        # latest knowable row wins per (ticker, feature): sort then take last
        # non-null value per column so corrections supersede originals.
        data = data.sort_values(["ticker", "knowledge_time"], kind="stable")
        latest = data.groupby("ticker")[feature_cols].last()
        merged = base.merge(latest, on="ticker", how="left")
        self._assert_no_leakage(data, as_of)
        return FeatureQueryResult(frame=merged, as_of=as_of, sources=tuple(chosen))

    # ------------------------------------------------------------------ audit

    @staticmethod
    def _assert_no_leakage(data: pd.DataFrame, as_of: datetime) -> None:
        """Defense-in-depth invariant: every surviving row is knowable."""

        if not data.empty and (data["knowledge_time"] > pd.Timestamp(as_of)).any():
            raise FeatureStoreError("leakage invariant violated: row with knowledge_time > as_of")

    def describe(self) -> dict[str, Any]:
        """Row/file counts per source (operations visibility)."""

        out: dict[str, Any] = {}
        for source in self.sources():
            files = list((self.root / source).glob("*.parquet"))
            rows = sum(len(pd.read_parquet(f)) for f in files)
            out[source] = {"files": len(files), "rows": rows}
        return out
