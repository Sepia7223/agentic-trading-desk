"""Confidence-weighted Kelly: the money-hunger harness must hold its rules."""

from __future__ import annotations

from pathlib import Path

import pytest

from trading_desk.confidence import (
    CalibrationLedger,
    ConfidenceInputs,
    KellySizer,
    bucket_of,
    confidence_score,
    target_r_multiple,
)
from trading_desk.confidence.sizing import MAX_MULTIPLIER, MIN_TRADES_TO_UNLOCK


def _inputs(**overrides) -> ConfidenceInputs:
    defaults = {
        "signal_percentile": 0.5,
        "sleeve_agreement": 0.5,
        "regime_vol_percentile": 0.5,
        "crowding_penalty": 0.5,
        "news_state": "clear",
    }
    defaults.update(overrides)
    return ConfidenceInputs(**defaults)


def _fill_bucket(
    ledger: CalibrationLedger, bucket: str, confidence: float, outcomes: list[float]
) -> None:
    for i, r in enumerate(outcomes):
        ledger.record(
            trade_id=f"{bucket}-{i}",
            symbol="TEST",
            confidence=confidence,
            bucket=bucket,
            outcome_r=r,
            opened="2026-07-01",
            closed="2026-07-10",
        )


def test_score_is_deterministic_and_bounded() -> None:
    perfect = _inputs(
        signal_percentile=1.0,
        sleeve_agreement=1.0,
        regime_vol_percentile=0.0,
        crowding_penalty=0.0,
    )
    assert confidence_score(perfect) == 1.0
    worst = _inputs(
        signal_percentile=0.0,
        sleeve_agreement=0.0,
        regime_vol_percentile=1.0,
        crowding_penalty=1.0,
    )
    assert confidence_score(worst) == 0.0
    assert confidence_score(_inputs()) == pytest.approx(0.5)


def test_news_caution_discounts_confidence() -> None:
    clear = confidence_score(_inputs(news_state="clear"))
    caution = confidence_score(_inputs(news_state="caution"))
    assert caution == pytest.approx(clear * 0.75)


def test_invalid_inputs_rejected() -> None:
    with pytest.raises(ValueError):
        _inputs(signal_percentile=1.5)
    with pytest.raises(ValueError):
        _inputs(news_state="blocked")


def test_bucket_boundaries() -> None:
    assert bucket_of(0.0) == "low"
    assert bucket_of(0.39) == "low"
    assert bucket_of(0.40) == "base"
    assert bucket_of(0.55) == "elevated"
    assert bucket_of(0.70) == "high"
    assert bucket_of(0.85) == "very_high"
    assert bucket_of(1.0) == "very_high"


def test_ledger_stats_and_kelly_math(tmp_path: Path) -> None:
    ledger = CalibrationLedger(tmp_path / "cal.jsonl")
    # 6 wins of +2R, 4 losses of -1R: W=0.6, payoff=2, f*=0.6-0.4/2=0.4
    _fill_bucket(ledger, "high", 0.75, [2.0] * 6 + [-1.0] * 4)
    stats = ledger.bucket_stats("high")
    assert stats.n == 10
    assert stats.win_rate == pytest.approx(0.6)
    assert stats.payoff_ratio == pytest.approx(2.0)
    assert stats.expectancy_r == pytest.approx(0.8)
    assert stats.kelly_fraction() == pytest.approx(0.4)


def test_degenerate_records_have_no_sizing_power(tmp_path: Path) -> None:
    ledger = CalibrationLedger(tmp_path / "cal.jsonl")
    _fill_bucket(ledger, "high", 0.75, [1.5] * 5)  # wins only: payoff undefined
    assert ledger.bucket_stats("high").kelly_fraction() == 0.0
    empty = ledger.bucket_stats("very_high")
    assert empty.n == 0 and empty.kelly_fraction() == 0.0


def test_low_confidence_downsizes_immediately(tmp_path: Path) -> None:
    sizer = KellySizer(CalibrationLedger(tmp_path / "cal.jsonl"))
    decision = sizer.decide(0.2)
    assert decision.bucket == "low"
    assert decision.multiplier == 0.5
    assert decision.unlocked


def test_unproven_bucket_stays_at_baseline(tmp_path: Path) -> None:
    ledger = CalibrationLedger(tmp_path / "cal.jsonl")
    _fill_bucket(ledger, "very_high", 0.9, [3.0] * (MIN_TRADES_TO_UNLOCK - 1))
    decision = KellySizer(ledger).decide(0.9)
    assert decision.multiplier == 1.0
    assert not decision.unlocked  # spectacular but insufficient history


def test_proven_bucket_earns_capped_multiplier(tmp_path: Path) -> None:
    ledger = CalibrationLedger(tmp_path / "cal.jsonl")
    # strong bucket: 30 trades, W=2/3, +2R wins vs -1R losses
    _fill_bucket(ledger, "very_high", 0.9, ([2.0, 2.0, -1.0] * 10))
    # mediocre rest-of-account: W=0.5, +1R vs -1R -> kelly 0
    _fill_bucket(ledger, "base", 0.45, [1.0, -1.0] * 20)
    decision = KellySizer(ledger).decide(0.9)
    assert decision.unlocked
    assert 1.0 < decision.multiplier <= MAX_MULTIPLIER


def test_no_account_edge_means_no_upsizing(tmp_path: Path) -> None:
    ledger = CalibrationLedger(tmp_path / "cal.jsonl")
    # bucket record exists and is losing overall: baseline kelly = 0
    _fill_bucket(ledger, "high", 0.75, [-1.0, 1.0, -1.0] * 10)
    decision = KellySizer(ledger).decide(0.75)
    assert decision.multiplier == 1.0
    assert not decision.unlocked


def test_target_scales_with_confidence() -> None:
    assert target_r_multiple(0.0) == pytest.approx(1.5)
    assert target_r_multiple(1.0) == pytest.approx(3.0)
    assert target_r_multiple(0.5) == pytest.approx(2.25)
    with pytest.raises(ValueError):
        target_r_multiple(1.2)
