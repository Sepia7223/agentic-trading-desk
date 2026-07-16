"""Compatibility exports for the strict advisory AI provider boundary."""

from trading_desk.ai.models import AIAnalysisRequest, AIAnalysisResult
from trading_desk.ai.provider import AIAnalysisProvider

__all__ = ["AIAnalysisProvider", "AIAnalysisRequest", "AIAnalysisResult"]
