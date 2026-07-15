"""Validation-only ablation and explicit final-test release."""

from __future__ import annotations

import hashlib
import json

from pydantic_core import to_jsonable_python

from trading_desk.backtest.configuration import (
    BacktestConfiguration,
    FrozenSelection,
)
from trading_desk.backtest.engine import BacktestEngine
from trading_desk.backtest.models import (
    BacktestDataset,
    BacktestRun,
    DatasetSplit,
    FinalTestReport,
    ValidationComparison,
    ValidationMetricSummary,
)
from trading_desk.backtest.splits import build_chronological_splits
from trading_desk.strategy.configuration import StrategyConfiguration
from trading_desk.strategy.models import StrategyVariant

ALL_VARIANTS = (
    StrategyVariant.BASELINE_ONLY,
    StrategyVariant.BASELINE_KALMAN,
    StrategyVariant.BASELINE_HMM,
    StrategyVariant.BASELINE_KALMAN_HMM,
)


def compare_variants(
    dataset: BacktestDataset,
    configuration: BacktestConfiguration,
    strategy_configuration: StrategyConfiguration | None = None,
    variants: tuple[StrategyVariant, ...] = ALL_VARIANTS,
) -> tuple[tuple[BacktestRun, ...], ValidationComparison]:
    """Compare variants on VALIDATION without reading or evaluating TEST."""
    if configuration.evaluation_split is not DatasetSplit.VALIDATION:
        raise ValueError("research comparison is restricted to VALIDATION")
    if StrategyVariant.BASELINE_ONLY not in variants:
        raise ValueError("variant comparison requires BASELINE_ONLY as the control")
    if len(set(variants)) != len(variants):
        raise ValueError("variant comparison cannot contain duplicates")

    validation_runs = tuple(
        BacktestEngine(
            configuration.model_copy(
                update={"variant": variant, "evaluation_split": DatasetSplit.VALIDATION}
            ),
            strategy_configuration,
        ).run(dataset)
        for variant in variants
    )
    payload = {
        "baseline_variant": StrategyVariant.BASELINE_ONLY,
        "dataset_content_sha256": dataset.manifest.content_sha256,
        "dataset_source_filename": dataset.manifest.source_filename,
        "splits": validation_runs[0].splits,
        "validation_run_fingerprints": tuple(run.run_fingerprint for run in validation_runs),
        "variants": tuple(run.variant for run in validation_runs),
        "validation_net_returns": tuple(run.metrics.net_return for run in validation_runs),
        "validation_maximum_drawdowns": tuple(
            run.metrics.maximum_drawdown for run in validation_runs
        ),
        "validation_trade_counts": tuple(run.metrics.trade_count for run in validation_runs),
    }
    comparison = ValidationComparison.model_validate(
        {"report_fingerprint": _fingerprint(payload), **payload}
    )
    return validation_runs, comparison


def freeze_selection(
    validation_runs: tuple[BacktestRun, ...],
    validation_report: ValidationComparison,
    configuration: BacktestConfiguration,
    selected_variant: StrategyVariant,
    *,
    selection_rationale: str,
    strategy_configuration: StrategyConfiguration | None = None,
) -> FrozenSelection:
    """Freeze one validation-selected variant without accepting TEST results."""
    if configuration.evaluation_split is not DatasetSplit.VALIDATION:
        raise ValueError("selection can be frozen only from VALIDATION configuration")
    if not selection_rationale.strip():
        raise ValueError("selection rationale is required")
    if any(run.evaluation_split is not DatasetSplit.VALIDATION for run in validation_runs):
        raise ValueError("final-test results cannot be used to freeze a selection")
    if _validation_report_fingerprint(validation_report) != validation_report.report_fingerprint:
        raise ValueError("validation report fingerprint mismatch")
    if tuple(run.run_fingerprint for run in validation_runs) != (
        validation_report.validation_run_fingerprints
    ):
        raise ValueError("validation runs differ from the comparison report")

    selected = next(
        (run for run in validation_runs if run.variant is selected_variant),
        None,
    )
    if selected is None:
        raise ValueError("selected variant was not evaluated on VALIDATION")
    frozen_backtest = configuration.model_copy(
        update={"variant": selected_variant, "evaluation_split": DatasetSplit.VALIDATION}
    )
    base_strategy = strategy_configuration or StrategyConfiguration()
    frozen_strategy = base_strategy.model_copy(update={"variant": selected_variant})
    expected_run_fingerprint = frozen_backtest.fingerprint(
        frozen_strategy, validation_report.dataset_content_sha256
    )
    if selected.run_fingerprint != expected_run_fingerprint:
        raise ValueError("selected validation run configuration fingerprint mismatch")

    fields = {
        "selected_variant": selected_variant,
        "backtest_configuration": frozen_backtest,
        "strategy_configuration": frozen_strategy,
        "strategy_configuration_fingerprint": frozen_strategy.fingerprint,
        "validation_report_fingerprint": validation_report.report_fingerprint,
        "validation_run_fingerprint": selected.run_fingerprint,
        "dataset_content_sha256": validation_report.dataset_content_sha256,
        "dataset_source_filename": validation_report.dataset_source_filename,
        "chronological_splits": validation_report.splits,
        "validation_metrics": ValidationMetricSummary(
            net_return=selected.metrics.net_return,
            maximum_drawdown=selected.metrics.maximum_drawdown,
            trade_count=selected.metrics.trade_count,
        ),
        "selection_rationale": selection_rationale.strip(),
        "final_test_authorized": True,
    }
    return FrozenSelection.model_validate({"selection_identifier": _fingerprint(fields), **fields})


def evaluate_final_test(
    dataset: BacktestDataset,
    selection: FrozenSelection,
) -> FinalTestReport:
    """Evaluate only the frozen variant after validating the release artifact."""
    _validate_selection_configuration(selection)
    if dataset.manifest.content_sha256 != selection.dataset_content_sha256:
        raise ValueError("final-test dataset hash differs from frozen selection")
    if dataset.manifest.source_filename != selection.dataset_source_filename:
        raise ValueError("final-test dataset identity differs from frozen selection")
    if dataset.manifest.resolution is not selection.backtest_configuration.resolution:
        raise ValueError("final-test dataset resolution differs from frozen selection")
    if not dataset.bars or dataset.bars[0].epic != selection.backtest_configuration.epic:
        raise ValueError("final-test dataset EPIC differs from frozen selection")

    expected_splits = build_chronological_splits(
        dataset,
        selection.backtest_configuration.splits,
        selection.strategy_configuration.minimum_bars_required,
    )
    if expected_splits != selection.chronological_splits:
        raise ValueError("final-test split boundaries differ from frozen selection")
    expected_validation_fingerprint = selection.backtest_configuration.fingerprint(
        selection.strategy_configuration,
        dataset.manifest.content_sha256,
    )
    if expected_validation_fingerprint != selection.validation_run_fingerprint:
        raise ValueError("frozen validation configuration fingerprint mismatch")
    if _selection_fingerprint(selection) != selection.selection_identifier:
        raise ValueError("frozen selection identifier mismatch")

    test_configuration = selection.backtest_configuration.model_copy(
        update={"evaluation_split": DatasetSplit.TEST}
    )
    run = BacktestEngine(
        test_configuration,
        selection.strategy_configuration,
        final_test_selection=selection,
    ).run(dataset)
    return FinalTestReport(
        selection_identifier=selection.selection_identifier,
        selected_variant=selection.selected_variant,
        run=run,
    )


def _validation_report_fingerprint(report: ValidationComparison) -> str:
    return _fingerprint(report.model_dump(mode="python", exclude={"report_fingerprint"}))


def _selection_fingerprint(selection: FrozenSelection) -> str:
    return selection.computed_identifier


def _validate_selection_configuration(selection: FrozenSelection) -> None:
    if selection.final_test_authorized is not True:
        raise ValueError("frozen selection does not authorize final TEST")
    if selection.strategy_configuration.fingerprint != selection.strategy_configuration_fingerprint:
        raise ValueError("frozen strategy configuration fingerprint mismatch")


def _fingerprint(value: object) -> str:
    canonical = json.dumps(
        to_jsonable_python(value),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
