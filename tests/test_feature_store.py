"""Tests for the point-in-time feature store (the leakage defenses above all)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from trading_desk.features import FeatureStore
from trading_desk.features.store import FeatureStoreError

T0 = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)


def make_frame(rows: list[tuple[str, datetime, datetime, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ticker": t,
                "event_time": ev,
                "knowledge_time": kt,
                "score": v,
            }
            for t, ev, kt, v in rows
        ]
    )


def test_future_knowledge_is_structurally_invisible(tmp_path: Path):
    store = FeatureStore(tmp_path)
    store.append(
        "insider",
        make_frame(
            [
                ("AAA", T0, T0 + timedelta(hours=1), 1.0),  # knowable at T0+1h
                ("BBB", T0, T0 + timedelta(days=2), 9.0),  # filed late
            ]
        ),
    )
    result = store.get_features(["AAA", "BBB"], as_of=T0 + timedelta(hours=2))
    row = result.frame.set_index("ticker")
    assert row.loc["AAA", "score"] == 1.0
    assert pd.isna(row.loc["BBB", "score"])  # event happened, NOT yet knowable


def test_corrections_apply_only_after_their_knowledge_time(tmp_path: Path):
    store = FeatureStore(tmp_path)
    store.append("est", make_frame([("AAA", T0, T0, 1.0)]))
    # vendor restates the same event later
    store.append("est", make_frame([("AAA", T0, T0 + timedelta(days=5), 2.0)]))
    before = store.get_features(["AAA"], as_of=T0 + timedelta(days=1))
    after = store.get_features(["AAA"], as_of=T0 + timedelta(days=6))
    assert before.frame.loc[0, "score"] == 1.0  # what was known then
    assert after.frame.loc[0, "score"] == 2.0  # correction visible later


def test_replay_stability_after_new_appends(tmp_path: Path):
    store = FeatureStore(tmp_path)
    store.append("news", make_frame([("AAA", T0, T0, 5.0)]))
    as_of = T0 + timedelta(days=1)
    first = store.get_features(["AAA"], as_of=as_of).frame
    # new data arrives afterwards — historical query must NOT change
    store.append("news", make_frame([("AAA", T0 + timedelta(days=3), T0 + timedelta(days=3), 7.0)]))
    second = store.get_features(["AAA"], as_of=as_of).frame
    pd.testing.assert_frame_equal(first, second)


def test_tolerance_drops_stale_features(tmp_path: Path):
    store = FeatureStore(tmp_path)
    store.append("si", make_frame([("AAA", T0, T0, 3.0)]))
    fresh = store.get_features(["AAA"], as_of=T0 + timedelta(days=10), tolerance=timedelta(days=30))
    stale = store.get_features(["AAA"], as_of=T0 + timedelta(days=90), tolerance=timedelta(days=30))
    assert fresh.frame.loc[0, "score"] == 3.0
    assert pd.isna(stale.frame.loc[0, "score"])  # expired, not silently reused


def test_impossible_knowledge_rejected_at_append(tmp_path: Path):
    store = FeatureStore(tmp_path)
    with pytest.raises(FeatureStoreError, match="impossible knowledge"):
        store.append("bad", make_frame([("AAA", T0, T0 - timedelta(hours=1), 1.0)]))


def test_append_requires_feature_columns_and_valid_source(tmp_path: Path):
    store = FeatureStore(tmp_path)
    bare = pd.DataFrame({"ticker": ["AAA"], "event_time": [T0], "knowledge_time": [T0]})
    with pytest.raises(FeatureStoreError, match="no feature columns"):
        store.append("x", bare)
    with pytest.raises(FeatureStoreError, match="invalid source"):
        store.append("a/b", make_frame([("AAA", T0, T0, 1.0)]))


def test_naive_as_of_rejected(tmp_path: Path):
    store = FeatureStore(tmp_path)
    store.append("news", make_frame([("AAA", T0, T0, 1.0)]))
    with pytest.raises(FeatureStoreError, match="timezone-aware"):
        store.get_features(["AAA"], as_of=datetime(2026, 7, 2, 12, 0))


def test_multi_source_merge_and_describe(tmp_path: Path):
    store = FeatureStore(tmp_path)
    store.append("insider", make_frame([("AAA", T0, T0, 1.0)]))
    frame2 = make_frame([("AAA", T0, T0, 4.0)]).rename(columns={"score": "os_ratio"})
    store.append("options", frame2)
    result = store.get_features(["AAA", "ZZZ"], as_of=T0 + timedelta(hours=1))
    row = result.frame.set_index("ticker")
    assert row.loc["AAA", "score"] == 1.0
    assert row.loc["AAA", "os_ratio"] == 4.0
    assert pd.isna(row.loc["ZZZ", "score"])  # in universe, no data
    described = store.describe()
    assert described["insider"]["rows"] == 1
    assert described["options"]["rows"] == 1
