from __future__ import annotations

import math

from trading_desk.strategy import score


def _indicator_state(**overrides: object) -> dict[str, object]:
    state: dict[str, object] = {
        "close": 100.0,
        "ema20": 100.0,
        "ema50": 100.0,
        "ema200": 100.0,
        "ema20_slope": 0.0,
        "ema200_slope": 0.0,
        "rsi14": 50.0,
        "rsi14_prev": 50.0,
        "macd_hist": 0.0,
        "macd_hist_prev": 0.0,
        "trix": 0.0,
        "trix_signal": 0.0,
        "trix_prev": 0.0,
        "trix_signal_prev": 0.0,
        "percent_b": 0.5,
        "bars_since_below_ema20": None,
    }
    state.update(overrides)
    return state


def test_trend_and_momentum_scores_for_bullish_self_test_series() -> None:
    close = [round(100 + i * 0.25 + 6 * math.sin(i / 12), 2) for i in range(260)]
    close += [close[-1] * 1.05, close[-1] * 1.10]

    card = score.score_symbol(close, macro_score=1, symbol="SELFTEST", holding=True)

    assert card["pillars"]["trend"]["score"] == 2
    assert card["pillars"]["momentum"]["score"] == 2
    assert card["pillar_total"] == 5
    assert card["decision"]["action"] == "HOLD (ride the cycle)"
    assert card["decision"]["flags"]["exhaustion"] == ["price at/above upper Bollinger Band (%B≥1)"]


def test_score_symbol_regression_for_original_self_test_output() -> None:
    close = [round(100 + i * 0.25 + 6 * math.sin(i / 12), 2) for i in range(260)]
    close += [close[-1] * 1.05, close[-1] * 1.10]

    card = score.score_symbol(close, macro_score=1, symbol="SELFTEST", holding=True)

    assert card["symbol"] == "SELFTEST"
    assert card["n_bars"] == 262
    assert card["warning"] is None
    assert card["pillars"] == {
        "trend": {
            "score": 2,
            "detail": "price>EMA20, EMA20>EMA50, EMA50>EMA200, EMA200↑",
        },
        "momentum": {"score": 2, "detail": "RSI 96≥55, MACD hist>0, TRIX mixed"},
        "macro_sentiment": {"score": 1, "detail": "injected from macro_pillar.py"},
    }
    assert card["decision"]["action"] == "HOLD (ride the cycle)"
    assert card["decision"]["flags"] == {
        "exhaustion": ["price at/above upper Bollinger Band (%B≥1)"],
        "bearish": [],
        "rebound": ["MACD histogram crossing bullishly"],
        "death_cross": False,
        "stretch_pct": 8.9,
    }
    assert card["indicators"] == {
        "n_bars": 262,
        "warning": None,
        "close": 183.843,
        "ema20": 168.8458,
        "ema50": 162.6398,
        "ema200": 141.4585,
        "ema20_slope": 2.7621,
        "ema50_slope": 2.2034,
        "ema200_slope": 1.5834,
        "rsi14": 96.4349,
        "rsi14_prev": 93.7001,
        "macd_line": 3.4734,
        "macd_signal": 2.7039,
        "macd_hist": 0.7695,
        "macd_hist_prev": -0.0742,
        "trix": 0.2391,
        "trix_prev": 0.2275,
        "trix_signal": 0.2616,
        "trix_signal_prev": 0.2673,
        "bars_since_below_ema20": 54,
        "bb_mid": 168.7405,
        "bb_upper": 176.5425,
        "bb_lower": 160.9384,
        "percent_b": 1.4679,
    }


def test_unknown_holding_state_results_in_no_trade() -> None:
    ind = {
        "close": 90.0,
        "ema20": 100.0,
        "ema50": 105.0,
        "ema200": 110.0,
        "ema20_slope": -1.0,
        "ema200_slope": -1.0,
        "rsi14": 40.0,
        "rsi14_prev": 42.0,
        "macd_hist": -1.0,
        "macd_hist_prev": -0.5,
        "trix": -1.0,
        "trix_signal": -0.5,
        "trix_prev": -1.1,
        "trix_signal_prev": -0.8,
        "percent_b": 0.1,
        "bars_since_below_ema20": 0,
    }

    decision = score.decide(ind, trend=-2, mom=-2, macro=None, holding=None)

    assert decision["action"] == "NO TRADE"
    assert decision["rationale"] == "Position state unknown."


def test_holding_and_flat_states_preserve_distinct_bullish_decisions() -> None:
    indicators = _indicator_state()

    holding = score.decide(indicators, trend=2, mom=2, macro=1, holding=True)
    flat = score.decide(indicators, trend=2, mom=2, macro=1, holding=False)

    assert holding["action"] == "HOLD (ride the cycle)"
    assert flat["action"] == "WAIT (do not chase)"


def test_exhaustion_flags_and_holder_exit_behavior_are_preserved() -> None:
    indicators = _indicator_state(
        close=121.0,
        ema20=100.0,
        rsi14=72.0,
        rsi14_prev=75.0,
        macd_hist=0.2,
        macd_hist_prev=0.5,
        percent_b=1.1,
    )

    decision = score.decide(indicators, trend=2, mom=1, macro=0, holding=True)

    assert decision["action"] == "EXIT / TRIM"
    assert decision["flags"]["exhaustion"] == [
        "RSI turning from overbought (75\u219272)",
        "MACD histogram shrinking in positive territory",
        "price at/above upper Bollinger Band (%B\u22651)",
        "price stretched 21% above EMA20",
    ]


def test_bearish_flags_and_holding_versus_flat_behavior_are_preserved() -> None:
    indicators = _indicator_state(
        close=80.0,
        ema50=90.0,
        ema200=100.0,
        ema200_slope=-1.0,
        rsi14=40.0,
        rsi14_prev=42.0,
        macd_hist=-1.0,
        macd_hist_prev=-0.5,
        trix=-1.0,
        trix_signal=-0.5,
    )

    holding = score.decide(indicators, trend=-2, mom=-2, macro=0, holding=True)
    flat = score.decide(indicators, trend=-2, mom=-2, macro=0, holding=False)

    expected_flags = [
        "price<EMA50<EMA200 with EMA200\u2193",
        "MACD histogram deepening in negative territory",
        "TRIX<signal below zero",
        "RSI weak and falling (40)",
    ]
    assert holding["action"] == "EXIT"
    assert flat["action"] == "STAY OUT / AVOID"
    assert holding["flags"]["bearish"] == expected_flags
    assert holding["flags"]["death_cross"] is True


def test_rebound_flags_and_death_cross_behavior_are_preserved() -> None:
    indicators = _indicator_state(
        close=91.0,
        ema20=90.0,
        ema50=95.0,
        ema200=100.0,
        ema20_slope=1.0,
        rsi14=34.0,
        rsi14_prev=30.0,
        macd_hist=-0.2,
        macd_hist_prev=-0.5,
        trix=-0.1,
        trix_signal=-0.2,
        trix_prev=-0.3,
        trix_signal_prev=-0.2,
        bars_since_below_ema20=2,
    )

    decision = score.decide(indicators, trend=-1, mom=1, macro=0, holding=False)

    assert decision["action"] == "TACTICAL REBOUND (counter-trend)"
    assert decision["flags"]["rebound"] == [
        "RSI turning from oversold (30\u219234)",
        "MACD histogram crossing bullishly",
        "price reclaims EMA20 (closed below 2 bars ago)",
        "fresh bullish TRIX cross below zero",
    ]
    assert decision["flags"]["death_cross"] is True
