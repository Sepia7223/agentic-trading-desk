"""Restart-safe Demo trade counts and deterministic campaign report inputs."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

from trading_desk.opportunity.fingerprints import fingerprint


class DemoTradeStatus(StrEnum):
    SUBMITTED = "SUBMITTED"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    CLOSED = "CLOSED"


class DemoTradeRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)
    trading_date: date
    boundary_policy: str = "UTC"
    occurred_at: datetime
    status: DemoTradeStatus
    strategy: str
    instrument: str
    timeframe: str
    regime: str
    session: str
    candidate_id: str
    execution_id: str | None = None
    realized_pnl: Decimal | None = None
    estimated_cost: Decimal = Field(default=Decimal("0"), ge=0)
    observed_cost: Decimal = Field(default=Decimal("0"), ge=0)
    holding_period_seconds: Decimal | None = Field(default=None, ge=0)
    record_id: str = Field(min_length=64, max_length=64)

    @field_validator("occurred_at")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("trade ledger timestamp must be UTC")
        return value.astimezone(UTC)


class DemoTradeLedgerState(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    records: tuple[DemoTradeRecord, ...] = ()
    state_fingerprint: str = Field(min_length=64, max_length=64)


class DemoTradeLedger:
    """Daily limit counts submitted orders, including ambiguous submissions."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> DemoTradeLedgerState:
        if not self.path.is_file():
            return self._state(())
        try:
            state = DemoTradeLedgerState.model_validate_json(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise ValueError("persisted Demo trade ledger is invalid") from None
        if state.state_fingerprint != fingerprint({"records": state.records}):
            raise ValueError("persisted Demo trade ledger fingerprint mismatch")
        return state

    def append(self, record: DemoTradeRecord) -> DemoTradeLedgerState:
        state = self.load()
        if any(item.record_id == record.record_id for item in state.records):
            return state
        updated = self._state((*state.records, record))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(updated.model_dump_json(indent=2), encoding="utf-8")
        temporary.replace(self.path)
        return updated

    def submitted_on(self, trading_date: date) -> int:
        return sum(
            1
            for item in self.load().records
            if item.trading_date == trading_date and item.status is DemoTradeStatus.SUBMITTED
        )

    @staticmethod
    def create_record(**values: object) -> DemoTradeRecord:
        fields = dict(values)
        occurred_at = fields["occurred_at"]
        assert isinstance(occurred_at, datetime)
        fields.setdefault("trading_date", occurred_at.astimezone(UTC).date())
        fields.setdefault("boundary_policy", "UTC")
        return DemoTradeRecord.model_validate({**fields, "record_id": fingerprint(fields)})

    @staticmethod
    def _state(records: tuple[DemoTradeRecord, ...]) -> DemoTradeLedgerState:
        fields = {"records": records}
        return DemoTradeLedgerState(
            records=records,
            state_fingerprint=fingerprint(fields),
        )
