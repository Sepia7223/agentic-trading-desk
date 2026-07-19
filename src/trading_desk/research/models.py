"""Immutable experiment contracts for governed offline strategy research.

Research is an analysis activity with no operational authority: experiment
records rank candidates for human review and Milestone 12 governance; they
cannot change strategy lifecycle state, Demo configuration, or any
operational system.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from trading_desk.context.fingerprints import fingerprint
from trading_desk.strategy.validation_orchestration import StageBoundaries


class ResearchModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


class ExperimentStatus(StrEnum):
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ObjectiveName(StrEnum):
    NET_EXPECTANCY = "NET_EXPECTANCY"
    SHARPE_RATIO = "SHARPE_RATIO"
    PROFIT_FACTOR = "PROFIT_FACTOR"


class ParameterRange(ResearchModel):
    """One bounded, stepped axis of a frozen search space."""

    name: str = Field(min_length=1)
    minimum: Decimal
    maximum: Decimal
    step: Decimal = Field(gt=0)

    @model_validator(mode="after")
    def bounded(self) -> Self:
        if self.maximum < self.minimum:
            raise ValueError("parameter range maximum is below minimum")
        if (self.maximum - self.minimum) / self.step > 200:
            raise ValueError("parameter range exceeds the bounded search budget")
        return self

    def values(self) -> tuple[Decimal, ...]:
        result: list[Decimal] = []
        value = self.minimum
        while value <= self.maximum:
            result.append(value)
            value += self.step
        return tuple(result)


class ResourceBudget(ResearchModel):
    """Hard, enforced execution bounds; exceeding a bound cancels the run."""

    maximum_trials: int = Field(default=64, ge=1, le=512)
    maximum_wall_clock_seconds: int = Field(default=3600, ge=0)
    maximum_bars_per_series: int = Field(default=200_000, ge=1_000)


class ExperimentSpecification(ResearchModel):
    """Frozen before execution; the experiment identity covers every input."""

    schema_version: Literal["research-experiment-v1"] = "research-experiment-v1"
    experiment_id: str = Field(min_length=64, max_length=64)
    title: str = Field(min_length=1, max_length=200)
    hypothesis: str = Field(min_length=1)
    strategy_family: Literal["trend-pullback-v1", "volatility-breakout", "range-mean-reversion"]
    parameter_space: tuple[ParameterRange, ...] = Field(min_length=1)
    objective: ObjectiveName = ObjectiveName.NET_EXPECTANCY
    random_seed: int = Field(default=42, ge=0)
    dataset_fingerprint: str = Field(min_length=64, max_length=64)
    bars_root_declared: str
    pairs: tuple[str, ...] = Field(min_length=1)
    timeframes: tuple[str, ...] = Field(min_length=1)
    boundaries: StageBoundaries
    inner_window_count: int = Field(default=3, ge=2, le=12)
    macro_scoring_included: bool
    staleness_gates_included: bool
    budget: ResourceBudget = ResourceBudget()
    parent_experiment_ids: tuple[str, ...] = ()
    created_at: datetime
    created_by: str = Field(min_length=1)

    @field_validator("created_at")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("experiment timestamps must be UTC")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def identity_and_isolation(self) -> Self:
        names = [item.name for item in self.parameter_space]
        if len(names) != len(set(names)):
            raise ValueError("parameter axes must be unique")
        expected = fingerprint(self.model_dump(mode="python", exclude={"experiment_id"}))
        if self.experiment_id != expected:
            raise ValueError("experiment specification fingerprint mismatch")
        return self


class TrialMetrics(ResearchModel):
    trade_count: int = Field(ge=0)
    net_expectancy: Decimal | None
    profit_factor: Decimal | None
    sharpe_ratio: Decimal | None
    maximum_drawdown: Decimal = Field(ge=0)

    def objective_value(self, objective: ObjectiveName) -> Decimal | None:
        return {
            ObjectiveName.NET_EXPECTANCY: self.net_expectancy,
            ObjectiveName.SHARPE_RATIO: self.sharpe_ratio,
            ObjectiveName.PROFIT_FACTOR: self.profit_factor,
        }[objective]


class TrialResult(ResearchModel):
    trial_index: int = Field(ge=0)
    parameters: tuple[tuple[str, str], ...]
    configuration_fingerprint: str = Field(min_length=64, max_length=64)
    inner_selection: TrialMetrics
    outer_evaluation: TrialMetrics
    trial_fingerprint: str = Field(min_length=64, max_length=64)

    @model_validator(mode="after")
    def identity(self) -> Self:
        expected = fingerprint(self.model_dump(mode="python", exclude={"trial_fingerprint"}))
        if self.trial_fingerprint != expected:
            raise ValueError("trial fingerprint mismatch")
        return self


class ExperimentDiagnostics(ResearchModel):
    """Multiple-comparison and overfitting diagnostics for the whole run."""

    trial_count: int = Field(ge=0)
    completed_trial_count: int = Field(ge=0)
    best_outer_objective: Decimal | None
    mean_outer_objective: Decimal | None
    expected_best_under_null: Decimal | None
    development_to_validation_degradation: Decimal | None
    neighborhood_stability: Decimal | None
    isolated_optimum_rejected: bool
    benchmark_objective: Decimal
    beats_benchmark: bool
    economic_plausibility_notes: str


class ExperimentRecord(ResearchModel):
    """Append-only registry entry; failed and cancelled runs are retained."""

    schema_version: Literal["research-record-v1"] = "research-record-v1"
    record_id: str = Field(min_length=64, max_length=64)
    previous_record_id: str | None = Field(default=None, min_length=64, max_length=64)
    specification: ExperimentSpecification
    status: ExperimentStatus
    status_reason: str = ""
    code_fingerprint: str = Field(min_length=64, max_length=64)
    trials: tuple[TrialResult, ...] = ()
    diagnostics: ExperimentDiagnostics | None = None
    ranked_trial_indices: tuple[int, ...] = ()
    started_at: datetime
    finished_at: datetime
    advisory_statement: Literal[
        "Research output ranks candidates for human review only; it grants no"
        " lifecycle, Demo, Risk, execution, or Live authority."
    ] = (
        "Research output ranks candidates for human review only; it grants no"
        " lifecycle, Demo, Risk, execution, or Live authority."
    )

    @model_validator(mode="after")
    def identity(self) -> Self:
        if self.finished_at < self.started_at:
            raise ValueError("experiment finish precedes start")
        expected = fingerprint(self.model_dump(mode="python", exclude={"record_id"}))
        if self.record_id != expected:
            raise ValueError("experiment record fingerprint mismatch")
        return self


def create_specification(**values: object) -> ExperimentSpecification:
    draft_fields = {**values, "experiment_id": "0" * 64}
    draft = ExperimentSpecification.model_construct(**draft_fields)  # type: ignore[arg-type]
    fields = draft.model_dump(mode="python", exclude={"experiment_id"})
    return ExperimentSpecification.model_validate({**fields, "experiment_id": fingerprint(fields)})


def create_trial(**values: object) -> TrialResult:
    fields = dict(values)
    return TrialResult.model_validate({**fields, "trial_fingerprint": fingerprint(fields)})


def create_record(**values: object) -> ExperimentRecord:
    draft_fields = {**values, "record_id": "0" * 64}
    draft = ExperimentRecord.model_construct(**draft_fields)  # type: ignore[arg-type]
    fields = draft.model_dump(mode="python", exclude={"record_id"})
    return ExperimentRecord.model_validate({**fields, "record_id": fingerprint(fields)})
