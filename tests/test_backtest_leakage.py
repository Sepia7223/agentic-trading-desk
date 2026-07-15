from __future__ import annotations

from tests.backtest_helpers import configuration, dataset

from trading_desk.backtest.engine import BacktestEngine


def test_appended_future_bars_do_not_change_stored_validation_artifacts() -> None:
    original_data = dataset(250)
    extended_data = dataset(260)
    config = configuration(count=250)

    original = BacktestEngine(config).run(original_data)
    extended = BacktestEngine(config).run(extended_data)

    assert original.signals == extended.signals
    assert original.fills == extended.fills
    assert original.trades == extended.trades
    assert original.equity_curve == extended.equity_curve


def test_each_signal_cutoff_precedes_any_associated_fill() -> None:
    run = BacktestEngine(configuration()).run(dataset())
    assert all(
        fill.fill_index > fill.signal_index for fill in run.fills if fill.side.value == "ENTRY"
    )


def test_train_and_validation_boundaries_are_not_future_fitted() -> None:
    run = BacktestEngine(configuration()).run(dataset())
    assert all(signal.timestamp <= run.splits.validation.end_timestamp for signal in run.signals)
    assert all(signal.index >= run.splits.validation.start_index for signal in run.signals)
    assert run.evaluation_split.value == "VALIDATION"
    assert run.splits.train.end_timestamp < run.splits.validation.start_timestamp
    assert run.splits.validation.end_timestamp < run.splits.test.start_timestamp
