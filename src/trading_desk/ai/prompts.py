"""Versioned deterministic prompt construction."""

from trading_desk.ai.fingerprints import canonical_json, fingerprint
from trading_desk.ai.models import ADVISORY_STATEMENT, PROMPT_VERSION, AIAnalysisRequest


def build_prompt(request: AIAnalysisRequest) -> str:
    instructions = (
        "Deterministic strategy, risk, and portfolio records are authoritative.",
        ADVISORY_STATEMENT,
        "Do not invent missing data; identify uncertainty explicitly.",
        "Reference only supplied source record IDs for evidence.",
        "Do not approve or reject trades, determine or increase quantity, or change stops.",
        "Do not propose risk-limit, kill-switch, portfolio, or strategy configuration changes.",
        "Do not provide order instructions or claim guaranteed profitability.",
        "Do not rewrite, suppress, or contradict supplied historical evidence.",
        "Return only the required structured advisory response.",
    )
    payload = {
        "prompt_version": PROMPT_VERSION,
        "mode": request.mode,
        "instructions": instructions,
        "source_record_ids": request.source_record_ids,
        "missing_data_policy": "UNAVAILABLE fields remain unavailable",
        "request": request,
    }
    return canonical_json(payload)


def prompt_fingerprint(request: AIAnalysisRequest) -> str:
    return fingerprint(build_prompt(request))
