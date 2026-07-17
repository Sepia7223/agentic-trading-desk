"""Explicit API dependency container."""

from dataclasses import dataclass

from trading_desk.operations.config import OperationsConfiguration
from trading_desk.operations.events import OperationsEventBus
from trading_desk.operations.service import OperationsService


@dataclass(frozen=True)
class OperationsDependencies:
    configuration: OperationsConfiguration
    service: OperationsService
    events: OperationsEventBus
