"""Dedicated broker-mutation port owned only by the execution subsystem."""

from typing import Protocol

from trading_desk.execution.models import (
    BrokerConfirmation,
    BrokerOrderRequest,
    BrokerSubmission,
)
from trading_desk.ig.models import OpenPosition


class BrokerExecutionPort(Protocol):
    async def submit_market_position(self, request: BrokerOrderRequest) -> BrokerSubmission: ...

    async def get_deal_confirmation(self, deal_reference: str) -> BrokerConfirmation: ...

    async def get_open_positions(self) -> tuple[OpenPosition, ...]: ...
