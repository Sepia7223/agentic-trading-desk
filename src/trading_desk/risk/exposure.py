"""Projected exposure calculations for a proposed long position."""

from __future__ import annotations

from decimal import Decimal


def notional_capacity(limit_fraction: Decimal, equity: Decimal, current: Decimal) -> Decimal:
    return max(limit_fraction * equity - current, Decimal("0"))


def quantity_capacity(notional_headroom: Decimal, per_unit_notional: Decimal) -> Decimal:
    if per_unit_notional <= 0:
        raise ValueError("per-unit notional must be positive")
    return max(notional_headroom, Decimal("0")) / per_unit_notional


def projected_exposure(current: Decimal, trade_notional: Decimal) -> Decimal:
    return current + trade_notional
