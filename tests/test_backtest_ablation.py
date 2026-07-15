from __future__ import annotations

from tests.backtest_helpers import configuration, dataset

from trading_desk.backtest.comparison import ALL_VARIANTS, compare_variants
from trading_desk.backtest.engine import BacktestEngine
from trading_desk.strategy.configuration import StrategyConfiguration
from trading_desk.strategy.models import StrategyVariant


def test_all_four_variants_run_identical_data_splits_and_assumptions() -> None:
    data = dataset(223)
    config = configuration(count=223)
    strategy = StrategyConfiguration(
        hmm_training_iterations=20,
        minimum_regime_probability=0.0,
        maximum_regime_uncertainty=1.0,
    )
    runs, comparison = compare_variants(data, config, strategy)

    assert tuple(run.variant for run in runs) == ALL_VARIANTS
    assert comparison.baseline_variant is StrategyVariant.BASELINE_ONLY
    assert len({run.manifest.content_sha256 for run in runs}) == 1
    assert len({run.splits.model_dump_json() for run in runs}) == 1
    assert all(run.metrics.variant is run.variant for run in runs)
    assert all(run.evaluation_split.value == "VALIDATION" for run in runs)
    assert len(comparison.validation_net_returns) == 4
    assert len(comparison.validation_maximum_drawdowns) == 4
    assert not hasattr(comparison, "test_net_returns")


def test_variant_changes_run_fingerprint_but_not_execution_assumptions() -> None:
    data = dataset()
    baseline = BacktestEngine(configuration()).run(data)
    kalman = BacktestEngine(configuration(variant=StrategyVariant.BASELINE_KALMAN)).run(data)

    assert baseline.run_fingerprint != kalman.run_fingerprint
    assert baseline.manifest == kalman.manifest
    assert baseline.splits == kalman.splits


def test_configuration_rejects_rolling_window_below_strategy_history() -> None:
    config = configuration(
        fitting_window_policy="ROLLING",
        maximum_rolling_window=220,
    )
    strategy = StrategyConfiguration(minimum_bars_required=221)
    try:
        BacktestEngine(config, strategy)
    except ValueError as error:
        assert "shorter" in str(error)
    else:
        raise AssertionError("short rolling window was accepted")
