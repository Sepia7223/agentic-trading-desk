"""Read-only position lifecycle monitoring source."""

from typing import Protocol

from trading_desk.ig.models import OpenPosition


class PositionMonitorPort(Protocol):
    async def get_open_positions(self) -> tuple[OpenPosition, ...]: ...
