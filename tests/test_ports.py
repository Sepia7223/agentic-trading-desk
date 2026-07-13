from __future__ import annotations

import inspect

import trading_desk.ports as ports
from trading_desk.ports.broker import Broker


def test_read_only_broker_protocol_has_no_order_surface() -> None:
    protocol_methods = {
        name
        for name, member in inspect.getmembers(Broker, predicate=inspect.isfunction)
        if not name.startswith("_")
    }

    assert protocol_methods == {"get_portfolio_state"}
    assert all("order" not in name.lower() for name in dir(Broker))
    assert not hasattr(ports, "OrderPreview")
