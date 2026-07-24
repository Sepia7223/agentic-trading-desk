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


def test_days_to_cover_scores_consolidated_schema() -> None:
    # Real consolidatedShortInterest record shape (verified live 2026-07-24
    # from the Agilent/NYSE record): symbolCode + daysToCoverQuantity.
    records = [
        {"symbolCode": "A", "daysToCoverQuantity": 2.12},
        {"symbolCode": "BBB", "daysToCoverQuantity": 999.99},
        {"symbolCode": "CCC", "daysToCoverQuantity": None},
        {"symbolCode": "DDD", "daysToCoverQuantity": 0.0},
    ]
    scores = variant_scores(records, "days-to-cover")
    assert scores == {"A": 2.12}  # sentinel, missing and zero rows dropped


def test_si_change_scores_from_single_record() -> None:
    records = [
        {
            "symbolCode": "AAA",
            "currentShortPositionQuantity": 1200,
            "previousShortPositionQuantity": 1000,
        },
        {
            "symbolCode": "BBB",
            "currentShortPositionQuantity": 500,
            "previousShortPositionQuantity": 0,
        },
    ]
    scores = variant_scores(records, "si-change")
    assert scores == {"AAA": pytest.approx(0.2)}  # zero-previous dropped


def test_unknown_variant_rejected() -> None:
    with pytest.raises(ValueError):
        variant_scores([], "made-up")
