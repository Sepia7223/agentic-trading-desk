"""UTC completed-bar and cadence calculations."""

from datetime import UTC, datetime

from trading_desk.context.models import ContextTimeframe


def completed_bar_boundary(now: datetime, timeframe: ContextTimeframe) -> datetime:
    if now.tzinfo is None:
        raise ValueError("scheduler clock requires a timezone-aware timestamp")
    epoch = int(now.astimezone(UTC).timestamp())
    boundary = epoch - epoch % timeframe.seconds
    return datetime.fromtimestamp(boundary, tz=UTC)


def cadence_boundary(now: datetime, interval_seconds: int) -> datetime:
    if now.tzinfo is None:
        raise ValueError("scheduler clock requires a timezone-aware timestamp")
    epoch = int(now.astimezone(UTC).timestamp())
    return datetime.fromtimestamp(epoch - epoch % interval_seconds, tz=UTC)
