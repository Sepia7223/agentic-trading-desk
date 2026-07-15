"""AI analysis provider protocol.

Runtime model providers must receive sanitized strategy outputs and qualitative
context only. Broker credentials and order authority stay outside this port.
"""

from __future__ import annotations

from typing import Protocol, TypedDict


class AIAnalysisRequest(TypedDict):
    symbol: str
    deterministic_scorecard: dict[str, object]
    qualitative_context: dict[str, object]
    risk_limits: dict[str, object]


class AIAnalysisResult(TypedDict):
    summary: str
    observations: list[str]
    risk_notes: list[str]


class AIAnalysisProvider(Protocol):
    """Sanitized language-model analysis boundary."""

    async def analyze(self, request: AIAnalysisRequest) -> AIAnalysisResult:
        """Analyze without order authority or broker secrets."""
