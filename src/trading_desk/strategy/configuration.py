"""Immutable configuration for the deterministic regime-aware strategy."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from trading_desk.strategy.models import StrategyVariant


class StrategyConfiguration(BaseModel):
    """Safety-critical model and gate settings with deterministic defaults."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy_schema_version: Literal["strategy-schema-v2"] = "strategy-schema-v2"
    variant: StrategyVariant = StrategyVariant.BASELINE_KALMAN_HMM
    minimum_bars_required: int = Field(default=220, ge=210, le=5000)
    kalman_minimum_observations: int = Field(default=30, ge=3)
    kalman_process_level_noise: float = Field(default=1e-3, gt=0)
    kalman_process_slope_noise: float = Field(default=1e-5, gt=0)
    kalman_observation_noise: float = Field(default=1e-2, gt=0)
    kalman_initial_level_variance: float = Field(default=1.0, gt=0)
    kalman_initial_slope_variance: float = Field(default=1.0, gt=0)
    maximum_kalman_normalized_slope_uncertainty: float = Field(default=0.01, ge=0)
    minimum_entry_deviation: float = -2.0
    maximum_entry_deviation: float = 1.0

    hmm_state_count: Literal[3] = 3
    hmm_training_iterations: int = Field(default=200, ge=2, le=5000)
    hmm_convergence_tolerance: float = Field(default=1e-3, gt=0)
    hmm_random_seed: int = 42
    hmm_rolling_window: int = Field(default=20, ge=2, le=252)
    hmm_minimum_feature_observations: int = Field(default=120, ge=30)
    hmm_minimum_effective_observations: float = Field(default=10.0, gt=0)
    hmm_covariance_floor: float = Field(default=1e-6, gt=0)
    hmm_mapping_minimum_score_margin: float = Field(default=0.20, gt=0)
    maximum_absolute_standardized_feature: float = Field(default=20.0, gt=0)
    minimum_regime_probability: float = Field(default=0.60, ge=0, le=1)
    maximum_regime_uncertainty: float = Field(default=0.65, ge=0, le=1)

    maximum_spread_bps: float = Field(default=10.0, ge=0)
    minimum_trend_score: int = Field(default=1, ge=-2, le=2)
    minimum_momentum_score: int = Field(default=1, ge=-2, le=2)
    daily_maximum_age_seconds: int = Field(default=129600, ge=1)
    daily_weekend_grace_seconds: int = Field(default=172800, ge=0)
    intraday_maximum_age_multiple: float = Field(default=2.0, gt=1)
    maximum_gap_multiple: float = Field(default=4.0, gt=1)
    require_macro_confirmation: bool = False
    long_only: Literal[True] = True
    allow_transitional_regime_entries: Literal[False] = False

    @field_validator(
        "kalman_process_level_noise",
        "kalman_process_slope_noise",
        "kalman_observation_noise",
        "kalman_initial_level_variance",
        "kalman_initial_slope_variance",
        "maximum_kalman_normalized_slope_uncertainty",
        "minimum_entry_deviation",
        "maximum_entry_deviation",
        "hmm_convergence_tolerance",
        "hmm_minimum_effective_observations",
        "hmm_covariance_floor",
        "hmm_mapping_minimum_score_margin",
        "maximum_absolute_standardized_feature",
        "minimum_regime_probability",
        "maximum_regime_uncertainty",
        "maximum_spread_bps",
        "intraday_maximum_age_multiple",
        "maximum_gap_multiple",
    )
    @classmethod
    def reject_non_finite_numbers(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("strategy numeric configuration must be finite")
        return value

    @model_validator(mode="after")
    def validate_cross_field_constraints(self) -> Self:
        if self.kalman_minimum_observations > self.minimum_bars_required:
            raise ValueError("Kalman minimum observations cannot exceed minimum bars")
        if self.minimum_entry_deviation > self.maximum_entry_deviation:
            raise ValueError("entry deviation bounds are reversed")
        usable = self.minimum_bars_required - self.hmm_rolling_window
        if usable < self.hmm_minimum_feature_observations:
            raise ValueError("minimum bars cannot provide the required HMM feature history")
        if self.hmm_minimum_effective_observations * self.hmm_state_count >= usable:
            raise ValueError("minimum bars cannot support all HMM states")
        return self

    @property
    def fingerprint_payload(self) -> str:
        """Canonical secret-free payload containing every strategy setting."""

        return json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )

    @property
    def fingerprint(self) -> str:
        payload = self.fingerprint_payload.encode("utf-8")
        return hashlib.sha256(payload).hexdigest()
