"""Explicit non-overlapping chronological dataset partitions."""

from __future__ import annotations

from trading_desk.backtest.configuration import SplitConfiguration
from trading_desk.backtest.models import (
    BacktestDataset,
    ChronologicalSplits,
    DatasetSplit,
    SplitPeriod,
)
from trading_desk.backtest.validation import BacktestDataError


def build_chronological_splits(
    dataset: BacktestDataset,
    configuration: SplitConfiguration,
    minimum_warmup_bars: int,
) -> ChronologicalSplits:
    timestamps = tuple(bar.timestamp for bar in dataset.bars)
    train_indices = tuple(
        i for i, value in enumerate(timestamps) if value <= configuration.train_end
    )
    validation_indices = tuple(
        i
        for i, value in enumerate(timestamps)
        if configuration.train_end < value <= configuration.validation_end
    )
    test_indices = tuple(
        i
        for i, value in enumerate(timestamps)
        if configuration.validation_end < value <= configuration.test_end
    )
    if not train_indices or not validation_indices or not test_indices:
        raise BacktestDataError("TRAIN, VALIDATION, and TEST splits must all be non-empty")
    if len(train_indices) < minimum_warmup_bars:
        raise BacktestDataError("TRAIN split is shorter than the strategy warm-up")
    train = _period(DatasetSplit.TRAIN, train_indices, timestamps)
    validation = _period(DatasetSplit.VALIDATION, validation_indices, timestamps)
    test = _period(DatasetSplit.TEST, test_indices, timestamps)
    if not train.end_index < validation.start_index <= validation.end_index < test.start_index:
        raise BacktestDataError("chronological splits overlap or are out of order")
    return ChronologicalSplits(train=train, validation=validation, test=test)


def split_for_index(index: int, splits: ChronologicalSplits) -> DatasetSplit:
    if splits.train.start_index <= index <= splits.train.end_index:
        return DatasetSplit.TRAIN
    if splits.validation.start_index <= index <= splits.validation.end_index:
        return DatasetSplit.VALIDATION
    if splits.test.start_index <= index <= splits.test.end_index:
        return DatasetSplit.TEST
    raise IndexError("bar index falls outside configured splits")


def _period(
    name: DatasetSplit, indices: tuple[int, ...], timestamps: tuple[object, ...]
) -> SplitPeriod:
    start, end = indices[0], indices[-1]
    return SplitPeriod(
        name=name,
        start_index=start,
        end_index=end,
        start_timestamp=timestamps[start],  # type: ignore[arg-type]
        end_timestamp=timestamps[end],  # type: ignore[arg-type]
    )
