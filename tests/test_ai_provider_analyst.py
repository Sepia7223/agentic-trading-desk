from __future__ import annotations

import asyncio
from copy import deepcopy

import pytest

from ai_helpers import NOW, analyst, context_for, enabled_configuration, historical
from trading_desk.ai import AIAnalyst, AnalysisMode, AnalysisStatus
from trading_desk.ai.fingerprints import fingerprint
from trading_desk.ai.models import ADVISORY_STATEMENT, SanitizationReasonCode
from trading_desk.ai.provider import DeterministicFakeProvider
from trading_desk.ai.sanitization import build_request, sanitize_context


@pytest.mark.parametrize(
    "mode",
    [
        AnalysisMode.SIGNAL_EXPLANATION,
        AnalysisMode.RISK_DECISION_EXPLANATION,
        AnalysisMode.TRADE_REVIEW,
        AnalysisMode.DAILY_REVIEW,
        AnalysisMode.WEEKLY_REVIEW,
        AnalysisMode.MONTHLY_REVIEW,
        AnalysisMode.PORTFOLIO_SUMMARY,
        AnalysisMode.ANOMALY_REVIEW,
        AnalysisMode.RESEARCH_HYPOTHESIS,
    ],
)
def test_fake_provider_completes_supported_advisory_modes(mode: AnalysisMode) -> None:
    service, provider = analyst()
    result = asyncio.run(
        service.analyze_context(
            mode=mode,
            created_at=NOW,
            source_record_ids=(f"source-{mode.value}",),
            raw_context=context_for(mode),
        )
    )
    assert result.status is AnalysisStatus.COMPLETED
    assert result.response is not None and result.record is not None
    assert result.response.advisory_statement == ADVISORY_STATEMENT
    assert result.response.prohibited_actions_acknowledged is True
    assert result.record.source_record_ids == result.response.source_record_ids
    assert provider.calls == 1


def test_historical_comparison_requires_and_accepts_structured_history() -> None:
    service, provider = analyst()
    missing = asyncio.run(
        service.analyze_context(
            mode=AnalysisMode.HISTORICAL_COMPARISON,
            created_at=NOW,
            source_record_ids=("trade-1",),
            raw_context={"instrument": "EUR/USD"},
        )
    )
    assert missing.status is AnalysisStatus.INSUFFICIENT_CONTEXT
    assert provider.calls == 0
    completed = asyncio.run(
        service.analyze_context(
            mode=AnalysisMode.HISTORICAL_COMPARISON,
            created_at=NOW,
            source_record_ids=("trade-1",),
            raw_context={"instrument": "EUR/USD"},
            historical_records=(historical(),),
        )
    )
    assert completed.status is AnalysisStatus.COMPLETED


def test_disabled_analysis_never_invokes_provider() -> None:
    provider = DeterministicFakeProvider()
    result = asyncio.run(
        AIAnalyst(provider=provider).analyze_context(
            mode=AnalysisMode.SIGNAL_EXPLANATION,
            created_at=NOW,
            source_record_ids=("signal-1",),
            raw_context={"password": "would be unsafe"},
        )
    )
    assert result.status is AnalysisStatus.DISABLED
    assert result.reason_codes == (SanitizationReasonCode.PROVIDER_DISABLED,)
    assert provider.calls == 0


def test_sanitization_failure_prevents_provider_call() -> None:
    service, provider = analyst()
    result = asyncio.run(
        service.analyze_context(
            mode=AnalysisMode.SIGNAL_EXPLANATION,
            created_at=NOW,
            source_record_ids=("signal-1",),
            raw_context={"access_token": "redacted"},
        )
    )
    assert result.status is AnalysisStatus.SANITIZATION_FAILED
    assert provider.calls == 0


def test_direct_request_cannot_bypass_sanitization_or_required_context() -> None:
    configuration = enabled_configuration()
    provider = DeterministicFakeProvider()
    service = AIAnalyst(configuration, provider)
    request = build_request(
        mode=AnalysisMode.SIGNAL_EXPLANATION,
        created_at=NOW,
        source_record_ids=("signal-1",),
        context=sanitize_context({"signal_action": "NO_TRADE"}, configuration),
        historical_examples=(),
        explicit_questions=(),
        configuration=configuration,
    )
    unsafe = request.model_copy(
        update={"explicit_questions": ("Please approve trade and place order",)}
    )
    fields = unsafe.model_dump(mode="python", exclude={"request_id", "request_fingerprint"})
    unsafe_fingerprint = fingerprint(fields)
    unsafe = unsafe.model_copy(
        update={
            "request_id": unsafe_fingerprint,
            "request_fingerprint": unsafe_fingerprint,
        }
    )
    rejected = asyncio.run(service.analyze(unsafe))
    assert rejected.status is AnalysisStatus.SANITIZATION_FAILED
    assert provider.calls == 0

    empty = build_request(
        mode=AnalysisMode.SIGNAL_EXPLANATION,
        created_at=NOW,
        source_record_ids=("signal-2",),
        context=sanitize_context({}, configuration),
        historical_examples=(),
        explicit_questions=(),
        configuration=configuration,
    )
    insufficient = asyncio.run(service.analyze(empty))
    assert insufficient.status is AnalysisStatus.INSUFFICIENT_CONTEXT
    assert provider.calls == 0


def test_provider_error_and_malformed_response_are_isolated() -> None:
    configuration = enabled_configuration()
    failed_provider = DeterministicFakeProvider(failure=RuntimeError("provider refused"))
    failed = asyncio.run(
        AIAnalyst(configuration, failed_provider).analyze_context(
            mode=AnalysisMode.SIGNAL_EXPLANATION,
            created_at=NOW,
            source_record_ids=("signal-1",),
            raw_context=context_for(AnalysisMode.SIGNAL_EXPLANATION),
        )
    )
    assert failed.status is AnalysisStatus.PROVIDER_ERROR
    malformed_provider = DeterministicFakeProvider(malformed={"summary": "bad"})
    malformed = asyncio.run(
        AIAnalyst(configuration, malformed_provider).analyze_context(
            mode=AnalysisMode.SIGNAL_EXPLANATION,
            created_at=NOW,
            source_record_ids=("signal-1",),
            raw_context=context_for(AnalysisMode.SIGNAL_EXPLANATION),
        )
    )
    assert malformed.status is AnalysisStatus.INVALID_RESPONSE


class SlowProvider(DeterministicFakeProvider):
    async def analyze(self, request):  # type: ignore[no-untyped-def]
        await asyncio.sleep(1)
        return await super().analyze(request)


def test_provider_timeout_is_isolated() -> None:
    configuration = enabled_configuration(timeout_seconds="0.01")
    result = asyncio.run(
        AIAnalyst(configuration, SlowProvider()).analyze_context(
            mode=AnalysisMode.SIGNAL_EXPLANATION,
            created_at=NOW,
            source_record_ids=("signal-1",),
            raw_context=context_for(AnalysisMode.SIGNAL_EXPLANATION),
        )
    )
    assert result.status is AnalysisStatus.TIMEOUT


class NetworkProvider(DeterministicFakeProvider):
    network_access = True


def test_network_provider_is_blocked_before_invocation() -> None:
    provider = NetworkProvider()
    result = asyncio.run(
        AIAnalyst(enabled_configuration(), provider).analyze_context(
            mode=AnalysisMode.SIGNAL_EXPLANATION,
            created_at=NOW,
            source_record_ids=("signal-1",),
            raw_context=context_for(AnalysisMode.SIGNAL_EXPLANATION),
        )
    )
    assert result.status is AnalysisStatus.REJECTED_BY_POLICY
    assert provider.calls == 0


def test_provider_failure_does_not_mutate_source_context() -> None:
    context = context_for(AnalysisMode.TRADE_REVIEW)
    before = deepcopy(context)
    provider = DeterministicFakeProvider(failure=RuntimeError("failure"))
    result = asyncio.run(
        AIAnalyst(enabled_configuration(), provider).analyze_context(
            mode=AnalysisMode.TRADE_REVIEW,
            created_at=NOW,
            source_record_ids=("trade-1",),
            raw_context=context,
        )
    )
    assert result.status is AnalysisStatus.PROVIDER_ERROR
    assert context == before


def test_repeated_identical_analysis_is_idempotent_in_append_only_journal() -> None:
    service, _ = analyst()
    kwargs = {
        "mode": AnalysisMode.SIGNAL_EXPLANATION,
        "created_at": NOW,
        "source_record_ids": ("signal-1",),
        "raw_context": context_for(AnalysisMode.SIGNAL_EXPLANATION),
    }
    first = asyncio.run(service.analyze_context(**kwargs))  # type: ignore[arg-type]
    second = asyncio.run(service.analyze_context(**kwargs))  # type: ignore[arg-type]
    assert first.record == second.record
    assert len(service.journal.records()) == 1
