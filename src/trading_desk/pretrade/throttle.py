"""Runaway protection: order rate limits + restart-surviving idempotency.

Pre-trade controls against the rapid accumulation of orders from mistakes or
malfunctions (the CFTC automated-trading concern): a sliding-window rate limit,
an open-order cap, and a daily cap — plus deterministic idempotency keys so a
duplicate order is detected even across process restarts (the registry is
serialisable and must be persisted by the caller).

Pure logic with injected clocks; no wall-clock reads, so fully testable.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from trading_desk.pretrade.models import OrderSpec, Rejection, RejectionCode, SignalState


class ThrottleLimits(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    max_orders_per_minute: int = Field(default=10, gt=0)
    max_open_orders: int = Field(default=20, gt=0)
    max_orders_per_day: int = Field(default=60, gt=0)


def idempotency_key(signal: SignalState, order: OrderSpec) -> str:
    """Deterministic key: same strategy decision -> same key, across restarts."""

    seed = "|".join(
        (
            order.strategy_id,
            order.account_id,
            order.symbol,
            order.direction,
            str(Decimal(order.quantity)),
            signal.signal_type,
            signal.rebalance_date.date().isoformat(),
            str(Decimal(signal.target_weight)),
        )
    )
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32]


class OrderThrottle:
    """Sliding-window rate limiting + duplicate detection.

    ``seen_keys`` should be loaded from persistence at startup and saved after
    every accepted order so duplicate detection survives restarts.
    """

    def __init__(
        self,
        limits: ThrottleLimits | None = None,
        seen_keys: set[str] | None = None,
    ) -> None:
        self.limits = limits or ThrottleLimits()
        self.seen_keys: set[str] = set(seen_keys or ())
        self._recent: list[datetime] = []
        self._today: tuple[str, int] = ("", 0)
        self.open_orders: int = 0

    def admit(self, key: str, now: datetime) -> tuple[bool, list[Rejection]]:
        """Check an order for admission; on success, record it."""

        rejections: list[Rejection] = []
        if key in self.seen_keys:
            rejections.append(
                Rejection(
                    code=RejectionCode.ORDER_VALIDATION_FAILED,
                    detail=f"duplicate idempotency key {key[:12]}…",
                )
            )
        self._recent = [t for t in self._recent if (now - t).total_seconds() < 60.0]
        if len(self._recent) >= self.limits.max_orders_per_minute:
            rejections.append(
                Rejection(
                    code=RejectionCode.RATE_LIMITED,
                    detail=(
                        f"{len(self._recent)} orders in the last minute >= "
                        f"{self.limits.max_orders_per_minute}"
                    ),
                )
            )
        if self.open_orders >= self.limits.max_open_orders:
            rejections.append(
                Rejection(
                    code=RejectionCode.RATE_LIMITED,
                    detail=f"open orders {self.open_orders} >= {self.limits.max_open_orders}",
                )
            )
        day = now.date().isoformat()
        day_key, day_count = self._today
        if day_key != day:
            day_count = 0
        if day_count >= self.limits.max_orders_per_day:
            rejections.append(
                Rejection(
                    code=RejectionCode.RATE_LIMITED,
                    detail=f"daily order count {day_count} >= {self.limits.max_orders_per_day}",
                )
            )
        if rejections:
            return False, rejections
        self.seen_keys.add(key)
        self._recent.append(now)
        self._today = (day, day_count + 1)
        self.open_orders += 1
        return True, []

    def order_closed(self) -> None:
        self.open_orders = max(0, self.open_orders - 1)
