"""Immutable simulation assumptions and canonical run fingerprints."""

from __future__ import annotations

import hashlib
import json
import math
import platform
from datetime import datetime
from importlib.metadata import version
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from trading_desk.backtest.models import (
    ChronologicalSplits,
    DatasetSplit,
    FillPriceMode,
    FittingWindowPolicy,
    IntrabarAmbiguityPolicy,
    ValidationMetricSummary,
)
from trading_desk.strategy.configuration import StrategyConfiguration
from trading_desk.strategy.models import StrategyBarResolution, StrategyVariant


class SplitConfiguration(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    train_end: datetime
    validation_end: datetime
    test_end: datetime

    @model_validator(mode="after")
    def validate_order(self) -> Self:
        if any(
            value.tzinfo is None for value in (self.train_end, self.validation_end, self.test_end)
        ):
            raise ValueError("split boundaries must be timezone-aware")
        if not self.train_end < self.validation_end < self.test_end:
            raise ValueError("split boundaries must be strictly chronological")
        return self


class BacktestConfiguration(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["backtest-schema-v1"] = "backtest-schema-v1"
    dataset_source: str
    epic: str = Field(min_length=1, max_length=80)
    resolution: StrategyBarResolution
    splits: SplitConfiguration
    variant: StrategyVariant = StrategyVariant.BASELINE_KALMAN_HMM
    evaluation_split: DatasetSplit = DatasetSplit.VALIDATION
    fitting_window_policy: FittingWindowPolicy = FittingWindowPolicy.EXPANDING
    maximum_rolling_window: int | None = Field(default=None, ge=220)
    initial_capital: float = Field(default=100_000.0, gt=0)
    fixed_quantity: float = Field(default=1.0, gt=0)
    slippage_bps: float = Field(default=1.0, ge=0)
    fixed_commission_per_side: float = Field(default=0.0, ge=0)
    proportional_commission_bps: float = Field(default=0.0, ge=0)
    overnight_funding_bps_per_day: float = Field(default=0.0, ge=0)
    guaranteed_stop_premium: float = Field(default=0.0, ge=0)
    maximum_holding_bars: int = Field(default=20, ge=1)
    protective_stop_bps: float = Field(default=500.0, gt=0)
    ambiguity_policy: IntrabarAmbiguityPolicy = IntrabarAmbiguityPolicy.ADVERSE_FIRST
    maximum_execution_delay_bars: int = Field(default=1, ge=1)
    entry_fill_mode: FillPriceMode = FillPriceMode.NEXT_OPEN
    exit_fill_mode: FillPriceMode = FillPriceMode.NEXT_OPEN
    annualization_factor: float | None = Field(default=None, gt=0)
    enable_cash_benchmark: bool = True
    enable_buy_and_hold_benchmark: bool = True

    @field_validator("dataset_source")
    @classmethod
    def retain_filename_only(cls, value: str) -> str:
        name = Path(value).name
        if not name:
            raise ValueError("dataset source filename is required")
        return name

    @field_validator(
        "initial_capital",
        "fixed_quantity",
        "slippage_bps",
        "fixed_commission_per_side",
        "proportional_commission_bps",
        "overnight_funding_bps_per_day",
        "guaranteed_stop_premium",
        "protective_stop_bps",
        "annualization_factor",
    )
    @classmethod
    def finite_numbers(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("backtest numeric settings must be finite")
        return value

    @model_validator(mode="after")
    def validate_window(self) -> Self:
        if self.evaluation_split is DatasetSplit.TRAIN:
            raise ValueError("performance evaluation split must be VALIDATION or TEST")
        if (
            self.fitting_window_policy is FittingWindowPolicy.ROLLING
            and self.maximum_rolling_window is None
        ):
            raise ValueError("rolling fitting requires a maximum rolling window")
        if self.entry_fill_mode not in {FillPriceMode.NEXT_OPEN, FillPriceMode.NEXT_CLOSE}:
            raise ValueError("entry fill mode must use a future bar quote")
        if self.exit_fill_mode not in {
            FillPriceMode.NEXT_OPEN,
            FillPriceMode.NEXT_CLOSE,
            FillPriceMode.END_OF_BAR_EXIT,
        }:
            raise ValueError("exit fill mode is unsupported for scheduled exits")
        return self

    def resolved_annualization_factor(self) -> float:
        if self.annualization_factor is not None:
            return self.annualization_factor
        return {
            StrategyBarResolution.DAY: 252.0,
            StrategyBarResolution.HOUR_4: 252.0 * 6.0,
            StrategyBarResolution.HOUR: 252.0 * 24.0,
        }[self.resolution]

    def fingerprint(
        self,
        strategy: StrategyConfiguration,
        dataset_hash: str,
    ) -> str:
        payload = {
            "backtest": self.model_dump(mode="json"),
            "strategy_configuration_fingerprint": strategy.fingerprint,
            "dataset_content_sha256": dataset_hash,
            "runtime_versions": runtime_versions(),
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class FrozenSelection(BaseModel):
    """Immutable validation decision required to release the final TEST split."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["selection-schema-v1"] = "selection-schema-v1"
    selection_identifier: str = Field(min_length=64, max_length=64)
    selected_variant: StrategyVariant
    backtest_configuration: BacktestConfiguration
    strategy_configuration: StrategyConfiguration
    strategy_configuration_fingerprint: str = Field(min_length=64, max_length=64)
    validation_report_fingerprint: str = Field(min_length=64, max_length=64)
    validation_run_fingerprint: str = Field(min_length=64, max_length=64)
    dataset_content_sha256: str = Field(min_length=64, max_length=64)
    dataset_source_filename: str
    chronological_splits: ChronologicalSplits
    validation_metrics: ValidationMetricSummary
    selection_rationale: str = Field(min_length=1, max_length=2_000)
    final_test_authorized: Literal[True] = True

    @model_validator(mode="after")
    def validate_frozen_configuration(self) -> Self:
        if self.backtest_configuration.evaluation_split is not DatasetSplit.VALIDATION:
            raise ValueError("frozen selection must originate from VALIDATION")
        if self.backtest_configuration.variant is not self.selected_variant:
            raise ValueError("selected variant differs from frozen backtest configuration")
        if self.strategy_configuration.variant is not self.selected_variant:
            raise ValueError("selected variant differs from frozen strategy configuration")
        if self.strategy_configuration.fingerprint != self.strategy_configuration_fingerprint:
            raise ValueError("strategy configuration fingerprint mismatch")
        return self

    @property
    def computed_identifier(self) -> str:
        """Recompute the tamper-evident identifier from the frozen payload."""
        payload = self.model_dump(
            mode="json",
            exclude={"selection_identifier", "schema_version"},
        )
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def runtime_versions() -> tuple[tuple[str, str], ...]:
    return (
        ("python", platform.python_version()),
        ("numpy", version("numpy")),
        ("scipy", version("scipy")),
        ("scikit-learn", version("scikit-learn")),
        ("hmmlearn", version("hmmlearn")),
        ("strategy-schema", "strategy-schema-v2"),
        ("backtest-schema", "backtest-schema-v1"),
    )
