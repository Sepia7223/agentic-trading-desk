"""Append-only storage boundary for structured AI analysis records."""

from __future__ import annotations

from typing import Protocol

from trading_desk.ai.models import AIAnalysisRecord


class AIAnalysisJournal(Protocol):
    def append(self, record: AIAnalysisRecord) -> None: ...

    def records(self) -> tuple[AIAnalysisRecord, ...]: ...


class InMemoryAIAnalysisJournal:
    def __init__(self) -> None:
        self._records: tuple[AIAnalysisRecord, ...] = ()

    def append(self, record: AIAnalysisRecord) -> None:
        existing = next(
            (item for item in self._records if item.analysis_id == record.analysis_id), None
        )
        if existing is not None:
            if existing != record:
                raise ValueError("AI analysis ID conflicts with existing immutable record")
            return
        self._records += (record,)

    def records(self) -> tuple[AIAnalysisRecord, ...]:
        return self._records
