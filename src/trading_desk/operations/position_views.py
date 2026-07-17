"""Current Paper and reconciled IG Demo position projections."""

from datetime import datetime
from decimal import Decimal, InvalidOperation

from trading_desk.journal.models import JournalRecordType
from trading_desk.operations.fingerprints import fingerprint
from trading_desk.operations.models import (
    ExecutionLifecycleProjection,
    OpenPositionProjection,
    OpenPositionsProjection,
    RecordProjection,
)


def build_open_positions(
    records: tuple[RecordProjection, ...],
    lifecycles: tuple[ExecutionLifecycleProjection, ...],
    generated_at: datetime,
) -> OpenPositionsProjection:
    paper, paper_source = _paper_positions(records, generated_at)
    demo = tuple(_demo_position(item, generated_at) for item in lifecycles if _is_reconciled(item))
    fields: dict[str, object] = {
        "generated_at": generated_at,
        "paper": paper,
        "demo": demo,
        "paper_source": paper_source,
        "demo_source": "LATEST_RECONCILED_DEMO_EXECUTION",
    }
    return OpenPositionsProjection(
        generated_at=generated_at,
        paper=paper,
        demo=demo,
        paper_source=paper_source,
        demo_source="LATEST_RECONCILED_DEMO_EXECUTION",
        projection_fingerprint=fingerprint(fields),
    )


def _paper_positions(
    records: tuple[RecordProjection, ...], generated_at: datetime
) -> tuple[tuple[OpenPositionProjection, ...], str]:
    for record in reversed(records):
        if record.record_type != JournalRecordType.PAPER_PORTFOLIO_EVENT.value:
            continue
        positions = _position_list(record.payload)
        if positions is not None:
            open_positions = tuple(
                _paper_state_position(item, record, generated_at)
                for item in positions
                if str(item.get("status", "OPEN")) == "OPEN"
            )
            return open_positions, "LATEST_PORTFOLIO_STATE"
    closed_ids = {
        str(item.payload.get("position_id"))
        for item in records
        if item.record_type
        in {
            JournalRecordType.PAPER_CLOSED_TRADE.value,
            JournalRecordType.PAPER_UNRESOLVED_POSITION.value,
        }
        and item.payload.get("position_id") is not None
    }
    entries: dict[str, RecordProjection] = {}
    for record in records:
        if record.record_type != JournalRecordType.PAPER_FILL.value:
            continue
        if str(record.payload.get("side", "ENTRY")) != "ENTRY":
            continue
        position_id = str(record.payload.get("position_id") or record.source_record_id)
        if position_id not in closed_ids:
            entries[position_id] = record
    return (
        tuple(_paper_fill_position(key, value, generated_at) for key, value in entries.items()),
        "ENTRY_FILL_MINUS_CLOSED_AND_UNRESOLVED",
    )


def _position_list(payload: dict[str, object]) -> tuple[dict[str, object], ...] | None:
    candidates = payload.get("positions")
    if not isinstance(candidates, (list, tuple)):
        state = payload.get("state")
        candidates = state.get("positions") if isinstance(state, dict) else None
    if not isinstance(candidates, (list, tuple)):
        return None
    return tuple(item for item in candidates if isinstance(item, dict))


def _paper_state_position(
    payload: dict[str, object], record: RecordProjection, now: datetime
) -> OpenPositionProjection:
    position_id = str(payload.get("position_id") or record.source_record_id)
    fields = _position_fields(
        position_id=position_id,
        environment="PAPER",
        evidence_status="CURRENT_PORTFOLIO_STATE",
        payload=payload,
        record=record,
        now=now,
        source_record_ids=(record.source_record_id,),
    )
    return OpenPositionProjection.model_validate(
        {**fields, "projection_fingerprint": fingerprint(fields)}
    )


def _paper_fill_position(
    position_id: str, record: RecordProjection, now: datetime
) -> OpenPositionProjection:
    fields = _position_fields(
        position_id=position_id,
        environment="PAPER",
        evidence_status="OPEN_FROM_ENTRY_EVIDENCE",
        payload=record.payload,
        record=record,
        now=now,
        source_record_ids=(record.source_record_id,),
    )
    return OpenPositionProjection.model_validate(
        {**fields, "projection_fingerprint": fingerprint(fields)}
    )


def _position_fields(
    *,
    position_id: str,
    environment: str,
    evidence_status: str,
    payload: dict[str, object],
    record: RecordProjection,
    now: datetime,
    source_record_ids: tuple[str, ...],
) -> dict[str, object]:
    entry_at = _datetime(payload.get("entry_timestamp")) or record.effective_at
    return {
        "position_id": position_id,
        "environment": environment,
        "evidence_status": evidence_status,
        "instrument": str(payload.get("instrument") or record.instrument or "") or None,
        "epic": str(payload.get("epic") or record.epic or "") or None,
        "direction": _text(payload.get("direction")),
        "quantity": _decimal(payload.get("quantity")),
        "entry_timestamp": entry_at,
        "entry_price": _decimal(payload.get("entry_price") or payload.get("fill_price")),
        "current_mark": _decimal(payload.get("current_mark_price")),
        "stop_price": _decimal(payload.get("stop_price") or payload.get("stop_level")),
        "target_price": _decimal(payload.get("target_price") or payload.get("target_level")),
        "unrealized_pnl": _decimal(
            payload.get("net_unrealized_pnl") or payload.get("unrealized_pnl")
        ),
        "realized_costs": _sum_values(
            payload, "entry_commission", "entry_slippage_cost", "realized_costs"
        ),
        "funding": _decimal(payload.get("accrued_funding") or payload.get("funding")),
        "exposure": _decimal(payload.get("current_exposure") or payload.get("exposure")),
        "open_risk": _decimal(payload.get("open_risk_amount") or payload.get("open_risk")),
        "duration_seconds": max(0, int((now - entry_at).total_seconds())),
        "source_strategy": record.strategy_variant,
        "risk_decision_id": _text(payload.get("risk_decision_id")),
        "execution_id": None,
        "reconciliation_status": None,
        "source_record_ids": source_record_ids,
    }


def _demo_position(
    lifecycle: ExecutionLifecycleProjection, now: datetime
) -> OpenPositionProjection:
    entry_stage = next(
        (item for item in lifecycle.stages if item.stage == "BROKER CONFIRMATION"),
        lifecycle.stages[-1],
    )
    fields: dict[str, object] = {
        "position_id": lifecycle.execution_request_id,
        "environment": "IG DEMO",
        "evidence_status": "LATEST_RECONCILED_DEMO_STATE",
        "instrument": lifecycle.instrument,
        "epic": lifecycle.epic,
        "direction": lifecycle.direction,
        "quantity": lifecycle.confirmed_size or lifecycle.submitted_quantity,
        "entry_timestamp": entry_stage.timestamp,
        "entry_price": lifecycle.confirmed_entry,
        "current_mark": None,
        "stop_price": lifecycle.stop_price,
        "target_price": lifecycle.target_price,
        "unrealized_pnl": None,
        "realized_costs": None,
        "funding": None,
        "exposure": None,
        "open_risk": None,
        "duration_seconds": max(0, int((now - entry_stage.timestamp).total_seconds())),
        "source_strategy": None,
        "risk_decision_id": None,
        "execution_id": lifecycle.execution_request_id,
        "reconciliation_status": lifecycle.reconciliation_status,
        "source_record_ids": lifecycle.source_record_ids,
    }
    return OpenPositionProjection.model_validate(
        {**fields, "projection_fingerprint": fingerprint(fields)}
    )


def _is_reconciled(lifecycle: ExecutionLifecycleProjection) -> bool:
    return lifecycle.reconciliation_status.upper() in {"RECONCILED", "MATCHED"}


def _decimal(value: object | None) -> Decimal | None:
    try:
        return None if value is None else Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _sum_values(payload: dict[str, object], *keys: str) -> Decimal | None:
    values = tuple(_decimal(payload.get(key)) for key in keys)
    present = tuple(item for item in values if item is not None)
    return sum(present, Decimal("0")) if present else None


def _datetime(value: object | None) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _text(value: object | None) -> str | None:
    return None if value is None else str(value)
