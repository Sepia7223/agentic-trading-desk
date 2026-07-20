"""Attribution over authoritative operational closed-trade records.

The operational Demo ledger records native quote-currency realized P&L and an
aggregate observed cost — not a per-trade entry notional or a spread/slippage/
financing split. This reader stays faithful to what the authoritative record
carries: it attributes native-currency realized P&L exactly, decomposes gross
versus net using the recorded cost, converts to the reporting currency only
where dated evidence exists, and declares everything the ledger cannot support
as explicitly unavailable in a completeness diagnostic — never fabricated.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from trading_desk.analytics.currency import ConversionPolicy
from trading_desk.analytics.models import (
    AnalyticsModel,
    DimensionName,
    Measure,
    available,
    unavailable,
)
from trading_desk.context.fingerprints import fingerprint


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("closed-trade timestamps must be timezone-aware UTC")
    return value.astimezone(UTC)


class ClosedTradeSource(AnalyticsModel):
    """One authoritative closed-trade row, traced to its source records.

    Mirrors the fields the operational ledger (joined to its execution and
    reconciliation records) actually persists. ``currency`` is the native
    quote currency of ``realized_pnl``; an empty string means the currency
    evidence was not resolvable and the row is excluded, not guessed.
    """

    schema_version: Literal["analytics-closed-trade-source-v1"] = "analytics-closed-trade-source-v1"
    record_id: str = Field(min_length=1)
    source_record_ids: tuple[str, ...] = Field(min_length=1)
    strategy_id: str = Field(min_length=1)
    instrument: str = Field(min_length=1)
    timeframe: str = Field(min_length=1)
    regime: str = Field(min_length=1)
    exit_reason: str = Field(min_length=1)
    currency: str = Field(default="", max_length=3)
    occurred_at: datetime
    holding_period_seconds: Decimal | None = Field(default=None, ge=0)
    realized_pnl: Decimal | None = None
    estimated_cost: Decimal = Field(default=Decimal("0"), ge=0)
    observed_cost: Decimal = Field(default=Decimal("0"), ge=0)

    @field_validator("occurred_at")
    @classmethod
    def utc(cls, value: datetime) -> datetime:
        return _utc(value)


class ExcludedRecord(AnalyticsModel):
    record_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class CurrencyBlock(AnalyticsModel):
    """Authoritative native-currency totals — always reconcilable."""

    currency: str = Field(min_length=3, max_length=3)
    trade_count: int = Field(ge=0)
    gross_realized: Decimal
    observed_cost: Decimal = Field(ge=0)
    estimated_cost: Decimal = Field(ge=0)
    net_realized: Decimal
    implementation_shortfall: Decimal

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if self.net_realized != self.gross_realized - self.observed_cost:
            raise ValueError("net must equal gross minus observed cost")
        if self.implementation_shortfall != self.observed_cost - self.estimated_cost:
            raise ValueError("shortfall must equal observed minus estimated cost")
        return self


class LedgerSlice(AnalyticsModel):
    dimension: DimensionName
    key: str
    currency: str = Field(min_length=3, max_length=3)
    trade_count: int = Field(ge=0)
    gross_realized: Decimal
    net_realized: Decimal
    observed_cost: Decimal = Field(ge=0)


class CompletenessDiagnostic(AnalyticsModel):
    """What the authoritative ledger can and cannot support, stated plainly."""

    schema_version: Literal["analytics-completeness-v1"] = "analytics-completeness-v1"
    sources_seen: int = Field(ge=0)
    included: int = Field(ge=0)
    excluded: int = Field(ge=0)
    records_missing_holding_period: int = Field(ge=0)
    notional_normalized_returns: Measure
    cost_decomposition: Measure


class LedgerAttributionReport(AnalyticsModel):
    """Deterministic, fingerprinted attribution over operational closed trades."""

    schema_version: Literal["analytics-ledger-attribution-v1"] = "analytics-ledger-attribution-v1"
    report_id: str = Field(min_length=64, max_length=64)
    reporting_currency: str = Field(min_length=3, max_length=3)
    input_start: datetime | None
    input_end: datetime | None
    trade_count: int = Field(ge=0)
    native: tuple[CurrencyBlock, ...]
    attribution: tuple[LedgerSlice, ...]
    reporting_gross: Measure
    reporting_net: Measure
    reporting_cost_drag: Measure
    reporting_implementation_shortfall: Measure
    exposure_seconds: Measure
    excluded: tuple[ExcludedRecord, ...]
    completeness: CompletenessDiagnostic
    reconciled: bool

    @model_validator(mode="after")
    def identity(self) -> Self:
        expected = fingerprint(self.model_dump(mode="python", exclude={"report_id"}))
        if self.report_id != expected:
            raise ValueError("ledger attribution fingerprint mismatch")
        return self


_DIMENSION_KEYS = {
    DimensionName.STRATEGY: lambda row: row.strategy_id,
    DimensionName.INSTRUMENT: lambda row: row.instrument,
    DimensionName.TIMEFRAME: lambda row: row.timeframe,
    DimensionName.REGIME: lambda row: row.regime,
    DimensionName.EXIT_REASON: lambda row: row.exit_reason,
}


def _create_report(**values: object) -> LedgerAttributionReport:
    draft_fields = {**values, "report_id": "0" * 64}
    draft = LedgerAttributionReport.model_construct(**draft_fields)  # type: ignore[arg-type]
    fields = draft.model_dump(mode="python", exclude={"report_id"})
    return LedgerAttributionReport.model_validate({**fields, "report_id": fingerprint(fields)})


def build_ledger_attribution(
    sources: tuple[ClosedTradeSource, ...], policy: ConversionPolicy
) -> LedgerAttributionReport:
    """Attribute authoritative operational closed trades, currency-aware."""

    included: list[ClosedTradeSource] = []
    excluded: list[ExcludedRecord] = []
    for row in sorted(sources, key=lambda item: (item.occurred_at, item.record_id)):
        if row.realized_pnl is None:
            excluded.append(ExcludedRecord(record_id=row.record_id, reason="MISSING_REALIZED_PNL"))
        elif len(row.currency) != 3:
            excluded.append(
                ExcludedRecord(record_id=row.record_id, reason="CURRENCY_EVIDENCE_UNAVAILABLE")
            )
        else:
            included.append(row)

    currencies = sorted({row.currency for row in included})
    native: list[CurrencyBlock] = []
    for currency in currencies:
        members = [row for row in included if row.currency == currency]
        gross = sum((row.realized_pnl or Decimal(0) for row in members), Decimal(0))
        observed = sum((row.observed_cost for row in members), Decimal(0))
        estimated = sum((row.estimated_cost for row in members), Decimal(0))
        native.append(
            CurrencyBlock(
                currency=currency,
                trade_count=len(members),
                gross_realized=gross,
                observed_cost=observed,
                estimated_cost=estimated,
                net_realized=gross - observed,
                implementation_shortfall=observed - estimated,
            )
        )

    attribution: list[LedgerSlice] = []
    for dimension, key_of in _DIMENSION_KEYS.items():
        for currency in currencies:
            members = [row for row in included if row.currency == currency]
            for key in sorted({key_of(row) for row in members}):
                group = [row for row in members if key_of(row) == key]
                gross = sum((row.realized_pnl or Decimal(0) for row in group), Decimal(0))
                observed = sum((row.observed_cost for row in group), Decimal(0))
                attribution.append(
                    LedgerSlice(
                        dimension=dimension,
                        key=key,
                        currency=currency,
                        trade_count=len(group),
                        gross_realized=gross,
                        net_realized=gross - observed,
                        observed_cost=observed,
                    )
                )

    input_end = max((row.occurred_at for row in included), default=None)
    reporting = _reporting_rollup(native, policy, input_end)

    holding = [row for row in included if row.holding_period_seconds is not None]
    exposure = (
        available(sum((row.holding_period_seconds or Decimal(0) for row in holding), Decimal(0)))
        if holding
        else unavailable("NO_HOLDING_PERIOD_EVIDENCE")
    )
    reconciled = _reconciles(native, attribution)

    completeness = CompletenessDiagnostic(
        sources_seen=len(sources),
        included=len(included),
        excluded=len(excluded),
        records_missing_holding_period=len(included) - len(holding),
        notional_normalized_returns=unavailable("NO_ENTRY_NOTIONAL_IN_LEDGER"),
        cost_decomposition=unavailable("LEDGER_RECORDS_AGGREGATE_COST_ONLY"),
    )
    return _create_report(
        reporting_currency=policy.reporting_currency,
        input_start=min((row.occurred_at for row in included), default=None),
        input_end=input_end,
        trade_count=len(included),
        native=tuple(native),
        attribution=tuple(attribution),
        reporting_gross=reporting["gross"],
        reporting_net=reporting["net"],
        reporting_cost_drag=reporting["cost"],
        reporting_implementation_shortfall=reporting["shortfall"],
        exposure_seconds=exposure,
        excluded=tuple(excluded),
        completeness=completeness,
        reconciled=reconciled,
    )


def _reporting_rollup(
    native: list[CurrencyBlock], policy: ConversionPolicy, at: datetime | None
) -> dict[str, Measure]:
    if not native:
        empty = unavailable("NO_CLOSED_TRADES")
        return {"gross": empty, "net": empty, "cost": empty, "shortfall": empty}
    if at is None:
        blocked = unavailable("NO_CONVERSION_TIMESTAMP")
        return {"gross": blocked, "net": blocked, "cost": blocked, "shortfall": blocked}
    missing = [
        block.currency for block in native if policy.convert(Decimal(0), block.currency, at) is None
    ]
    if missing:
        reason = "MISSING_CONVERSION_RATE:" + ",".join(sorted(missing))
        blocked = unavailable(reason)
        return {"gross": blocked, "net": blocked, "cost": blocked, "shortfall": blocked}
    totals = {"gross": Decimal(0), "net": Decimal(0), "cost": Decimal(0), "shortfall": Decimal(0)}
    for block in native:
        for measure, value in (
            ("gross", block.gross_realized),
            ("net", block.net_realized),
            ("cost", block.observed_cost),
            ("shortfall", block.implementation_shortfall),
        ):
            converted = policy.convert(value, block.currency, at)
            assert converted is not None
            totals[measure] += converted
    return {name: available(value) for name, value in totals.items()}


def _reconciles(native: list[CurrencyBlock], attribution: list[LedgerSlice]) -> bool:
    for block in native:
        for dimension in DimensionName:
            slices = [
                item
                for item in attribution
                if item.dimension is dimension and item.currency == block.currency
            ]
            if sum((item.gross_realized for item in slices), Decimal(0)) != block.gross_realized:
                return False
            if sum((item.net_realized for item in slices), Decimal(0)) != block.net_realized:
                return False
            if sum(item.trade_count for item in slices) != block.trade_count:
                return False
    return True
