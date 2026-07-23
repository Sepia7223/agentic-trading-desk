"""A4 — advisory synthesizer with one adversarial bear-critique pass (shadow).

Draft -> single bear critique -> revised AdvisoryPacket. Attenuation-only by
type construction (size_scalar in [0.25, 1.0]; veto boolean). Invalid output
at any step degrades to a safe 'no_data' packet — the future non-shadow
consumer treats that as scalar 1.0 / no veto, i.e. zero effect.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

from pydantic import ValidationError

from trading_desk.agents.client import LLMClient
from trading_desk.agents.models import AdvisoryPacket, ArtifactEnvelope, NewsSignal

PROMPT_VERSION = "a4-synth-v1"

SYNTH_SYSTEM = (
    "You synthesize an advisory stance for ONE instrument from classified news "
    "signals and quantitative features. Respond ONLY with JSON: {stance: "
    "supportive|neutral|cautionary|no_data, size_scalar: 0.25..1.0, veto: "
    "bool, key_risks: [<=5 strings], critique_summary: ''}. You may only "
    "REDUCE risk: scalar 1.0 means no effect; veto true blocks the trade. "
    "No text outside the JSON."
)

BEAR_SYSTEM = (
    "You are the adversarial reviewer. Attack the draft advisory: what did it "
    "miss or overweight? Respond ONLY with JSON: {revised_stance: supportive|"
    "neutral|cautionary|no_data, revised_size_scalar: 0.25..1.0, revised_veto: "
    "bool, critique_summary: <=500 chars}. Your revision may only keep or "
    "REDUCE the scalar, never raise it. No text outside the JSON."
)


def _safe_packet(instrument: str, as_of: datetime, input_sha: str, model_id: str) -> AdvisoryPacket:
    return AdvisoryPacket(
        run_id=ArtifactEnvelope.make_run_id("a4-synth", as_of, input_sha),
        agent="a4-synth",
        model_id=model_id,
        prompt_version=PROMPT_VERSION,
        as_of=as_of,
        input_sha256=input_sha,
        instrument=instrument,
        stance="no_data",
        size_scalar=1.0,
        veto=False,
        key_risks=(),
        critique_summary="agent output invalid or absent; packet has no effect",
    )


def synthesize_advisory(
    client: LLMClient,
    *,
    instrument: str,
    news_signals: list[NewsSignal],
    quant_features: dict[str, float],
    as_of: datetime,
) -> AdvisoryPacket:
    packet_input = json.dumps(
        {
            "instrument": instrument,
            "signals": [s.model_dump(mode="json") for s in news_signals],
            "features": quant_features,
        },
        sort_keys=True,
        default=str,
    )
    input_sha = hashlib.sha256(packet_input.encode()).hexdigest()

    try:
        draft_raw = client.complete(SYNTH_SYSTEM, packet_input)
        draft = json.loads(draft_raw)
        critique_raw = client.complete(
            BEAR_SYSTEM, json.dumps({"input": packet_input, "draft": draft})
        )
        critique = json.loads(critique_raw)
    except (RuntimeError, json.JSONDecodeError):
        return _safe_packet(instrument, as_of, input_sha, client.model_id)

    try:
        draft_scalar = float(draft.get("size_scalar", 1.0))
        revised_scalar = float(critique.get("revised_size_scalar", draft_scalar))
        # the critique may only keep or REDUCE the scalar
        final_scalar = min(draft_scalar, revised_scalar)
        return AdvisoryPacket(
            run_id=ArtifactEnvelope.make_run_id("a4-synth", as_of, input_sha),
            agent="a4-synth",
            model_id=client.model_id,
            prompt_version=PROMPT_VERSION,
            as_of=as_of,
            input_sha256=input_sha,
            instrument=instrument,
            stance=critique.get("revised_stance", draft.get("stance", "no_data")),
            size_scalar=final_scalar,
            veto=bool(draft.get("veto", False)) or bool(critique.get("revised_veto", False)),
            key_risks=tuple(draft.get("key_risks", ())[:5]),
            critique_summary=str(critique.get("critique_summary", ""))[:500],
        )
    except (ValidationError, TypeError, ValueError):
        return _safe_packet(instrument, as_of, input_sha, client.model_id)
