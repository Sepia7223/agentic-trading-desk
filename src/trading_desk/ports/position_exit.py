"""Dedicated close-position mutation port owned only by the lifecycle engine."""

from typing import Protocol

from trading_desk.ig.models import OpenPosition
from trading_desk.lifecycle.models import (
    BrokerCloseRequest,
    BrokerCloseSubmission,
    CloseBrokerConfirmation,
)


class PositionExitPort(Protocol):
    async def submit_position_close(self, request: BrokerCloseRequest) -> BrokerCloseSubmission: ...

    async def get_close_confirmation(self, deal_reference: str) -> CloseBrokerConfirmation: ...

    async def get_open_positions(self) -> tuple[OpenPosition, ...]: ...
