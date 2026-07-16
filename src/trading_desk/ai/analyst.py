"""Failure-isolated orchestration for structured advisory analysis."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from datetime import datetime

from trading_desk.ai.config import AIAnalystConfiguration
from trading_desk.ai.errors import AIPolicyViolation
from trading_desk.ai.fingerprints import canonical_json, fingerprint
from trading_desk.ai.journal import AIAnalysisJournal, InMemoryAIAnalysisJournal
from trading_desk.ai.models import (
    AIAnalysisRecord,
    AIAnalysisRequest,
    AIAnalysisResult,
    AnalysisMode,
    AnalysisStatus,
    HistoricalExample,
    SanitizationReasonCode,
    SanitizedContext,
)
from trading_desk.ai.policy import validate_response
from trading_desk.ai.prompts import build_prompt
from trading_desk.ai.provider import AIAnalysisProvider
from trading_desk.ai.reports import summarize_historical_evidence
from trading_desk.ai.sanitization import (
    SanitizationFailure,
    build_request,
    sanitize_context,
    sanitize_historical_examples,
)


class AIAnalyst:
    def __init__(
        self,
        configuration: AIAnalystConfiguration | None = None,
        provider: AIAnalysisProvider | None = None,
        journal: AIAnalysisJournal | None = None,
    ) -> None:
        self.configuration = configuration or AIAnalystConfiguration()
        self.provider = provider
        self.journal = journal or InMemoryAIAnalysisJournal()

    async def analyze_context(
        self,
        *,
        mode: AnalysisMode,
        created_at: datetime,
        source_record_ids: tuple[str, ...],
        raw_context: Mapping[str, object],
        historical_records: Sequence[Mapping[str, object] | HistoricalExample] = (),
        explicit_questions: tuple[str, ...] = (),
        strategy_configuration_fingerprint: str | None = None,
        risk_configuration_fingerprint: str | None = None,
        portfolio_configuration_fingerprint: str | None = None,
        journal_snapshot_id: str | None = None,
    ) -> AIAnalysisResult:
        if not self.configuration.analysis_enabled:
            return AIAnalysisResult(
                status=AnalysisStatus.DISABLED,
                reason_codes=(SanitizationReasonCode.PROVIDER_DISABLED,),
                safe_message="AI analysis is disabled; deterministic workflows continue unchanged.",
            )
        if self.provider is None:
            return AIAnalysisResult(
                status=AnalysisStatus.PROVIDER_ERROR,
                safe_message="No advisory provider is configured.",
            )
        if self.provider.network_access and not self.configuration.allow_network_provider:
            return AIAnalysisResult(
                status=AnalysisStatus.REJECTED_BY_POLICY,
                reason_codes=(SanitizationReasonCode.NETWORK_PROVIDER_DISABLED,),
                safe_message="Network provider access is disabled by policy.",
            )
        try:
            context = sanitize_context(raw_context, self.configuration)
            history = sanitize_historical_examples(
                historical_records,
                self.configuration,
                evaluation_timestamp=created_at,
            )
            if history:
                summary = summarize_historical_evidence(history, (f"mode={mode.value}",))
                context = context.model_copy(update={"historical_summary": canonical_json(summary)})
            if not _has_required_context(mode, context, history):
                return AIAnalysisResult(
                    status=AnalysisStatus.INSUFFICIENT_CONTEXT,
                    reason_codes=(SanitizationReasonCode.MISSING_REQUIRED_CONTEXT,),
                    safe_message="Required sanitized context is unavailable.",
                )
            request = build_request(
                mode=mode,
                created_at=created_at,
                source_record_ids=source_record_ids,
                context=context,
                historical_examples=history,
                explicit_questions=explicit_questions,
                configuration=self.configuration,
                strategy_configuration_fingerprint=strategy_configuration_fingerprint,
                risk_configuration_fingerprint=risk_configuration_fingerprint,
                portfolio_configuration_fingerprint=portfolio_configuration_fingerprint,
                journal_snapshot_id=journal_snapshot_id,
            )
        except SanitizationFailure as error:
            return AIAnalysisResult(
                status=AnalysisStatus.SANITIZATION_FAILED,
                reason_codes=(error.code,),
                safe_message=str(error),
            )
        return await self.analyze(request)

    async def analyze(self, request: AIAnalysisRequest) -> AIAnalysisResult:
        if not self.configuration.analysis_enabled:
            return AIAnalysisResult(
                status=AnalysisStatus.DISABLED,
                request_id=request.request_id,
                reason_codes=(SanitizationReasonCode.PROVIDER_DISABLED,),
                safe_message="AI analysis is disabled; deterministic workflows continue unchanged.",
            )
        if self.provider is None:
            return AIAnalysisResult(
                status=AnalysisStatus.PROVIDER_ERROR,
                request_id=request.request_id,
                safe_message="No advisory provider is configured.",
            )
        if self.provider.network_access and not self.configuration.allow_network_provider:
            return AIAnalysisResult(
                status=AnalysisStatus.REJECTED_BY_POLICY,
                request_id=request.request_id,
                reason_codes=(SanitizationReasonCode.NETWORK_PROVIDER_DISABLED,),
                safe_message="Network provider access is disabled by policy.",
            )
        try:
            context = sanitize_context(
                request.sanitized_context.model_dump(mode="python"), self.configuration
            )
            history = sanitize_historical_examples(
                request.historical_examples,
                self.configuration,
                evaluation_timestamp=request.created_at,
            )
            rebuilt = build_request(
                mode=request.mode,
                created_at=request.created_at,
                source_record_ids=request.source_record_ids,
                context=context,
                historical_examples=history,
                explicit_questions=request.explicit_questions,
                configuration=self.configuration,
                strategy_configuration_fingerprint=(request.strategy_configuration_fingerprint),
                risk_configuration_fingerprint=request.risk_configuration_fingerprint,
                portfolio_configuration_fingerprint=(request.portfolio_configuration_fingerprint),
                journal_snapshot_id=request.journal_snapshot_id,
            )
        except SanitizationFailure as error:
            return AIAnalysisResult(
                status=AnalysisStatus.SANITIZATION_FAILED,
                request_id=request.request_id,
                reason_codes=(error.code,),
                safe_message=str(error),
            )
        if rebuilt != request or not _request_fingerprint_valid(request):
            return AIAnalysisResult(
                status=AnalysisStatus.REJECTED_BY_POLICY,
                request_id=request.request_id,
                safe_message="AI request fingerprint is invalid.",
            )
        if not _has_required_context(request.mode, context, history):
            return AIAnalysisResult(
                status=AnalysisStatus.INSUFFICIENT_CONTEXT,
                request_id=request.request_id,
                reason_codes=(SanitizationReasonCode.MISSING_REQUIRED_CONTEXT,),
                safe_message="Required sanitized context is unavailable.",
            )
        if (
            request.configuration_fingerprint != self.configuration.fingerprint
            or len(request.historical_examples) > self.configuration.maximum_records_per_request
            or len(canonical_json(request)) > self.configuration.maximum_input_characters
        ):
            return AIAnalysisResult(
                status=AnalysisStatus.REJECTED_BY_POLICY,
                request_id=request.request_id,
                safe_message="AI request violates configured policy limits.",
            )
        build_prompt(request)
        raw: object | None = None
        for attempt in range(self.configuration.maximum_retries + 1):
            try:
                raw = await asyncio.wait_for(
                    self.provider.analyze(request),
                    timeout=float(self.configuration.timeout_seconds),
                )
                break
            except TimeoutError:
                if attempt == self.configuration.maximum_retries:
                    return AIAnalysisResult(
                        status=AnalysisStatus.TIMEOUT,
                        request_id=request.request_id,
                        safe_message=(
                            "Advisory provider timed out; deterministic workflows are unaffected."
                        ),
                    )
            except Exception:
                if attempt == self.configuration.maximum_retries:
                    return AIAnalysisResult(
                        status=AnalysisStatus.PROVIDER_ERROR,
                        request_id=request.request_id,
                        safe_message=(
                            "Advisory provider failed; deterministic workflows are unaffected."
                        ),
                    )
        try:
            response = validate_response(raw, request, self.configuration)
        except AIPolicyViolation as error:
            return AIAnalysisResult(
                status=AnalysisStatus.INVALID_RESPONSE,
                request_id=request.request_id,
                safe_message=str(error),
            )
        record_fields = {
            "request_id": request.request_id,
            "mode": request.mode,
            "created_at": response.created_at,
            "source_record_ids": response.source_record_ids,
            "sanitized_input_fingerprint": fingerprint(request.sanitized_context),
            "provider_name": response.provider_name,
            "model_name": response.model_name,
            "structured_response": response,
            "policy_version": request.policy_version,
            "configuration_fingerprint": self.configuration.fingerprint,
        }
        analysis_fingerprint = fingerprint(record_fields)
        record = AIAnalysisRecord.model_validate(
            {
                **record_fields,
                "analysis_id": analysis_fingerprint,
                "analysis_fingerprint": analysis_fingerprint,
            }
        )
        self.journal.append(record)
        return AIAnalysisResult(
            status=AnalysisStatus.COMPLETED,
            request_id=request.request_id,
            response=response,
            record=record,
            safe_message="Advisory analysis completed for human review.",
        )


def _request_fingerprint_valid(request: AIAnalysisRequest) -> bool:
    fields = request.model_dump(mode="python", exclude={"request_id", "request_fingerprint"})
    return request.request_id == request.request_fingerprint == fingerprint(fields)


def _has_required_context(
    mode: AnalysisMode,
    context: SanitizedContext,
    history: Sequence[HistoricalExample],
) -> bool:
    if mode is AnalysisMode.SIGNAL_EXPLANATION:
        return context.signal_action is not None
    if mode is AnalysisMode.RISK_DECISION_EXPLANATION:
        return context.risk_status is not None
    if mode is AnalysisMode.TRADE_REVIEW:
        return context.net_pnl is not None
    if mode in {
        AnalysisMode.DAILY_REVIEW,
        AnalysisMode.WEEKLY_REVIEW,
        AnalysisMode.MONTHLY_REVIEW,
        AnalysisMode.PORTFOLIO_SUMMARY,
    }:
        return context.portfolio_equity is not None
    if mode is AnalysisMode.HISTORICAL_COMPARISON:
        return bool(history)
    return (
        context.historical_summary is not None
        or context.review_metrics is not None
        or context.regime is not None
        or context.risk_status is not None
    )
