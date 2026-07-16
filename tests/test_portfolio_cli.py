from __future__ import annotations

from pathlib import Path

from trading_desk.cli import main


def test_portfolio_create_and_replay_are_local_only(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    events = tmp_path / "events.json"
    assert (
        main(
            [
                "portfolio",
                "create",
                "--timestamp",
                "2026-07-15T12:00:00+00:00",
                "--output",
                str(events),
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    assert "Mode: PAPER" in output
    assert "Execution: SIMULATED ONLY" in output
    assert "Broker connectivity: DISABLED" in output
    assert "Live trading: DISABLED" in output
    assert events.exists()
    assert main(["portfolio", "replay", "--events", str(events)]) == 0
    assert "Open positions: 0" in capsys.readouterr().out


def test_portfolio_cli_rejects_naive_timestamp_without_loading_broker(
    tmp_path: Path, capsys
) -> None:  # type: ignore[no-untyped-def]
    result = main(
        [
            "portfolio",
            "create",
            "--timestamp",
            "2026-07-15T12:00:00",
            "--output",
            str(tmp_path / "events.json"),
        ]
    )
    assert result == 2
    captured = capsys.readouterr()
    assert "Mode: PAPER" in captured.out
    assert "timezone-aware UTC" in captured.err
