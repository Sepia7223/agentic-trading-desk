"""Typed market-data normalization and deterministic fail-closed validation."""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from statistics import median

from pydantic import ValidationError

from trading_desk.ig.models import HistoricalPricePage
from trading_desk.strategy.configuration import StrategyConfiguration
from trading_desk.strategy.models import (
    DataValidationResult,
    FindingCode,
    MarketDataBuildResult,
    StrategyBarResolution,
    StrategyContext,
    StrategyMarketData,
    ValidationFinding,
)


def market_data_from_ig_page(
    page: HistoricalPricePage,
    *,
    epic: str,
    instrument_name: str,
    market_status: str,
    data_retrieval_time: datetime,
    bar_resolution: StrategyBarResolution | None = None,
) -> MarketDataBuildResult:
    """Convert normalized IG bars without importing transport or session state."""

    timestamps: list[datetime] = []
    opens: list[float] = []
    highs: list[float] = []
    lows: list[float] = []
    closes: list[float] = []
    bids: list[float | None] = []
    asks: list[float | None] = []
    spreads: list[float] = []
    spread_bps: list[float] = []
    volumes: list[float | None] = []
    excluded = 0

    for bar in page.bars:
        midpoint_values = (
            bar.midpoint_open,
            bar.midpoint_high,
            bar.midpoint_low,
            bar.midpoint_close,
        )
        if not bar.valid_for_strategy or any(value is None for value in midpoint_values):
            excluded += 1
            continue
        open_mid, high_mid, low_mid, close_mid = midpoint_values
        assert open_mid is not None
        assert high_mid is not None
        assert low_mid is not None
        assert close_mid is not None
        bid = float(bar.close.bid) if bar.close.bid is not None else None
        ask = float(bar.close.ask) if bar.close.ask is not None else None
        timestamps.append(bar.timestamp)
        opens.append(float(open_mid))
        highs.append(float(high_mid))
        lows.append(float(low_mid))
        closes.append(float(close_mid))
        bids.append(bid)
        asks.append(ask)
        absolute_spread = (ask - bid) if bid is not None and ask is not None else 0.0
        close_midpoint = float(close_mid)
        spreads.append(absolute_spread)
        spread_bps.append(10_000.0 * absolute_spread / close_midpoint)
        volumes.append(
            float(bar.last_traded_volume) if bar.last_traded_volume is not None else None
        )

    findings: list[ValidationFinding] = []
    if excluded:
        findings.append(
            ValidationFinding(
                code=FindingCode.INVALID_IG_BARS,
                message=f"{excluded} normalized IG bars were excluded as invalid",
                blocking=False,
            )
        )
    try:
        data = StrategyMarketData(
            epic=epic,
            instrument_name=instrument_name,
            timestamps=tuple(timestamps),
            open_midpoints=tuple(opens),
            high_midpoints=tuple(highs),
            low_midpoints=tuple(lows),
            close_midpoints=tuple(closes),
            bids=tuple(bids),
            asks=tuple(asks),
            spreads=tuple(spreads),
            spread_bps=tuple(spread_bps),
            volume=tuple(volumes),
            market_status=market_status,
            data_retrieval_time=data_retrieval_time,
            bar_resolution=bar_resolution,
            source_bar_count=len(page.bars),
            excluded_invalid_bars=excluded,
        )
    except ValidationError:
        findings.append(
            ValidationFinding(
                code=FindingCode.NON_FINITE_VALUE,
                message="normalized IG bars could not form consistent strategy data",
            )
        )
        return MarketDataBuildResult(data=None, findings=tuple(findings))
    return MarketDataBuildResult(data=data, findings=tuple(findings))


def validate_market_data(
    data: StrategyMarketData,
    context: StrategyContext,
    config: StrategyConfiguration,
    *,
    inherited_findings: tuple[ValidationFinding, ...] = (),
) -> DataValidationResult:
    findings = list(inherited_findings)
    count = len(data.timestamps)
    if count < config.minimum_bars_required:
        findings.append(
            ValidationFinding(
                code=FindingCode.INSUFFICIENT_BARS,
                message=(f"{count} valid bars available; {config.minimum_bars_required} required"),
            )
        )

    lengths = {
        len(data.timestamps),
        len(data.open_midpoints),
        len(data.high_midpoints),
        len(data.low_midpoints),
        len(data.close_midpoints),
        len(data.bids),
        len(data.asks),
        len(data.spreads),
        len(data.spread_bps),
    }
    if len(lengths) != 1:
        findings.append(
            ValidationFinding(
                code=FindingCode.SERIES_LENGTH_MISMATCH,
                message="market-data series lengths differ",
            )
        )
    if any(
        left >= right for left, right in zip(data.timestamps, data.timestamps[1:], strict=False)
    ):
        findings.append(
            ValidationFinding(
                code=FindingCode.TIMESTAMPS_NOT_INCREASING,
                message="timestamps are duplicated or unsorted",
            )
        )

    required_prices = (
        data.open_midpoints,
        data.high_midpoints,
        data.low_midpoints,
        data.close_midpoints,
    )
    if any(not math.isfinite(value) for values in required_prices for value in values):
        findings.append(
            ValidationFinding(
                code=FindingCode.NON_FINITE_VALUE,
                message="required prices contain a non-finite value",
            )
        )
    if any(value <= 0 for values in required_prices for value in values):
        findings.append(
            ValidationFinding(
                code=FindingCode.NON_POSITIVE_PRICE,
                message="required prices contain a zero or negative value",
            )
        )
    if any(
        bid is not None and ask is not None and bid > ask
        for bid, ask in zip(data.bids, data.asks, strict=False)
    ):
        findings.append(
            ValidationFinding(
                code=FindingCode.INVALID_BID_ASK,
                message="a bid exceeds its corresponding ask",
            )
        )

    cadence_seconds, inferred_resolution = infer_bar_cadence(data)
    if cadence_seconds is None or inferred_resolution is None:
        findings.append(
            ValidationFinding(
                code=FindingCode.UNKNOWN_BAR_CADENCE,
                message="bar cadence could not be determined safely",
            )
        )

    if data.timestamps and cadence_seconds is not None and inferred_resolution is not None:
        age_seconds = (context.current_time - data.timestamps[-1]).total_seconds()
        if age_seconds < 0:
            findings.append(
                ValidationFinding(
                    code=FindingCode.FUTURE_DATA,
                    message="latest market bar is later than the evaluation time",
                )
            )
        elif inferred_resolution is StrategyBarResolution.DAY:
            allowed_age = float(config.daily_maximum_age_seconds)
            if _interval_contains_weekend(data.timestamps[-1], context.current_time):
                allowed_age += config.daily_weekend_grace_seconds
            if age_seconds > allowed_age:
                findings.append(
                    ValidationFinding(
                        code=FindingCode.STALE_DATA,
                        message="latest daily bar exceeds the resolution-aware age limit",
                    )
                )
        elif age_seconds > cadence_seconds * config.intraday_maximum_age_multiple:
            findings.append(
                ValidationFinding(
                    code=FindingCode.STALE_DATA,
                    message="latest intraday bar exceeds the cadence-aware age limit",
                )
            )

    if data.market_status.upper() != "TRADEABLE" or context.market_status.upper() != "TRADEABLE":
        findings.append(
            ValidationFinding(
                code=FindingCode.MARKET_NOT_TRADEABLE,
                message="market status is not TRADEABLE",
            )
        )
    if context.current_spread_bps > config.maximum_spread_bps:
        findings.append(
            ValidationFinding(
                code=FindingCode.SPREAD_TOO_WIDE,
                message="current relative spread exceeds the configured basis-point threshold",
            )
        )
    if context.holding is None:
        findings.append(
            ValidationFinding(
                code=FindingCode.HOLDING_STATE_UNKNOWN,
                message="holding state is unknown",
            )
        )

    if len(data.timestamps) >= 3:
        gaps = [
            (right - left).total_seconds()
            for left, right in zip(data.timestamps, data.timestamps[1:], strict=False)
        ]
        typical_gap = median(gaps)
        if typical_gap <= 0 or any(gap > typical_gap * config.maximum_gap_multiple for gap in gaps):
            findings.append(
                ValidationFinding(
                    code=FindingCode.EXCESSIVE_TIME_GAP,
                    message="historical series contains a gap beyond tolerance",
                )
            )

    valid = not any(finding.blocking for finding in findings)
    return DataValidationResult(valid=valid, findings=tuple(findings))


def infer_bar_cadence(
    data: StrategyMarketData,
) -> tuple[float | None, StrategyBarResolution | None]:
    """Return a conservative cadence without consulting a market calendar."""

    cadence_by_resolution = {
        StrategyBarResolution.HOUR: 3600.0,
        StrategyBarResolution.HOUR_4: 14400.0,
        StrategyBarResolution.DAY: 86400.0,
    }
    if data.bar_resolution is not None:
        return cadence_by_resolution[data.bar_resolution], data.bar_resolution
    if len(data.timestamps) < 3:
        return None, None
    gaps = [
        (right - left).total_seconds()
        for left, right in zip(data.timestamps, data.timestamps[1:], strict=False)
    ]
    typical = float(median(gaps))
    if typical <= 0:
        return None, None
    closest = min(cadence_by_resolution.items(), key=lambda item: abs(item[1] - typical))
    if abs(closest[1] - typical) / closest[1] > 0.10:
        return None, None
    return closest[1], closest[0]


def _interval_contains_weekend(start: datetime, end: datetime) -> bool:
    day = start.date()
    while day <= end.date():
        if day.weekday() >= 5:
            return True
        day += timedelta(days=1)
    return False
