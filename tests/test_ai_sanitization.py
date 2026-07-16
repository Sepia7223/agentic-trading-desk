from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from ai_helpers import NOW, enabled_configuration, historical
from trading_desk.ai.models import AnalysisMode, SanitizationReasonCode, SanitizedContext
from trading_desk.ai.sanitization import (
    SanitizationFailure,
    build_request,
    sanitize_context,
    sanitize_historical_examples,
)


@pytest.mark.parametrize(
    ("context", "code"),
    [
        ({"password": "redacted"}, SanitizationReasonCode.SECRET_FIELD_DETECTED),
        ({"api_key": "redacted"}, SanitizationReasonCode.SECRET_FIELD_DETECTED),
        ({"access_token": "redacted"}, SanitizationReasonCode.SECRET_FIELD_DETECTED),
        ({"refresh_token": "redacted"}, SanitizationReasonCode.SECRET_FIELD_DETECTED),
        ({"authorization": "redacted"}, SanitizationReasonCode.RAW_AUTHORIZATION_DATA_DETECTED),
        (
            {"historical_summary": "Authorization: Bearer redacted-value"},
            SanitizationReasonCode.RAW_AUTHORIZATION_DATA_DETECTED,
        ),
        ({"headers": {}}, SanitizationReasonCode.RAW_AUTHORIZATION_DATA_DETECTED),
        ({"raw_response": {}}, SanitizationReasonCode.UNSAFE_FIELD_NAME),
        (
            {"instrument": "C:\\Users\\person\\data.json"},
            SanitizationReasonCode.UNSUPPORTED_CONTEXT,
        ),
        ({"net_pnl": Decimal("NaN")}, SanitizationReasonCode.INVALID_DECIMAL),
        ({"net_pnl": 1.2}, SanitizationReasonCode.INVALID_DECIMAL),
    ],
)
def test_unsafe_context_is_rejected(
    context: dict[str, object], code: SanitizationReasonCode
) -> None:
    with pytest.raises(SanitizationFailure) as captured:
        sanitize_context(context, enabled_configuration())
    assert captured.value.code is code


def test_account_and_broker_identifiers_are_redacted() -> None:
    context = sanitize_context(
        {
            "instrument": "EUR/USD",
            "account_id": "ACCOUNT1234",
            "broker_identifier": "BROKER5678",
        },
        enabled_configuration(),
    )
    assert context.account_reference == "***1234"
    assert context.broker_reference == "***5678"
    assert "ACCOUNT" not in context.model_dump_json()
    assert "BROKER" not in context.model_dump_json()

    with pytest.raises(ValueError, match="must be redacted"):
        SanitizedContext.model_validate(
            {**context.model_dump(mode="python"), "account_reference": "ACCOUNT1234"}
        )


def test_human_notes_and_news_are_policy_controlled() -> None:
    context = sanitize_context(
        {"instrument": "EUR/USD", "human_notes": "private note"},
        enabled_configuration(),
    )
    assert context.human_notes is None
    with pytest.raises(SanitizationFailure):
        sanitize_context(
            {"instrument": "EUR/USD", "news_context": "provided research"},
            enabled_configuration(),
        )
    allowed = sanitize_context(
        {"instrument": "EUR/USD", "news_context": "provided research"},
        enabled_configuration(allow_news_context=True),
    )
    assert allowed.news_context == "provided research"


def test_input_and_record_limits_fail_closed() -> None:
    with pytest.raises(SanitizationFailure) as captured:
        sanitize_context(
            {"historical_summary": "x" * 500},
            enabled_configuration(maximum_input_characters=100),
        )
    assert captured.value.code is SanitizationReasonCode.INPUT_TOO_LARGE
    with pytest.raises(SanitizationFailure) as captured:
        sanitize_historical_examples(
            (historical("one"), historical("two")),
            enabled_configuration(maximum_records_per_request=1),
            evaluation_timestamp=NOW,
        )
    assert captured.value.code is SanitizationReasonCode.TOO_MANY_RECORDS


def test_invalid_or_future_historical_timestamps_fail_closed() -> None:
    raw = historical().model_dump(mode="python")
    raw["timestamp"] = datetime(2026, 1, 1)
    with pytest.raises(SanitizationFailure):
        sanitize_historical_examples((raw,), enabled_configuration(), evaluation_timestamp=NOW)
    future = historical().model_copy(update={"timestamp": NOW.replace(year=2027)})
    with pytest.raises(SanitizationFailure) as captured:
        sanitize_historical_examples((future,), enabled_configuration(), evaluation_timestamp=NOW)
    assert captured.value.code is SanitizationReasonCode.INVALID_TIMESTAMP


def test_request_preserves_safe_source_ids_and_is_fingerprinted() -> None:
    configuration = enabled_configuration()
    context = sanitize_context({"signal_action": "NO_TRADE"}, configuration)
    request = build_request(
        mode=AnalysisMode.SIGNAL_EXPLANATION,
        created_at=NOW,
        source_record_ids=("signal-1", "market-1"),
        context=context,
        historical_examples=(),
        explicit_questions=("What deterministic gates failed?",),
        configuration=configuration,
    )
    assert request.source_record_ids == ("signal-1", "market-1")
    assert request.request_id == request.request_fingerprint
    assert len(request.request_fingerprint) == 64


def test_operational_explicit_question_is_rejected() -> None:
    configuration = enabled_configuration()
    context = sanitize_context({"signal_action": "NO_TRADE"}, configuration)
    with pytest.raises(SanitizationFailure) as captured:
        build_request(
            mode=AnalysisMode.SIGNAL_EXPLANATION,
            created_at=NOW,
            source_record_ids=("signal-1",),
            context=context,
            historical_examples=(),
            explicit_questions=("Please approve trade and place order",),
            configuration=configuration,
        )
    assert captured.value.code is SanitizationReasonCode.UNSAFE_FIELD_NAME
