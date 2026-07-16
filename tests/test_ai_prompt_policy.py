from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest

from ai_helpers import NOW, analyst, context_for, enabled_configuration
from trading_desk.ai.errors import AIPolicyViolation
from trading_desk.ai.fingerprints import fingerprint
from trading_desk.ai.models import ADVISORY_STATEMENT, AnalysisMode
from trading_desk.ai.policy import validate_response
from trading_desk.ai.prompts import build_prompt, prompt_fingerprint
from trading_desk.ai.sanitization import build_request, sanitize_context


def request_and_response():  # type: ignore[no-untyped-def]
    service, provider = analyst()
    result = asyncio.run(
        service.analyze_context(
            mode=AnalysisMode.SIGNAL_EXPLANATION,
            created_at=NOW,
            source_record_ids=("signal-1",),
            raw_context=context_for(AnalysisMode.SIGNAL_EXPLANATION),
        )
    )
    assert result.response is not None
    configuration = service.configuration
    request = build_request(
        mode=AnalysisMode.SIGNAL_EXPLANATION,
        created_at=NOW,
        source_record_ids=("signal-1",),
        context=sanitize_context(context_for(AnalysisMode.SIGNAL_EXPLANATION), configuration),
        historical_examples=(),
        explicit_questions=(),
        configuration=configuration,
    )
    assert provider.calls == 1
    return request, result.response, configuration


def test_prompt_is_deterministic_versioned_and_advisory() -> None:
    request, _, _ = request_and_response()
    first = build_prompt(request)
    second = build_prompt(request)
    assert first == second
    assert prompt_fingerprint(request) == prompt_fingerprint(request)
    assert AnalysisMode.SIGNAL_EXPLANATION.value in first
    assert ADVISORY_STATEMENT in first
    assert "signal-1" in first
    assert "Do not invent missing data" in first
    assert "Do not approve or reject trades" in first
    assert "guaranteed profitability" in first
    assert "password" not in first.lower()


def _refingerprint(response, **updates):  # type: ignore[no-untyped-def]
    changed = response.model_copy(update=updates)
    fields = changed.model_dump(mode="python", exclude={"response_id", "response_fingerprint"})
    value = fingerprint(fields)
    return changed.model_copy(update={"response_id": value, "response_fingerprint": value})


@pytest.mark.parametrize(
    "recommendation",
    [
        "Approve trade after review.",
        "Place order now.",
        "Increase quantity.",
        "Change risk limit.",
        "Disable kill switch.",
        "Close position.",
        "This is guaranteed profit.",
    ],
)
def test_operational_or_guaranteed_recommendations_are_rejected(
    recommendation: str,
) -> None:
    request, response, configuration = request_and_response()
    unsafe = _refingerprint(response, recommended_human_actions=(recommendation,))
    with pytest.raises(AIPolicyViolation, match="prohibited"):
        validate_response(unsafe, request, configuration)


def test_missing_advisory_acknowledgment_or_changed_banner_is_rejected() -> None:
    request, response, configuration = request_and_response()
    missing_ack = _refingerprint(response, prohibited_actions_acknowledged=False)
    with pytest.raises(AIPolicyViolation, match="structured validation"):
        validate_response(missing_ack, request, configuration)
    changed = _refingerprint(response, advisory_statement="Not advisory")
    with pytest.raises(AIPolicyViolation, match="structured validation"):
        validate_response(changed, request, configuration)


def test_source_links_and_confidence_are_validated() -> None:
    request, response, configuration = request_and_response()
    missing_source = _refingerprint(response, source_record_ids=("other",))
    with pytest.raises(AIPolicyViolation, match="source links"):
        validate_response(missing_source, request, configuration)
    bad_observation = response.observations[0].model_copy(update={"confidence": Decimal("2")})
    invalid = _refingerprint(response, observations=(bad_observation,))
    with pytest.raises(AIPolicyViolation, match="structured validation"):
        validate_response(invalid, request, configuration)
    unsupported = response.observations[0].model_copy(
        update={"supporting_record_ids": ("invented-source",)}
    )
    invalid_evidence = _refingerprint(response, observations=(unsupported,))
    with pytest.raises(AIPolicyViolation, match="unsupported source"):
        validate_response(invalid_evidence, request, configuration)


def test_output_length_and_response_fingerprint_are_enforced() -> None:
    request, response, _ = request_and_response()
    small_limit = enabled_configuration(maximum_output_characters=100)
    changed_config = _refingerprint(response, configuration_fingerprint=small_limit.fingerprint)
    with pytest.raises(AIPolicyViolation, match="output limit"):
        validate_response(changed_config, request, small_limit)
    bad_fingerprint = response.model_copy(update={"response_fingerprint": "f" * 64})
    with pytest.raises(AIPolicyViolation, match="fingerprint"):
        validate_response(bad_fingerprint, request, request_and_response()[2])
