from __future__ import annotations

from datetime import timedelta

import pytest
from pydantic import ValidationError
from tests.backtest_helpers import configuration, dataset

from trading_desk.backtest.configuration import SplitConfiguration
from trading_desk.backtest.models import DatasetSplit
from trading_desk.backtest.splits import build_chronological_splits, split_for_index
from trading_desk.backtest.validation import BacktestDataError


def test_explicit_splits_are_non_overlapping_and_chronological() -> None:
    data = dataset()
    config = configuration()
    splits = build_chronological_splits(data, config.splits, 220)

    assert splits.train.end_index < splits.validation.start_index
    assert splits.validation.end_index < splits.test.start_index
    assert split_for_index(splits.train.end_index, splits) is DatasetSplit.TRAIN
    assert split_for_index(splits.test.start_index, splits) is DatasetSplit.TEST


def test_invalid_boundary_order_and_empty_splits_fail() -> None:
    data = dataset()
    with pytest.raises(ValidationError):
        SplitConfiguration(
            train_end=data.bars[220].timestamp,
            validation_end=data.bars[219].timestamp,
            test_end=data.bars[-1].timestamp,
        )
    config = configuration().splits.model_copy(
        update={"validation_end": data.bars[219].timestamp + timedelta(seconds=1)}
    )
    with pytest.raises(BacktestDataError, match="non-empty"):
        build_chronological_splits(data, config, 220)


def test_insufficient_strategy_warmup_fails() -> None:
    data = dataset(223)
    config = configuration(count=223)
    with pytest.raises(BacktestDataError, match="warm-up"):
        build_chronological_splits(data, config.splits, 221)
