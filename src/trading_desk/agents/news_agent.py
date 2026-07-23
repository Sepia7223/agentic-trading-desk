"""A1 — news/event classifier (shadow). One headline packet -> NewsSignal.

The model must answer in strict JSON matching the NewsSignal fields; anything
that fails schema validation or the verbatim-evidence check is DISCARDED (and
reported as None) — never repaired. Abstention is legal and unpenalized.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

from pydantic import ValidationError

from trading_desk.agents.client import LLMClient
from trading_desk.agents.models import ArtifactEnvelope, NewsSignal
from trading_desk.agents.validators import EvidenceError, validate_evidence

PROMPT_VERSION = "a1-news-v1"

SYSTEM = (
    "You classify financial news for a trading research system. Respond with "
    "ONLY a JSON object: {event_type: earnings|guidance|macro|regulatory|mna|"
    "litigation|other, direction: bullish|bearish|neutral, relevance: direct|"
    "sector|macro, horizon: intraday|days|weeks, confidence: 0..1, rationale: "
    "<=400 chars, evidence: [{source_id, quote}], abstained: bool}. Every "
    "quote MUST be copied verbatim from a source. If unsure, set abstained "
    "true with direction neutral. No text outside the JSON."
)


def classify_news(
    client: LLMClient,
    *,
    instrument: str,
    sources: dict[str, str],
    as_of: datetime,
) -> NewsSignal | None:
    """Classify one instrument's news packet; None if the output is invalid."""

    packet = json.dumps({"instrument": instrument, "sources": sources}, sort_keys=True)
    input_sha = hashlib.sha256(packet.encode()).hexdigest()
    user = f"Instrument: {instrument}\nSources (id -> text):\n{packet}"
    raw = client.complete(SYSTEM, user)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    try:
        signal = NewsSignal(
            run_id=ArtifactEnvelope.make_run_id("a1-news", as_of, input_sha),
            agent="a1-news",
            model_id=client.model_id,
            prompt_version=PROMPT_VERSION,
            as_of=as_of,
            input_sha256=input_sha,
            instrument=instrument,
            **payload,
        )
    except (ValidationError, TypeError):
        return None
    try:
        validate_evidence(signal.evidence, sources)
    except EvidenceError:
        return None
    return signal
