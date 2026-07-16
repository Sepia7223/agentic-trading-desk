from __future__ import annotations

import pytest

from trading_desk.cli import main


@pytest.mark.parametrize(
    "arguments",
    [
        ("explain-signal", "--record-id", "signal-1"),
        ("explain-risk", "--decision-id", "decision-1"),
        ("review-trade", "--trade-id", "trade-1"),
        ("daily-review", "--date", "2026-07-15"),
        ("weekly-review", "--week", "2026-W29"),
        ("monthly-review", "--month", "2026-07"),
        ("historical-comparison", "--trade-id", "trade-1"),
    ],
)
def test_ai_cli_is_disabled_and_advisory_without_broker_configuration(
    arguments: tuple[str, str, str], capsys
) -> None:  # type: ignore[no-untyped-def]
    assert main(["ai", *arguments]) == 0
    output = capsys.readouterr().out
    assert "Mode: AI ANALYSIS" in output
    assert "Authority: ADVISORY ONLY" in output
    assert "Broker access: DISABLED" in output
    assert "Risk override: DISABLED" in output
    assert "Portfolio mutation: DISABLED" in output
    assert "Live trading: DISABLED" in output
    assert "Status: DISABLED" in output
