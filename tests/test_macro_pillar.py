from __future__ import annotations

from dataclasses import asdict

import pytest

from trading_desk.strategy import macro_pillar


def test_macro_pillar_regression_for_original_self_test_output() -> None:
    result = asdict(macro_pillar.score_macro(macro_pillar._synthetic()))

    assert result == {
        "as_of": "self-test",
        "composite": 0.65,
        "regime": "Broadening",
        "pillar_score": 2,
        "pillar_label": "Strongly favorable macro",
        "inflationary_flag": False,
        "spy_tlt_corr": -0.066,
        "components": [
            {
                "name": "Concentration (equal vs cap-weight)",
                "ratio": "RSP/SPY",
                "weight": 0.25,
                "signal": 1.0,
                "detail": "ratio above SMA200, SMA200 rising",
                "available": True,
            },
            {
                "name": "Yield Curve 10Y-2Y",
                "ratio": "10Y-2Y",
                "weight": 0.2,
                "signal": 0.0,
                "detail": "spread -0.06, steepening",
                "available": True,
            },
            {
                "name": "Credit (high-yield vs IG)",
                "ratio": "HYG/LQD",
                "weight": 0.15,
                "signal": 0.0,
                "detail": "ratio below SMA200, SMA200 rising",
                "available": True,
            },
            {
                "name": "Size factor (small vs large)",
                "ratio": "IWM/SPY",
                "weight": 0.15,
                "signal": 1.0,
                "detail": "ratio above SMA200, SMA200 rising",
                "available": True,
            },
            {
                "name": "Equity vs Bond (SPY/TLT)",
                "ratio": "SPY/TLT",
                "weight": 0.15,
                "signal": 1.0,
                "detail": "ratio above SMA200, SMA200 rising",
                "available": True,
            },
            {
                "name": "Sector rotation (cyclical vs defensive)",
                "ratio": "XLY/XLP",
                "weight": 0.1,
                "signal": 1.0,
                "detail": "ratio above SMA200, SMA200 rising",
                "available": True,
            },
        ],
        "notes": [],
    }


def test_macro_requires_at_least_one_available_component() -> None:
    with pytest.raises(ValueError, match="No components"):
        macro_pillar.score_macro({"series": {}})
