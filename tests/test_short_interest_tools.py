"""Short-interest fetch/validation: offline pins for the pure parts."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from fetch_short_interest import extract_partition_dates  # noqa: E402
from validate_short_interest_signal import (  # noqa: E402
    add_business_days,
    variant_scores,
)


def test_extract_partition_dates_handles_shape_variants() -> None:
    nested = {
        "datasetGroup": "otcMarket",
        "availablePartitions": [
            {"partitions": ["2022-08-31", "2022-09-15"]},
            {"partitions": ["2019-01-15"]},
        ],
    }
    assert extract_partition_dates(nested) == ["2019-01-15", "2022-08-31", "2022-09-15"]
    flat = ["2020-06-15", "2020-06-30", "not-a-date", "20200615"]
    assert extract_partition_dates(flat) == ["2020-06-15", "2020-06-30"]


def test_add_business_days_skips_weekends() -> None:
    # Fri 2026-07-17 + 9 business days -> Thu 2026-07-30
    assert add_business_days(date(2026, 7, 17), 9) == date(2026, 7, 30)
    assert add_business_days(date(2026, 7, 18), 1).weekday() < 5


def test_days_to_cover_scores() -> None:
    records = [
        {
            "symbolCode": "AAA",
            "currentShortPositionQuantity": 1000,
            "averageDailyVolumeQuantity": 100,
        },
        {"symbolCode": "BBB", "currentShortPositionQuantity": 500, "averageDailyVolumeQuantity": 0},
        {
            "symbolCode": "CCC",
            "currentShortPositionQuantity": None,
            "averageDailyVolumeQuantity": 50,
        },
    ]
    scores = variant_scores(records, None, "days-to-cover")
    assert scores == {"AAA": 10.0}  # zero-ADV and missing-position rows dropped


def test_si_change_scores_need_previous() -> None:
    current = [{"symbolCode": "AAA", "currentShortPositionQuantity": 1200}]
    previous = [{"symbolCode": "AAA", "currentShortPositionQuantity": 1000}]
    scores = variant_scores(current, previous, "si-change")
    assert scores["AAA"] == pytest.approx(0.2)
    assert variant_scores(current, None, "si-change") == {}


def test_unknown_variant_rejected() -> None:
    with pytest.raises(ValueError):
        variant_scores([], None, "made-up")
