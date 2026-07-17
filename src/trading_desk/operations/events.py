"""Bounded process-local event stream; never a command bus."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from trading_desk.operations.config import OperationsConfiguration
from trading_desk.operations.models import OperationsEvent


class OperationsEventBus:
    def __init__(self, configuration: OperationsConfiguration) -> None:
        self.configuration = configuration
        self._subscribers: set[asyncio.Queue[OperationsEvent]] = set()

    @property
    def client_count(self) -> int:
        return len(self._subscribers)

    def publish(self, event: OperationsEvent) -> None:
        for queue in tuple(self._subscribers):
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(event)

    async def subscribe(self) -> AsyncIterator[OperationsEvent]:
        if len(self._subscribers) >= self.configuration.maximum_websocket_clients:
            raise RuntimeError("maximum WebSocket clients reached")
        queue: asyncio.Queue[OperationsEvent] = asyncio.Queue(maxsize=100)
        self._subscribers.add(queue)
        try:
            while True:
                yield await queue.get()
        finally:
            self._subscribers.discard(queue)
