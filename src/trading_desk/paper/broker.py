"""Simulated broker with protected-order (OTO) choreography.

Execution model (daily cadence, no look-ahead):
  * Orders queued today fill at the NEXT session's open, adjusted adversely by
    half-spread + slippage (buys pay up, sells receive less).
  * Every entry carries a protective stop distance; on fill the stop is armed
    automatically (OTO) at fill_price -/+ stop_distance.
  * Armed stops are evaluated every settlement on the day's high/low,
    ADVERSE-FIRST: if the session gaps through the stop, the exit price is the
    (worse) open, not the stop level — gap risk is charged, never ignored.
  * OCO semantics at daily cadence: strategy exits arrive as next-day orders;
    the session layer skips exits for positions a stop already closed.

DEMO/PAPER ONLY. Deterministic and unit-testable: settlement consumes caller
supplied bars; no network I/O and no wall clock in this module.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


class PaperOrderStatus(StrEnum):
    QUEUED = "QUEUED"
    FILLED = "FILLED"
    REJECTED_NO_QUOTE = "REJECTED_NO_QUOTE"


class PaperOrder(_Model):
    order_id: str
    symbol: str
    direction: str  # BUY | SELL | SELL_SHORT | BUY_TO_COVER
    quantity: Decimal = Field(gt=0)
    stop_distance_fraction: Decimal = Field(ge=0)  # protection; 0 only for exits
    idempotency_key: str = ""


class Fill(_Model):
    order_id: str
    symbol: str
    direction: str
    quantity: Decimal
    price: Decimal
    fill_date: date
    protection_armed: bool
    stop_price: Decimal | None


class Position(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    symbol: str
    quantity: Decimal  # signed: + long, - short
    entry_price: Decimal
    stop_price: Decimal | None
    opened: date


class SessionBar(_Model):
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal


class PaperBroker:
    """Holds cash + positions; settles queued orders and armed stops."""

    def __init__(
        self,
        cash: Decimal,
        *,
        half_spread_bps: Decimal = Decimal("2.5"),
        slippage_bps: Decimal = Decimal("1.0"),
        positions: dict[str, Position] | None = None,
        fail_protection: bool = False,
    ) -> None:
        self.cash = cash
        self.positions: dict[str, Position] = dict(positions or {})
        self.queued: list[PaperOrder] = []
        self.half_spread_bps = half_spread_bps
        self.slippage_bps = slippage_bps
        self.fail_protection = fail_protection  # test hook for the incident path

    # ------------------------------------------------------------- queueing

    def queue(self, order: PaperOrder) -> None:
        self.queued.append(order)

    # ----------------------------------------------------------- settlement

    def _adverse(self, price: Decimal, buying: bool) -> Decimal:
        adj = (self.half_spread_bps + self.slippage_bps) / Decimal("10000")
        return price * (1 + adj) if buying else price * (1 - adj)

    def settle(
        self, bars: dict[str, SessionBar], session: date
    ) -> tuple[list[Fill], list[Fill], list[str]]:
        """Fill queued orders at the open, then run armed stops on high/low.

        Returns (entry_fills, stop_exit_fills, unprotected_symbols). Any symbol
        in ``unprotected_symbols`` failed protection arming (test hook or a
        zero stop on an opening order) and MUST trigger the incident path in
        the lifecycle layer.
        """

        fills: list[Fill] = []
        unprotected: list[str] = []
        still_queued: list[PaperOrder] = []
        for order in self.queued:
            bar = bars.get(order.symbol)
            if bar is None:
                still_queued.append(order)
                continue
            buying = order.direction in ("BUY", "BUY_TO_COVER")
            px = self._adverse(bar.open, buying)
            signed = order.quantity if buying else -order.quantity
            pos = self.positions.get(order.symbol)
            opening = pos is None or (pos.quantity > 0) == (signed > 0)
            protection_needed = opening and order.direction in ("BUY", "SELL_SHORT")
            stop_price: Decimal | None = None
            armed = False
            if (
                protection_needed
                and order.stop_distance_fraction > 0
                and not self.fail_protection
            ):
                stop_price = (
                    px * (1 - order.stop_distance_fraction)
                    if signed > 0
                    else px * (1 + order.stop_distance_fraction)
                )
                armed = True
            if protection_needed and not armed:
                unprotected.append(order.symbol)
            self.cash -= signed * px
            new_qty = (pos.quantity if pos else Decimal("0")) + signed
            if new_qty == 0:
                self.positions.pop(order.symbol, None)
            else:
                self.positions[order.symbol] = Position(
                    symbol=order.symbol,
                    quantity=new_qty,
                    entry_price=px if opening else (pos.entry_price if pos else px),
                    stop_price=stop_price if opening else (pos.stop_price if pos else None),
                    opened=session if opening else (pos.opened if pos else session),
                )
            fills.append(
                Fill(
                    order_id=order.order_id,
                    symbol=order.symbol,
                    direction=order.direction,
                    quantity=order.quantity,
                    price=px,
                    fill_date=session,
                    protection_armed=armed,
                    stop_price=stop_price,
                )
            )
        self.queued = still_queued

        # armed protective stops, adverse-first with gap handling
        stop_fills: list[Fill] = []
        for symbol in list(self.positions):
            pos = self.positions[symbol]
            if pos.stop_price is None:
                continue
            bar = bars.get(symbol)
            if bar is None:
                continue
            if pos.quantity > 0 and bar.low <= pos.stop_price:
                exit_px = min(bar.open, pos.stop_price)
                self.cash += pos.quantity * exit_px
                stop_fills.append(
                    Fill(
                        order_id=f"stop-{symbol}-{session.isoformat()}",
                        symbol=symbol,
                        direction="SELL",
                        quantity=pos.quantity,
                        price=exit_px,
                        fill_date=session,
                        protection_armed=False,
                        stop_price=pos.stop_price,
                    )
                )
                del self.positions[symbol]
            elif pos.quantity < 0 and bar.high >= pos.stop_price:
                exit_px = max(bar.open, pos.stop_price)
                self.cash += pos.quantity * exit_px  # negative qty: cash falls
                stop_fills.append(
                    Fill(
                        order_id=f"stop-{symbol}-{session.isoformat()}",
                        symbol=symbol,
                        direction="BUY_TO_COVER",
                        quantity=-pos.quantity,
                        price=exit_px,
                        fill_date=session,
                        protection_armed=False,
                        stop_price=pos.stop_price,
                    )
                )
                del self.positions[symbol]
        return fills, stop_fills, unprotected

    # -------------------------------------------------------------- marking

    def equity(self, closes: dict[str, Decimal]) -> Decimal:
        value = self.cash
        for symbol, pos in self.positions.items():
            px = closes.get(symbol, pos.entry_price)
            value += pos.quantity * px
        return value

    def gross_exposure(self, closes: dict[str, Decimal], equity: Decimal) -> Decimal:
        if equity <= 0:
            return Decimal("0")
        gross = Decimal("0")
        for symbol, pos in self.positions.items():
            px = closes.get(symbol, pos.entry_price)
            gross += abs(pos.quantity * px)
        return gross / equity
