from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from trading_desk.strategy.configuration import StrategyConfiguration
from trading_desk.strategy.data_validation import validate_market_data
from trading_desk.strategy.models import (
    FindingCode,
    StrategyBarResolution,
    StrategyContext,
    StrategyMarketData,
    StrategyVariant,
)


def _market_data(
    count: int = 240,
    *,
    status: str = "TRADEABLE",
    end_time: datetime | None = None,
) -> StrategyMarketData:
    final_time = end_time or datetime(2026, 7, 13, tzinfo=UTC)
    timestamps = tuple(final_time - timedelta(days=count - 1 - index) for index in range(count))
    closes = tuple(100.0 + index * 0.1 for index in range(count))
    return StrategyMarketData(
        epic="CS.D.TEST.CFD.IP",
        instrument_name="Test market",
        timestamps=timestamps,
        open_midpoints=closes,
        high_midpoints=tuple(value + 0.2 for value in closes),
        low_midpoints=tuple(value - 0.2 for value in closes),
        close_midpoints=closes,
        bids=tuple(value - 0.001 for value in closes),
        asks=tuple(value + 0.001 for value in closes),
        spreads=(0.002,) * count,
        spread_bps=(0.2,) * count,
        volume=(1000.0,) * count,
        market_status=status,
        data_retrieval_time=final_time,
        bar_resolution=StrategyBarResolution.DAY,
        source_bar_count=count,
    )


def _context(
    data: StrategyMarketData,
    *,
    holding: bool | None = False,
    status: str = "TRADEABLE",
    spread: float = 0.002,
    spread_bps: float = 0.2,
) -> StrategyContext:
    return StrategyContext(
        holding=holding,
        macro_score=1,
        current_spread=spread,
        current_spread_bps=spread_bps,
        market_status=status,
        current_time=data.timestamps[-1],
    )


@pytest.mark.parametrize(
    "override",
    [
        {"hmm_state_count": 2},
        {"kalman_process_level_noise": 0},
        {"kalman_observation_noise": -1},
        {"minimum_regime_probability": 1.1},
        {"maximum_regime_uncertainty": -0.1},
        {"minimum_bars_required": 209},
        {"long_only": False},
        {"allow_transitional_regime_entries": True},
        {"maximum_spread_bps": math.inf},
        {"hmm_convergence_tolerance": math.nan},
    ],
)
def test_strategy_configuration_rejects_unsafe_values(override: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        StrategyConfiguration.model_validate(override)


def test_configuration_fingerprint_is_stable_and_sensitive() -> None:
    first = StrategyConfiguration()
    second = StrategyConfiguration()
    changed = StrategyConfiguration(minimum_regime_probability=0.7)

    assert first.fingerprint == second.fingerprint
    assert len(first.fingerprint) == 64
    assert first.fingerprint != changed.fingerprint
    assert "PASSWORD" not in first.fingerprint_payload.upper()
    assert "SECRET" not in first.fingerprint_payload.upper()
    assert "strategy-schema-v2" in first.fingerprint_payload


def test_every_mutable_strategy_setting_changes_the_fingerprint() -> None:
    baseline = StrategyConfiguration()
    changes: dict[str, object] = {
        "variant": StrategyVariant.BASELINE_ONLY,
        "minimum_bars_required": 221,
        "kalman_minimum_observations": 31,
        "kalman_process_level_noise": 0.002,
        "kalman_process_slope_noise": 0.00002,
        "kalman_observation_noise": 0.02,
        "kalman_initial_level_variance": 2.0,
        "kalman_initial_slope_variance": 2.0,
        "maximum_kalman_normalized_slope_uncertainty": 0.02,
        "minimum_entry_deviation": -1.9,
        "maximum_entry_deviation": 0.9,
        "hmm_training_iterations": 201,
        "hmm_convergence_tolerance": 0.002,
        "hmm_random_seed": 43,
        "hmm_rolling_window": 21,
        "hmm_minimum_feature_observations": 121,
        "hmm_minimum_effective_observations": 11.0,
        "hmm_covariance_floor": 0.000002,
        "hmm_mapping_minimum_score_margin": 0.21,
        "maximum_absolute_standardized_feature": 19.0,
        "minimum_regime_probability": 0.61,
        "maximum_regime_uncertainty": 0.64,
        "maximum_spread_bps": 9.0,
        "minimum_trend_score": 2,
        "minimum_momentum_score": 2,
        "daily_maximum_age_seconds": 129601,
        "daily_weekend_grace_seconds": 172801,
        "intraday_maximum_age_multiple": 2.1,
        "maximum_gap_multiple": 4.1,
        "require_macro_confirmation": True,
    }
    for field, value in changes.items():
        changed = baseline.model_copy(update={field: value})
        assert changed.fingerprint != baseline.fingerprint, field


def test_conservative_history_defaults_are_separate() -> None:
    config = StrategyConfiguration()
    assert config.kalman_minimum_observations >= 30
    assert config.hmm_minimum_feature_observations >= 120
    assert config.hmm_minimum_effective_observations >= 10
    assert (
        config.minimum_bars_required - config.hmm_rolling_window
        >= config.hmm_minimum_feature_observations
    )


def test_market_data_model_rejects_mismatched_nonfinite_and_invalid_prices() -> None:
    data = _market_data()
    with pytest.raises(ValidationError, match="equal lengths"):
        StrategyMarketData.model_validate(
            {**data.model_dump(), "close_midpoints": data.close_midpoints[:-1]}
        )
    with pytest.raises(ValidationError, match="finite and positive"):
        StrategyMarketData.model_validate(
            {
                **data.model_dump(),
                "close_midpoints": (*data.close_midpoints[:-1], math.nan),
            }
        )
    with pytest.raises(ValidationError, match="bid cannot exceed ask"):
        StrategyMarketData.model_validate(
            {
                **data.model_dump(),
                "bids": (*data.bids[:-1], 101.0),
                "asks": (*data.asks[:-1], 100.0),
            }
        )


def test_valid_market_data_passes_validation() -> None:
    data = _market_data()
    result = validate_market_data(data, _context(data), StrategyConfiguration())

    assert result.valid is True
    assert result.findings == ()


@pytest.mark.parametrize(
    ("data_count", "holding", "status", "spread", "expected"),
    [
        (100, False, "TRADEABLE", 0.2, FindingCode.INSUFFICIENT_BARS),
        (240, None, "TRADEABLE", 0.2, FindingCode.HOLDING_STATE_UNKNOWN),
        (240, False, "CLOSED", 0.2, FindingCode.MARKET_NOT_TRADEABLE),
        (240, False, "TRADEABLE", 20.0, FindingCode.SPREAD_TOO_WIDE),
    ],
)
def test_validation_fails_closed_for_required_market_gates(
    data_count: int,
    holding: bool | None,
    status: str,
    spread: float,
    expected: FindingCode,
) -> None:
    data = _market_data(data_count, status=status)
    result = validate_market_data(
        data,
        _context(data, holding=holding, status=status, spread_bps=spread),
        StrategyConfiguration(),
    )

    assert result.valid is False
    assert expected in {finding.code for finding in result.findings}


def test_stale_and_excessive_gap_data_fail_closed() -> None:
    data = _market_data()
    stale_context = _context(data).model_copy(
        update={"current_time": data.timestamps[-1] + timedelta(days=10)}
    )
    stale = validate_market_data(data, stale_context, StrategyConfiguration())
    assert FindingCode.STALE_DATA in {finding.code for finding in stale.findings}

    timestamps = list(data.timestamps)
    timestamps[-1] = timestamps[-2] + timedelta(days=10)
    gapped = data.model_copy(update={"timestamps": tuple(timestamps)})
    gap_result = validate_market_data(gapped, _context(gapped), StrategyConfiguration())
    assert FindingCode.EXCESSIVE_TIME_GAP in {finding.code for finding in gap_result.findings}


def test_daily_weekend_grace_accepts_friday_to_monday_but_not_extended_staleness() -> None:
    friday = datetime(2026, 7, 10, 21, tzinfo=UTC)
    data = _market_data(end_time=friday)
    monday = _context(data).model_copy(
        update={"current_time": datetime(2026, 7, 13, 20, tzinfo=UTC)}
    )
    tuesday = monday.model_copy(update={"current_time": datetime(2026, 7, 14, 20, tzinfo=UTC)})

    assert validate_market_data(data, monday, StrategyConfiguration()).valid is True
    result = validate_market_data(data, tuesday, StrategyConfiguration())
    assert FindingCode.STALE_DATA in {finding.code for finding in result.findings}


@pytest.mark.parametrize(("midpoint", "absolute_spread"), [(1.1, 0.0011), (20000.0, 20.0)])
def test_relative_spread_gate_is_scale_invariant(midpoint: float, absolute_spread: float) -> None:
    data = _market_data().model_copy(
        update={
            "bids": (midpoint - absolute_spread / 2,) * 240,
            "asks": (midpoint + absolute_spread / 2,) * 240,
            "spreads": (absolute_spread,) * 240,
            "spread_bps": (10.0,) * 240,
        }
    )
    context = _context(data).model_copy(
        update={"current_spread": absolute_spread, "current_spread_bps": 10.0}
    )

    assert validate_market_data(data, context, StrategyConfiguration()).valid is True
