"""Authoritative read-only exposure snapshots for opportunity filtering."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

from trading_desk.ig.models import Direction, OpenPosition
from trading_desk.opportunity.config import MarketUniverse
from trading_desk.opportunity.fingerprints import fingerprint


class ReadOnlyPositionSource(Protocol):
    async def get_open_positions(self) -> tuple[OpenPosition, ...]: ...


class PositionExposure(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)
    epic: str
    instrument_id: str
    direction: str
    quantity: Decimal = Field(gt=0)
    correlation_groups: tuple[str, ...]


class CurrentExposureSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)
    observed_at: datetime
    positions: tuple[PositionExposure, ...]
    recently_closed: tuple[tuple[str, datetime], ...] = ()
    snapshot_fingerprint: str = Field(min_length=64, max_length=64)

    @field_validator("observed_at")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("exposure timestamp must be UTC")
        return value.astimezone(UTC)

    @property
    def existing_epics(self) -> tuple[str, ...]:
        return tuple(item.epic for item in self.positions)

    @property
    def occupied_correlation_groups(self) -> tuple[str, ...]:
        return tuple(group for item in self.positions for group in item.correlation_groups)

    @property
    def current_position_count(self) -> int:
        return len(self.positions)

    @property
    def base_currency_exposure(self) -> tuple[tuple[str, Decimal], ...]:
        return _currency_exposure(self.positions, base=True)

    @property
    def quote_currency_exposure(self) -> tuple[tuple[str, Decimal], ...]:
        return _currency_exposure(self.positions, base=False)


class OperationalExposureProvider:
    def __init__(self, source: ReadOnlyPositionSource, universe: MarketUniverse) -> None:
        self._source = source
        self._universe = universe

    async def snapshot(
        self,
        observed_at: datetime,
        *,
        recently_closed: tuple[tuple[str, datetime], ...] = (),
    ) -> CurrentExposureSnapshot:
        positions = await self._source.get_open_positions()
        by_epic = {item.epic: item for item in self._universe.markets}
        normalized: list[PositionExposure] = []
        for position in positions:
            market = by_epic.get(position.market.epic)
            if market is None or position.direction not in {Direction.BUY, Direction.SELL}:
                raise ValueError("authoritative position cannot be mapped to governed exposure")
            normalized.append(
                PositionExposure(
                    epic=market.epic,
                    instrument_id=market.instrument_id,
                    direction=position.direction.value,
                    quantity=position.size,
                    correlation_groups=market.correlation_groups,
                )
            )
        fields = {
            "observed_at": observed_at,
            "positions": tuple(sorted(normalized, key=lambda item: item.epic)),
            "recently_closed": recently_closed,
        }
        return CurrentExposureSnapshot.model_validate(
            {**fields, "snapshot_fingerprint": fingerprint(fields)}
        )


def _currency_exposure(
    positions: tuple[PositionExposure, ...], *, base: bool
) -> tuple[tuple[str, Decimal], ...]:
    totals: dict[str, Decimal] = {}
    for position in positions:
        currency = position.instrument_id.split("/")[0 if base else 1]
        totals[currency] = totals.get(currency, Decimal("0")) + position.quantity
    return tuple(sorted(totals.items()))
