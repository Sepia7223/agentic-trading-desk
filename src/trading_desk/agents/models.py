"""Typed artifact contracts for the advisory agents (closed vocabularies).

Vague outputs are structurally impossible: direction/stance/horizon are
Literals, free text is confined to bounded display-only fields, every claim
must carry verbatim evidence quotes (hard-checked by validators), abstention
is a legal first-class outcome, and confidence is display-only until the
calibration log proves otherwise.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


class Evidence(_Frozen):
    source_id: str = Field(min_length=1)
    quote: str = Field(min_length=1)  # must string-match the source verbatim


class ArtifactEnvelope(_Frozen):
    """Replayability fields carried by every artifact."""

    schema_version: Literal["1"] = "1"
    run_id: str = Field(min_length=1)  # deterministic: date+agent+input hash
    agent: str = Field(min_length=1)
    model_id: str = Field(min_length=1)  # pinned model or "mock"
    prompt_version: str = Field(min_length=1)
    as_of: datetime  # data cutoff of the input packet, not wall clock
    input_sha256: str = Field(min_length=16)
    shadow: Literal[True] = True  # Phase 3 artifacts are shadow-only

    @staticmethod
    def make_run_id(agent: str, as_of: datetime, input_sha256: str) -> str:
        seed = f"{agent}|{as_of.date().isoformat()}|{input_sha256[:16]}"
        return hashlib.sha256(seed.encode()).hexdigest()[:20]


class NewsSignal(ArtifactEnvelope):
    """A1 output: one classified news/filing item for one instrument."""

    instrument: str = Field(min_length=1)
    event_type: Literal["earnings", "guidance", "macro", "regulatory", "mna", "litigation", "other"]
    direction: Literal["bullish", "bearish", "neutral"]
    relevance: Literal["direct", "sector", "macro"]
    horizon: Literal["intraday", "days", "weeks"]
    confidence: float = Field(ge=0.0, le=1.0)  # DISPLAY-ONLY until calibrated
    rationale: str = Field(max_length=400)
    evidence: tuple[Evidence, ...] = Field(min_length=1)
    abstained: bool = False


class RegimeAssessment(ArtifactEnvelope):
    """A2 output: narration of OUR computed stats (nothing to hallucinate)."""

    regime: Literal["trend_up", "trend_down", "range", "stress"]
    stability: Literal["stable", "transitioning"]
    narrative: str = Field(max_length=600)


class AdvisoryPacket(ArtifactEnvelope):
    """A4 output — the ONLY artifact a future non-shadow mode may consume.

    Attenuation-only by construction: size_scalar can shrink a position, never
    grow it; veto adds a rejection; absence of a packet means scalar 1.0 and
    no veto (the pipeline runs unchanged if the agent layer is down).
    """

    instrument: str = Field(min_length=1)
    stance: Literal["supportive", "neutral", "cautionary", "no_data"]
    size_scalar: float = Field(ge=0.25, le=1.0)
    veto: bool = False
    key_risks: tuple[str, ...] = Field(max_length=5)
    evidence: tuple[Evidence, ...] = ()
    critique_summary: str = Field(max_length=500)
