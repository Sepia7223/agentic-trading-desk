"""Provider-neutral interface and deterministic test provider."""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol

from trading_desk.ai.fingerprints import fingerprint
from trading_desk.ai.models import (
    ADVISORY_STATEMENT,
    AIAnalysisRequest,
    AIAnalysisResponse,
    Observation,
    ResearchHypothesis,
)


class AIAnalysisProvider(Protocol):
    network_access: bool

    async def analyze(self, request: AIAnalysisRequest) -> object:
        """Return structured advisory content without operational authority."""


class DeterministicFakeProvider:
    """Stable local provider for tests; performs no network activity."""

    network_access = False

    def __init__(
        self,
        *,
        provider_name: str = "deterministic-fake",
        model_name: str = "fake-v1",
        failure: Exception | None = None,
        malformed: object | None = None,
    ) -> None:
        self.provider_name = provider_name
        self.model_name = model_name
        self.failure = failure
        self.malformed = malformed
        self.calls = 0

    async def analyze(self, request: AIAnalysisRequest) -> object:
        self.calls += 1
        if self.failure is not None:
            raise self.failure
        if self.malformed is not None:
            return self.malformed
        first_source = request.source_record_ids[0]
        mode_name = request.mode.value.replace("_", " ").lower()
        hypotheses = (
            (
                ResearchHypothesis(
                    hypothesis_id=fingerprint(
                        {"request_id": request.request_id, "kind": "research"}
                    ),
                    statement="Evaluate whether the observed pattern persists out of sample.",
                    rationale=(
                        "The supplied evidence is descriptive and requires controlled testing."
                    ),
                    required_dataset=(
                        "Chronological sanitized research dataset with held-out test data."
                    ),
                    proposed_test="Run a leakage-controlled deterministic ablation before review.",
                    prohibited_automatic_action=True,
                ),
            )
            if request.mode.value == "RESEARCH_HYPOTHESIS"
            else ()
        )
        fields = {
            "request_id": request.request_id,
            "mode": request.mode,
            "created_at": request.created_at,
            "summary": f"Advisory {mode_name} completed from sanitized deterministic records.",
            "observations": (
                Observation(
                    category="DETERMINISTIC_RECORD_REVIEW",
                    statement="The supplied deterministic record remains authoritative.",
                    supporting_record_ids=(first_source,),
                    confidence=Decimal("1"),
                    limitation="Provider narrative is advisory and not guaranteed reproducible.",
                ),
            ),
            "evidence": (f"source:{first_source}",),
            "uncertainties": ("No information beyond sanitized inputs was inferred.",),
            "risk_flags": (),
            "process_findings": ("Human review is required before research use.",),
            "historical_comparisons": (),
            "research_hypotheses": hypotheses,
            "recommended_human_actions": ("Review the linked deterministic records.",),
            "prohibited_actions_acknowledged": True,
            "advisory_statement": ADVISORY_STATEMENT,
            "source_record_ids": request.source_record_ids,
            "provider_name": self.provider_name,
            "model_name": self.model_name,
            "configuration_fingerprint": request.configuration_fingerprint,
            "request_fingerprint": request.request_fingerprint,
        }
        response_fingerprint = fingerprint(fields)
        return AIAnalysisResponse.model_validate(
            {
                **fields,
                "response_id": response_fingerprint,
                "response_fingerprint": response_fingerprint,
            }
        )
