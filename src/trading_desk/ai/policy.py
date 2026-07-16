"""Advisory-only request and response policy enforcement."""

from __future__ import annotations

from pydantic import ValidationError

from trading_desk.ai.config import AIAnalystConfiguration
from trading_desk.ai.errors import AIPolicyViolation
from trading_desk.ai.fingerprints import canonical_json, fingerprint
from trading_desk.ai.models import AIAnalysisRequest, AIAnalysisResponse

_PROHIBITED_RECOMMENDATIONS = (
    "approve trade",
    "place order",
    "execute order",
    "increase quantity",
    "position size",
    "change risk limit",
    "disable kill switch",
    "reset consecutive",
    "close position",
    "modify portfolio",
    "guaranteed profit",
    "guaranteed return",
)


def validate_response(
    raw: object,
    request: AIAnalysisRequest,
    configuration: AIAnalystConfiguration,
) -> AIAnalysisResponse:
    try:
        payload = raw.model_dump(mode="python") if isinstance(raw, AIAnalysisResponse) else raw
        response = AIAnalysisResponse.model_validate(payload)
    except ValidationError as error:
        if any("fingerprint" in item["msg"].lower() for item in error.errors()):
            raise AIPolicyViolation("provider response fingerprint is invalid") from error
        raise AIPolicyViolation("provider response failed structured validation") from error
    except Exception as error:
        raise AIPolicyViolation("provider response failed structured validation") from error
    if response.request_id != request.request_id or response.mode is not request.mode:
        raise AIPolicyViolation("provider response does not match request")
    if response.created_at != request.created_at:
        raise AIPolicyViolation("provider response timestamp does not match explicit request time")
    if response.configuration_fingerprint != configuration.fingerprint:
        raise AIPolicyViolation("provider response configuration mismatch")
    if (
        response.provider_name != configuration.provider_name
        or response.model_name != configuration.model_name
    ):
        raise AIPolicyViolation("provider response metadata mismatch")
    if response.request_fingerprint != request.request_fingerprint:
        raise AIPolicyViolation("provider response request fingerprint mismatch")
    if response.source_record_ids != request.source_record_ids:
        raise AIPolicyViolation("provider response source links are incomplete or changed")
    allowed_sources = set(request.source_record_ids)
    if any(
        not item.supporting_record_ids
        or not set(item.supporting_record_ids).issubset(allowed_sources)
        for item in response.observations
    ):
        raise AIPolicyViolation("observation evidence references unsupported source records")
    content = " ".join(
        (
            response.summary,
            *response.recommended_human_actions,
            *(item.statement for item in response.observations),
            *(item.statement for item in response.research_hypotheses),
        )
    ).lower()
    if any(phrase in content for phrase in _PROHIBITED_RECOMMENDATIONS):
        raise AIPolicyViolation("provider response contains a prohibited operational action")
    if len(canonical_json(response)) > configuration.maximum_output_characters:
        raise AIPolicyViolation("provider response exceeds configured output limit")
    fields = response.model_dump(mode="python", exclude={"response_id", "response_fingerprint"})
    if response.response_fingerprint != fingerprint(fields):
        raise AIPolicyViolation("provider response fingerprint is invalid")
    return response
