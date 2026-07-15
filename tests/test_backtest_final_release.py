from __future__ import annotations

import pytest
from tests.backtest_helpers import configuration, dataset

from trading_desk.backtest.comparison import (
    compare_variants,
    evaluate_final_test,
    freeze_selection,
)
from trading_desk.backtest.engine import BacktestEngine
from trading_desk.backtest.models import DatasetSplit
from trading_desk.strategy.models import StrategyVariant


def _selection():
    data = dataset(223)
    config = configuration(count=223)
    runs, report = compare_variants(
        data,
        config,
        variants=(StrategyVariant.BASELINE_ONLY, StrategyVariant.BASELINE_KALMAN),
    )
    selection = freeze_selection(
        runs,
        report,
        config,
        StrategyVariant.BASELINE_ONLY,
        selection_rationale="baseline selected from validation evidence",
    )
    return data, config, runs, report, selection


def test_research_comparison_is_validation_only_and_contains_no_test_metrics() -> None:
    data, _, runs, report, _ = _selection()
    changed = list(data.bars)
    changed[-1] = changed[-1].model_copy(
        update={
            "open_bid": changed[-1].open_bid * 5,
            "open_ask": changed[-1].open_ask * 5,
            "high_bid": changed[-1].high_bid * 5,
            "high_ask": changed[-1].high_ask * 5,
            "low_bid": changed[-1].low_bid * 5,
            "low_ask": changed[-1].low_ask * 5,
            "close_bid": changed[-1].close_bid * 5,
            "close_ask": changed[-1].close_ask * 5,
        }
    )
    changed_data = data.model_copy(update={"bars": tuple(changed)})
    changed_runs, _ = compare_variants(
        changed_data,
        configuration(count=223),
        variants=(StrategyVariant.BASELINE_ONLY, StrategyVariant.BASELINE_KALMAN),
    )

    assert all(run.evaluation_split is DatasetSplit.VALIDATION for run in runs)
    assert tuple(run.metrics for run in runs) == tuple(run.metrics for run in changed_runs)
    assert not hasattr(report, "test_net_returns")


def test_research_comparison_and_direct_engine_reject_test_access() -> None:
    data = dataset(223)
    test_config = configuration(count=223, evaluation_split=DatasetSplit.TEST)

    with pytest.raises(ValueError, match="restricted to VALIDATION"):
        compare_variants(data, test_config)
    with pytest.raises(ValueError, match="frozen selection"):
        BacktestEngine(test_config)


def test_final_test_requires_matching_frozen_selection_and_runs_only_selected_variant() -> None:
    data, _, _, _, selection = _selection()

    report = evaluate_final_test(data, selection)

    assert report.report_type == "FINAL_TEST"
    assert report.selected_variant is StrategyVariant.BASELINE_ONLY
    assert report.run.variant is StrategyVariant.BASELINE_ONLY
    assert report.run.evaluation_split is DatasetSplit.TEST


def test_final_test_rejects_fingerprint_dataset_and_split_mismatches() -> None:
    data, _, _, _, selection = _selection()
    bad_fingerprint = selection.model_copy(update={"strategy_configuration_fingerprint": "0" * 64})
    bad_splits = selection.model_copy(
        update={
            "chronological_splits": selection.chronological_splits.model_copy(
                update={"validation": selection.chronological_splits.test}
            )
        }
    )

    with pytest.raises(ValueError, match="strategy configuration fingerprint"):
        evaluate_final_test(data, bad_fingerprint)
    with pytest.raises(ValueError, match="dataset hash"):
        evaluate_final_test(dataset(224), selection)
    with pytest.raises(ValueError, match="split boundaries"):
        evaluate_final_test(data, bad_splits)


def test_direct_test_engine_rejects_tampered_selection_identifier() -> None:
    data, _, _, _, selection = _selection()
    tampered = selection.model_copy(update={"selection_rationale": "Changed after freezing."})
    test_config = selection.backtest_configuration.model_copy(
        update={"evaluation_split": DatasetSplit.TEST}
    )

    with pytest.raises(ValueError, match="selection identifier"):
        BacktestEngine(
            test_config,
            selection.strategy_configuration,
            final_test_selection=tampered,
        ).run(data)


def test_final_test_results_cannot_be_reused_for_selection() -> None:
    data, config, _, report, selection = _selection()
    final_report = evaluate_final_test(data, selection)

    with pytest.raises(ValueError, match="cannot be used"):
        freeze_selection(
            (final_report.run,),
            report,
            config,
            StrategyVariant.BASELINE_ONLY,
            selection_rationale="invalid feedback attempt",
        )
