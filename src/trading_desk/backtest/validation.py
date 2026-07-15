"""Fail-closed local dataset validation."""

from __future__ import annotations

from collections import Counter
from datetime import timedelta

from trading_desk.backtest.models import BacktestBar, DataQualityFinding
from trading_desk.strategy.models import StrategyBarResolution


class BacktestDataError(ValueError):
    """Raised when local historical data cannot be used safely."""


def validate_bars(
    bars: tuple[BacktestBar, ...], resolution: StrategyBarResolution
) -> tuple[DataQualityFinding, ...]:
    if not bars:
        raise BacktestDataError("historical dataset is empty")
    timestamps = tuple(bar.timestamp for bar in bars)
    if len(set(timestamps)) != len(timestamps):
        raise BacktestDataError("historical dataset contains duplicate timestamps")
    if any(left >= right for left, right in zip(timestamps, timestamps[1:], strict=False)):
        raise BacktestDataError("historical timestamps are not strictly increasing")

    expected_seconds = {
        StrategyBarResolution.DAY: 86400.0,
        StrategyBarResolution.HOUR_4: 14400.0,
        StrategyBarResolution.HOUR: 3600.0,
    }[resolution]
    findings: list[DataQualityFinding] = []
    gaps = [
        (right - left).total_seconds()
        for left, right in zip(timestamps, timestamps[1:], strict=False)
    ]
    for row, gap in enumerate(gaps, start=2):
        if resolution is StrategyBarResolution.DAY:
            if gap not in {expected_seconds, expected_seconds * 2, expected_seconds * 3}:
                findings.append(
                    DataQualityFinding(
                        code="CHANGING_CADENCE",
                        message="daily cadence is neither a daily nor weekend interval",
                        row_number=row,
                    )
                )
        elif abs(gap - expected_seconds) > expected_seconds * 0.01:
            findings.append(
                DataQualityFinding(
                    code="CHANGING_CADENCE",
                    message="intraday bar cadence changed",
                    row_number=row,
                )
            )
    non_tradeable = Counter(bar.market_status.upper() != "TRADEABLE" for bar in bars)[True]
    if non_tradeable:
        findings.append(
            DataQualityFinding(
                code="NON_TRADEABLE_BARS",
                message=f"{non_tradeable} bars are marked non-tradeable",
                blocking=False,
            )
        )
    if any(finding.blocking for finding in findings):
        codes = ", ".join(sorted({finding.code for finding in findings if finding.blocking}))
        raise BacktestDataError(f"historical dataset failed validation: {codes}")
    return tuple(findings)


def permitted_execution_deadline(signal_index: int, delay_bars: int) -> int:
    if delay_bars < 1:
        raise ValueError("same-bar execution is prohibited")
    return signal_index + delay_bars


def days_held(start: object, end: object) -> float:
    if not hasattr(start, "__sub__"):
        return 0.0
    delta = end - start  # type: ignore[operator]
    if not isinstance(delta, timedelta):
        return 0.0
    return max(delta.total_seconds() / 86400.0, 0.0)
