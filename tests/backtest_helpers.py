from __future__ import annotations

import hashlib
import math
from datetime import UTC, datetime, timedelta

from trading_desk.backtest.configuration import BacktestConfiguration, SplitConfiguration
from trading_desk.backtest.models import BacktestBar, BacktestDataManifest, BacktestDataset
from trading_desk.strategy.models import StrategyBarResolution, StrategyVariant


def bars(count: int = 250) -> tuple[BacktestBar, ...]:
    start = datetime(2020, 1, 1, tzinfo=UTC)
    result = []
    for index in range(count):
        close_bid = 100.0 + index * 0.03 + math.sin(index / 7) * 0.25
        open_bid = close_bid - 0.01
        spread = 0.02
        result.append(
            BacktestBar(
                epic="CS.D.TEST.CFD.IP",
                timestamp=start + timedelta(days=index),
                open_bid=open_bid,
                open_ask=open_bid + spread,
                high_bid=max(open_bid, close_bid) + 0.2,
                high_ask=max(open_bid, close_bid) + 0.2 + spread,
                low_bid=min(open_bid, close_bid) - 0.2,
                low_ask=min(open_bid, close_bid) - 0.2 + spread,
                close_bid=close_bid,
                close_ask=close_bid + spread,
                last_traded_volume=1000.0 + index,
            )
        )
    return tuple(result)


def dataset(count: int = 250, *, source: str = "prices.csv") -> BacktestDataset:
    values = bars(count)
    digest = hashlib.sha256(
        "\n".join(f"{item.timestamp.isoformat()},{item.close_bid}" for item in values).encode()
    ).hexdigest()
    return BacktestDataset(
        bars=values,
        manifest=BacktestDataManifest(
            source_filename=source,
            content_sha256=digest,
            row_count=len(values),
            first_timestamp=values[0].timestamp,
            last_timestamp=values[-1].timestamp,
            resolution=StrategyBarResolution.DAY,
        ),
    )


def configuration(
    *,
    count: int = 250,
    variant: StrategyVariant = StrategyVariant.BASELINE_ONLY,
    **updates: object,
) -> BacktestConfiguration:
    values = bars(count)
    settings: dict[str, object] = {
        "dataset_source": "prices.csv",
        "epic": "CS.D.TEST.CFD.IP",
        "resolution": StrategyBarResolution.DAY,
        "splits": SplitConfiguration(
            train_end=values[219].timestamp,
            validation_end=values[min(234, count - 2)].timestamp,
            test_end=values[count - 1].timestamp,
        ),
        "variant": variant,
    }
    settings.update(updates)
    return BacktestConfiguration.model_validate(settings)
