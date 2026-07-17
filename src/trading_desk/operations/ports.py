"""Read-only monitoring ports; command methods are intentionally absent."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from trading_desk.journal.models import JournalLineage, JournalQuery, JournalQueryResult
from trading_desk.operations.models import RuntimeSubsystemHealth


class OperationsJournalReader(Protocol):
    def query(self, query: JournalQuery) -> JournalQueryResult: ...

    def lineage(self, source_record_id: str) -> JournalLineage: ...


class RuntimeStateReader(Protocol):
    def scheduler_state(self, observed_at: datetime) -> RuntimeSubsystemHealth: ...

    def execution_state(self, observed_at: datetime) -> RuntimeSubsystemHealth: ...

    def broker_state(self, observed_at: datetime) -> RuntimeSubsystemHealth: ...


class JournalHealthReader(Protocol):
    def journal_state(self, observed_at: datetime) -> RuntimeSubsystemHealth: ...
