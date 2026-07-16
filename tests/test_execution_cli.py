from __future__ import annotations

from trading_desk.cli import build_parser, main


def test_execution_cli_has_no_close_amend_or_working_order_command() -> None:
    parser = build_parser()
    help_text = parser.format_help()
    assert "execution" in help_text
    execution_action = next(
        action
        for action in parser._actions
        if action.dest == "command"  # noqa: SLF001
    )
    execution_parser = execution_action.choices["execution"]  # type: ignore[attr-defined]
    execution_help = execution_parser.format_help()
    assert "close" not in execution_help
    assert "amend" not in execution_help
    assert "working-order" not in execution_help


def test_execution_command_is_disabled_before_config_or_network_access(
    capsys,
) -> None:  # type: ignore[no-untyped-def]
    exit_code = main(["execution", "confirm", "--deal-reference", "public-ref"])
    captured = capsys.readouterr()
    assert exit_code == 2
    assert "Environment: IG DEMO" in captured.out
    assert "Mode: CONTROLLED EXECUTION" in captured.out
    assert "Live trading: DISABLED" in captured.out
    assert "Automatic execution: DISABLED" in captured.out
    assert "Operator confirmation: REQUIRED" in captured.out
    assert "explicit --enable-execution" in captured.err
