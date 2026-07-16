"""Small deterministic helpers shared by ordered risk gates."""

from __future__ import annotations

from decimal import Decimal
from typing import TypeGuard

from trading_desk.risk.models import GateResult, RiskGate, RiskReasonCode


def is_finite(value: Decimal | None) -> TypeGuard[Decimal]:
    return value is not None and value.is_finite()


def is_non_negative(value: Decimal | None) -> TypeGuard[Decimal]:
    return value is not None and value.is_finite() and value >= 0


def is_positive(value: Decimal | None) -> TypeGuard[Decimal]:
    return value is not None and value.is_finite() and value > 0


def is_sha256(value: str) -> bool:
    return len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def gate_result(gate: RiskGate, *reasons: RiskReasonCode) -> GateResult:
    unique = tuple(dict.fromkeys(reasons))
    return GateResult(gate=gate, passed=not unique, reason_codes=unique)
