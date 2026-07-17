"""Sanitized server-to-client Operations Center WebSocket stream."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import WebSocket, WebSocketDisconnect

from trading_desk.operations.events import OperationsEventBus
from trading_desk.operations.fingerprints import fingerprint
from trading_desk.operations.models import OperationsEvent, OperationsEventType
from trading_desk.operations.service import OperationsService


async def stream_events(
    websocket: WebSocket, bus: OperationsEventBus, service: OperationsService
) -> None:
    await websocket.accept()
    now = datetime.now(UTC)
    payload = service.snapshot(now).model_dump(mode="json")
    fields = {
        "event_type": OperationsEventType.SYSTEM_HEALTH_UPDATED,
        "created_at": now,
        "source_record_ids": (),
        "payload": payload,
    }
    identity = fingerprint(fields)
    initial = OperationsEvent.model_validate(
        {**fields, "event_id": identity, "event_fingerprint": identity}
    )
    await websocket.send_json(initial.model_dump(mode="json"))
    try:
        async for event in bus.subscribe():
            await websocket.send_json(event.model_dump(mode="json"))
    except (WebSocketDisconnect, RuntimeError):
        await websocket.close()
