"""Append-only chained paper portfolio ledger and deterministic replay."""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime

from trading_desk.portfolio.errors import LedgerValidationError
from trading_desk.portfolio.fingerprints import canonical_json, fingerprint
from trading_desk.portfolio.models import EventType, PortfolioEvent, PortfolioState


def build_event(
    *,
    sequence_number: int,
    event_type: EventType,
    timestamp: datetime,
    portfolio_id: str,
    payload: object,
    previous_event_fingerprint: str | None,
    position_id: str | None = None,
    risk_decision_id: str | None = None,
    candidate_id: str | None = None,
) -> PortfolioEvent:
    payload_json = canonical_json(payload)
    fields = {
        "sequence_number": sequence_number,
        "event_type": event_type,
        "timestamp": timestamp,
        "portfolio_id": portfolio_id,
        "position_id": position_id,
        "risk_decision_id": risk_decision_id,
        "candidate_id": candidate_id,
        "payload": payload_json,
        "previous_event_fingerprint": previous_event_fingerprint,
    }
    event_fingerprint = fingerprint(fields)
    return PortfolioEvent.model_validate(
        {
            **fields,
            "event_id": event_fingerprint,
            "event_fingerprint": event_fingerprint,
        }
    )


def validate_event_chain(events: Iterable[PortfolioEvent]) -> tuple[PortfolioEvent, ...]:
    ordered = tuple(events)
    previous: str | None = None
    expected_sequence = 1
    known_positions: set[str] = set()
    closed_positions: set[str] = set()
    for event in ordered:
        if event.sequence_number != expected_sequence:
            raise LedgerValidationError("ledger sequence is missing, duplicated, or out of order")
        if event.previous_event_fingerprint != previous:
            raise LedgerValidationError("event fingerprint chain is broken")
        fields = event.model_dump(mode="python", exclude={"event_id", "event_fingerprint"})
        expected = fingerprint(fields)
        if event.event_fingerprint != expected or event.event_id != expected:
            raise LedgerValidationError("event fingerprint is invalid")
        position_id = event.position_id
        if event.event_type is EventType.POSITION_OPENED:
            if position_id is None or position_id in known_positions:
                raise LedgerValidationError("position-open event is invalid")
            known_positions.add(position_id)
        elif event.event_type in {
            EventType.POSITION_MARKED,
            EventType.FUNDING_APPLIED,
            EventType.STOP_TRIGGERED,
            EventType.TARGET_TRIGGERED,
            EventType.SCHEDULED_EXIT,
            EventType.POSITION_CLOSED,
            EventType.POSITION_UNRESOLVED,
        }:
            if position_id not in known_positions:
                raise LedgerValidationError("event references an unknown position")
            if position_id in closed_positions:
                raise LedgerValidationError("event references an already closed position")
            if event.event_type in {EventType.POSITION_CLOSED, EventType.POSITION_UNRESOLVED}:
                assert position_id is not None
                closed_positions.add(position_id)
        previous = event.event_fingerprint
        expected_sequence += 1
    return ordered


def replay(events: Iterable[PortfolioEvent]) -> PortfolioState:
    ordered = validate_event_chain(events)
    state: PortfolioState | None = None
    for event in ordered:
        payload = json.loads(event.payload)
        serialized = payload.get("state") if isinstance(payload, dict) else None
        if serialized is not None:
            state = PortfolioState.model_validate(serialized)
    if state is None:
        raise LedgerValidationError("ledger contains no reproducible portfolio state")
    if state.ledger_sequence != ordered[-1].sequence_number:
        raise LedgerValidationError("replayed state does not match final ledger sequence")
    return state


class InMemoryPortfolioRepository:
    """Atomic in-memory storage boundary used by the local paper engine."""

    def __init__(self) -> None:
        self._events: tuple[PortfolioEvent, ...] = ()
        self._state: PortfolioState | None = None

    @property
    def events(self) -> tuple[PortfolioEvent, ...]:
        return self._events

    @property
    def state(self) -> PortfolioState | None:
        return self._state

    def commit(self, events: tuple[PortfolioEvent, ...], state: PortfolioState) -> None:
        combined = self._events + events
        validate_event_chain(combined)
        if combined[-1].sequence_number != state.ledger_sequence:
            raise LedgerValidationError("committed state sequence does not match ledger")
        self._events = combined
        self._state = state
