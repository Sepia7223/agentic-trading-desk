from __future__ import annotations

import math
from pathlib import Path

import pytest
from tests.backtest_helpers import bars

from trading_desk.backtest.data import dataset_from_rows, load_dataset
from trading_desk.backtest.validation import BacktestDataError, validate_bars
from trading_desk.strategy.models import StrategyBarResolution


def _rows() -> tuple[dict[str, object], ...]:
    return tuple(item.model_dump(mode="json") for item in bars(4))


def test_csv_loading_records_manifest_and_stable_content_hash(tmp_path: Path) -> None:
    content = (
        "epic,timestamp,open_bid,open_ask,high_bid,high_ask,low_bid,low_ask,"
        "close_bid,close_ask,last_traded_volume,market_status\n"
        "CS.D.TEST.CFD.IP,2020-01-01T00:00:00+00:00,100,100.02,101,101.02,99,"
        "99.02,100.5,100.52,1000,TRADEABLE\n"
    )
    first = tmp_path / "first.csv"
    second = tmp_path / "second.csv"
    first.write_text(content, encoding="utf-8")
    second.write_text(content, encoding="utf-8")

    one = load_dataset(first, StrategyBarResolution.DAY)
    two = load_dataset(second, StrategyBarResolution.DAY)

    assert one.manifest.content_sha256 == two.manifest.content_sha256
    assert one.manifest.source_filename == "first.csv"
    assert one.manifest.row_count == 1


def test_duplicate_and_unsorted_timestamps_fail_closed() -> None:
    values = bars(4)
    duplicate = (*values[:2], values[1], values[3])
    unsorted = (values[0], values[2], values[1], values[3])
    with pytest.raises(BacktestDataError, match="duplicate"):
        validate_bars(duplicate, StrategyBarResolution.DAY)
    with pytest.raises(BacktestDataError, match="strictly increasing"):
        validate_bars(unsorted, StrategyBarResolution.DAY)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("close_bid", math.nan),
        ("open_ask", -1.0),
        ("close_bid", 200.0),
    ],
)
def test_nonfinite_negative_reversed_or_implausible_prices_fail(field: str, value: float) -> None:
    rows = list(_rows())
    rows[0] = {**rows[0], field: value}
    with pytest.raises(BacktestDataError, match="strict validation"):
        dataset_from_rows(tuple(rows), "prices.csv", "a" * 64, StrategyBarResolution.DAY)


def test_missing_bid_or_ask_is_never_interpolated() -> None:
    rows = list(_rows())
    rows[0] = {**rows[0], "open_ask": ""}
    with pytest.raises(BacktestDataError, match="missing required"):
        dataset_from_rows(tuple(rows), "prices.csv", "a" * 64, StrategyBarResolution.DAY)


def test_changing_cadence_is_detected() -> None:
    values = list(bars(4))
    values[3] = values[3].model_copy(
        update={"timestamp": values[2].timestamp + (values[2].timestamp - values[0].timestamp) * 5}
    )
    with pytest.raises(BacktestDataError, match="CHANGING_CADENCE"):
        validate_bars(tuple(values), StrategyBarResolution.DAY)
