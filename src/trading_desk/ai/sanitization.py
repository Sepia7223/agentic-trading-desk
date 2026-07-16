"""Deterministic fail-closed sanitization before provider invocation."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal

from pydantic import ValidationError

from trading_desk.ai.config import AIAnalystConfiguration
from trading_desk.ai.errors import AISanitizationError
from trading_desk.ai.fingerprints import canonical_json, fingerprint
from trading_desk.ai.models import (
    POLICY_VERSION,
    AIAnalysisRequest,
    AnalysisMode,
    HistoricalExample,
    SanitizationReasonCode,
    SanitizedContext,
)

_SECRET_KEYS = {
    "password",
    "secret",
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
    "oauth_token",
    "session_token",
    "cst",
    "x_security_token",
}
_AUTH_KEYS = {"authorization", "headers", "http_headers", "oauth", "session"}
_BROKER_RAW_KEYS = {"raw_response", "broker_response", "http_response", "request_headers"}
_LOCAL_PATH = re.compile(r"^(?:[A-Za-z]:[\\/]|/(?:Users|home|var|tmp)/)")
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
_UNSAFE_QUESTIONS = (
    "approve trade",
    "place order",
    "execute order",
    "increase quantity",
    "change risk limit",
    "disable kill switch",
    "close position",
    "guaranteed profit",
)


class SanitizationFailure(AISanitizationError):
    def __init__(self, code: SanitizationReasonCode, message: str) -> None:
        super().__init__(message)
        self.code = code


def sanitize_context(
    raw: Mapping[str, object], configuration: AIAnalystConfiguration
) -> SanitizedContext:
    _validate_structure(raw)
    values = dict(raw)
    account_id = values.pop("account_id", None)
    broker_id = values.pop("broker_identifier", None)
    if account_id is not None:
        values["account_reference"] = _redact(str(account_id))
    if broker_id is not None:
        values["broker_reference"] = _redact(str(broker_id))
    if not configuration.include_human_notes:
        values.pop("human_notes", None)
    if values.get("news_context") is not None and not configuration.allow_news_context:
        raise SanitizationFailure(
            SanitizationReasonCode.UNSUPPORTED_CONTEXT, "news context is disabled by policy"
        )
    if not configuration.include_strategy_details:
        for name in (
            "strategy_variant",
            "signal_action",
            "signal_scores",
            "regime",
            "regime_probabilities",
            "kalman_state",
        ):
            values.pop(name, None)
    if not configuration.include_risk_details:
        for name in ("risk_status", "risk_reason_codes", "approved_quantity"):
            values.pop(name, None)
    if not configuration.include_portfolio_details:
        for name in ("portfolio_equity", "drawdown", "exposure"):
            values.pop(name, None)
    try:
        context = SanitizedContext.model_validate(values)
    except ValidationError as error:
        code = _validation_code(error)
        raise SanitizationFailure(code, "context failed strict sanitization") from None
    if len(canonical_json(context)) > configuration.maximum_input_characters:
        raise SanitizationFailure(
            SanitizationReasonCode.INPUT_TOO_LARGE, "sanitized context exceeds input limit"
        )
    return context


def sanitize_historical_examples(
    raw_records: Sequence[Mapping[str, object] | HistoricalExample],
    configuration: AIAnalystConfiguration,
    *,
    evaluation_timestamp: datetime,
) -> tuple[HistoricalExample, ...]:
    if raw_records and not configuration.allow_historical_similarity_context:
        raise SanitizationFailure(
            SanitizationReasonCode.UNSUPPORTED_CONTEXT,
            "historical similarity context is disabled by policy",
        )
    if len(raw_records) > configuration.maximum_records_per_request:
        raise SanitizationFailure(
            SanitizationReasonCode.TOO_MANY_RECORDS, "historical record limit exceeded"
        )
    records: list[HistoricalExample] = []
    for raw in raw_records:
        values = raw.model_dump(mode="python") if isinstance(raw, HistoricalExample) else dict(raw)
        _validate_structure(values)
        try:
            record = HistoricalExample.model_validate(values)
        except ValidationError as error:
            raise SanitizationFailure(
                _validation_code(error),
                "historical record failed strict sanitization",
            ) from None
        if record.timestamp > evaluation_timestamp:
            raise SanitizationFailure(
                SanitizationReasonCode.INVALID_TIMESTAMP,
                "future historical records are prohibited",
            )
        records.append(record)
    return tuple(sorted(records, key=lambda item: (item.timestamp, item.record_id)))


def build_request(
    *,
    mode: AnalysisMode,
    created_at: datetime,
    source_record_ids: tuple[str, ...],
    context: SanitizedContext,
    historical_examples: tuple[HistoricalExample, ...],
    explicit_questions: tuple[str, ...],
    configuration: AIAnalystConfiguration,
    strategy_configuration_fingerprint: str | None = None,
    risk_configuration_fingerprint: str | None = None,
    portfolio_configuration_fingerprint: str | None = None,
    journal_snapshot_id: str | None = None,
) -> AIAnalysisRequest:
    _validate_structure(source_record_ids)
    _validate_structure(explicit_questions)
    if any(
        phrase in question.lower()
        for question in explicit_questions
        for phrase in _UNSAFE_QUESTIONS
    ):
        raise SanitizationFailure(
            SanitizationReasonCode.UNSAFE_FIELD_NAME,
            "explicit question requests prohibited operational authority",
        )
    base = {
        "mode": mode,
        "created_at": created_at,
        "source_record_ids": source_record_ids,
        "strategy_configuration_fingerprint": strategy_configuration_fingerprint,
        "risk_configuration_fingerprint": risk_configuration_fingerprint,
        "portfolio_configuration_fingerprint": portfolio_configuration_fingerprint,
        "journal_snapshot_id": journal_snapshot_id,
        "sanitized_context": context,
        "historical_examples": historical_examples,
        "explicit_questions": explicit_questions,
        "policy_version": POLICY_VERSION,
        "configuration_fingerprint": configuration.fingerprint,
    }
    request_fingerprint = fingerprint(base)
    if len(canonical_json(base)) > configuration.maximum_input_characters:
        raise SanitizationFailure(
            SanitizationReasonCode.INPUT_TOO_LARGE, "complete sanitized request exceeds input limit"
        )
    return AIAnalysisRequest.model_validate(
        {
            **base,
            "request_id": request_fingerprint,
            "request_fingerprint": request_fingerprint,
        }
    )


def _validate_structure(value: object, *, key: str | None = None) -> None:
    if key is not None:
        normalized = key.lower().replace("-", "_")
        if normalized in _SECRET_KEYS or any(part in normalized for part in ("password", "token")):
            raise SanitizationFailure(
                SanitizationReasonCode.SECRET_FIELD_DETECTED, "secret-like field is prohibited"
            )
        if normalized in _AUTH_KEYS:
            raise SanitizationFailure(
                SanitizationReasonCode.RAW_AUTHORIZATION_DATA_DETECTED,
                "raw authorization structures are prohibited",
            )
        if normalized in _BROKER_RAW_KEYS:
            raise SanitizationFailure(
                SanitizationReasonCode.UNSAFE_FIELD_NAME, "raw broker or HTTP data is prohibited"
            )
    if isinstance(value, Mapping):
        for child_key, child in value.items():
            if not isinstance(child_key, str):
                raise SanitizationFailure(
                    SanitizationReasonCode.UNSAFE_FIELD_NAME, "context keys must be strings"
                )
            _validate_structure(child, key=child_key)
    elif isinstance(value, (tuple, list)):
        for child in value:
            _validate_structure(child)
    elif isinstance(value, float):
        raise SanitizationFailure(
            SanitizationReasonCode.INVALID_DECIMAL,
            "binary floating point is prohibited in sanitized financial context",
        )
    elif isinstance(value, Decimal) and not value.is_finite():
        raise SanitizationFailure(
            SanitizationReasonCode.INVALID_DECIMAL, "non-finite Decimal is prohibited"
        )
    elif isinstance(value, str):
        if _LOCAL_PATH.match(value):
            raise SanitizationFailure(
                SanitizationReasonCode.UNSUPPORTED_CONTEXT,
                "absolute local paths are prohibited",
            )
        if _BEARER.search(value):
            raise SanitizationFailure(
                SanitizationReasonCode.RAW_AUTHORIZATION_DATA_DETECTED,
                "authorization token content is prohibited",
            )


def _redact(value: str) -> str:
    return "***" if len(value) <= 4 else f"***{value[-4:]}"


def _validation_code(error: ValidationError) -> SanitizationReasonCode:
    text = str(error).lower()
    if "datetime" in text or "timestamp" in text:
        return SanitizationReasonCode.INVALID_TIMESTAMP
    if "decimal" in text or "finite" in text:
        return SanitizationReasonCode.INVALID_DECIMAL
    if "field required" in text:
        return SanitizationReasonCode.MISSING_REQUIRED_CONTEXT
    return SanitizationReasonCode.UNSUPPORTED_CONTEXT
