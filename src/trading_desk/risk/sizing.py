"""Decimal-only risk sizing and quantity normalization."""

from __future__ import annotations

from decimal import ROUND_FLOOR, Decimal


def risk_budget(account_equity: Decimal, risk_fraction: Decimal) -> Decimal:
    return account_equity * risk_fraction


def risk_per_unit(
    entry_reference: Decimal,
    stop_reference: Decimal,
    value_per_price_unit: Decimal,
) -> Decimal:
    return abs(entry_reference - stop_reference) * value_per_price_unit


def raw_quantity(budget: Decimal, per_unit_risk: Decimal) -> Decimal:
    if per_unit_risk <= 0:
        raise ValueError("risk per unit must be positive")
    return budget / per_unit_risk


def notional_per_unit(entry_reference: Decimal, value_per_price_unit: Decimal) -> Decimal:
    value = abs(entry_reference) * value_per_price_unit
    if value <= 0:
        raise ValueError("notional per unit must be positive")
    return value


def round_quantity_down(quantity: Decimal, increment: Decimal) -> Decimal:
    if not quantity.is_finite() or not increment.is_finite() or increment <= 0:
        raise ValueError("quantity and increment must be finite with positive increment")
    if quantity <= 0:
        return Decimal("0")
    units = (quantity / increment).to_integral_value(rounding=ROUND_FLOOR)
    return units * increment


def compatible_increment(configured: Decimal, market: Decimal) -> Decimal | None:
    """Return an increment satisfying both step grids, or fail closed."""
    if configured <= 0 or market <= 0 or not configured.is_finite() or not market.is_finite():
        return None
    larger, smaller = max(configured, market), min(configured, market)
    ratio = larger / smaller
    if ratio != ratio.to_integral_value():
        return None
    return larger
