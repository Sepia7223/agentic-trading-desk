"""Explicit, authority-free handoff from research into Milestone 12 governance.

A handoff document proposes a candidate configuration for a NEW strategy
version starting at ``RESEARCH_ONLY``. It changes nothing by itself: the
proposed version must pass the full Milestone 12 validation pipeline (with a
fresh untouched final-test partition) and receive a named human promotion
decision before any lifecycle state changes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from trading_desk.context.fingerprints import fingerprint
from trading_desk.research.models import ExperimentRecord, ExperimentStatus


class HandoffError(ValueError):
    """Raised when a research result cannot be handed off safely."""


class CandidateHandoff(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    schema_version: Literal["research-handoff-v1"] = "research-handoff-v1"
    handoff_id: str = Field(min_length=64, max_length=64)
    experiment_record_id: str = Field(min_length=64, max_length=64)
    strategy_family: str
    proposed_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    parameters: tuple[tuple[str, str], ...]
    configuration_fingerprint: str = Field(min_length=64, max_length=64)
    outer_objective_value: str
    diagnostics_summary: tuple[tuple[str, str], ...]
    proposed_lifecycle_state: Literal["RESEARCH_ONLY"] = "RESEARCH_ONLY"
    requires_new_final_test_partition: Literal[True] = True
    prepared_by: str = Field(min_length=1)

    @model_validator(mode="after")
    def identity(self) -> Self:
        expected = fingerprint(self.model_dump(mode="python", exclude={"handoff_id"}))
        if self.handoff_id != expected:
            raise ValueError("handoff fingerprint mismatch")
        return self


def create_handoff(**values: object) -> CandidateHandoff:
    draft_fields = {**values, "handoff_id": "0" * 64}
    draft = CandidateHandoff.model_construct(**draft_fields)  # type: ignore[arg-type]
    fields = draft.model_dump(mode="python", exclude={"handoff_id"})
    return CandidateHandoff.model_validate({**fields, "handoff_id": fingerprint(fields)})


def build_handoff(
    record: ExperimentRecord, *, trial_index: int, proposed_version: str, prepared_by: str
) -> CandidateHandoff:
    if record.status is not ExperimentStatus.COMPLETED:
        raise HandoffError("only completed experiments can be handed off")
    if record.diagnostics is None:
        raise HandoffError("handoff requires experiment diagnostics")
    if record.diagnostics.isolated_optimum_rejected:
        raise HandoffError("the selected optimum was rejected as an isolated spike")
    trial = next((item for item in record.trials if item.trial_index == trial_index), None)
    if trial is None:
        raise HandoffError("unknown trial index")
    objective = trial.outer_evaluation.objective_value(record.specification.objective)
    if objective is None or objective <= 0:
        raise HandoffError("candidate lacks a positive out-of-selection objective")
    diagnostics = record.diagnostics
    fields = {
        "experiment_record_id": record.record_id,
        "strategy_family": record.specification.strategy_family,
        "proposed_version": proposed_version,
        "parameters": trial.parameters,
        "configuration_fingerprint": trial.configuration_fingerprint,
        "outer_objective_value": str(objective),
        "diagnostics_summary": (
            ("trial_count", str(diagnostics.trial_count)),
            ("expected_best_under_null", str(diagnostics.expected_best_under_null)),
            (
                "development_to_validation_degradation",
                str(diagnostics.development_to_validation_degradation),
            ),
            ("neighborhood_stability", str(diagnostics.neighborhood_stability)),
            ("beats_benchmark", str(diagnostics.beats_benchmark)),
        ),
        "prepared_by": prepared_by,
    }
    return create_handoff(**fields)


def write_handoff(handoff: CandidateHandoff, path: Path) -> None:
    if path.exists():
        raise HandoffError("handoff documents are immutable once written")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(json.loads(handoff.model_dump_json()), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
