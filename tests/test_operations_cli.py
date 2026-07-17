from pathlib import Path

from trading_desk.cli import main


def test_operations_cli_refuses_remote_binding(capsys) -> None:  # type: ignore[no-untyped-def]
    result = main(
        [
            "operations",
            "run",
            "--host",
            "0.0.0.0",
            "--journal",
            "journal.db",
        ]
    )
    output = capsys.readouterr()
    assert result == 2
    assert "remote Operations Center binding is prohibited" in output.err
    assert "Environment: IG DEMO" in output.out
    assert "Authority: READ ONLY" in output.out


def test_operations_cli_starts_loopback_read_only_server(
    tmp_path: Path, monkeypatch, capsys
) -> None:  # type: ignore[no-untyped-def]
    called: dict[str, object] = {}

    def fake_run(application: object, *, host: str, port: int, log_level: str) -> None:
        called.update(application=application, host=host, port=port, log_level=log_level)

    monkeypatch.setattr("uvicorn.run", fake_run)
    result = main(
        [
            "operations",
            "run",
            "--journal",
            str(tmp_path / "journal.db"),
        ]
    )
    output = capsys.readouterr().out
    assert result == 0
    assert called["host"] == "127.0.0.1"
    assert called["port"] == 8000
    assert "Broker mutation: DISABLED" in output
    assert "Risk mutation: DISABLED" in output
    assert "Portfolio mutation: DISABLED" in output
    assert "Live trading: DISABLED" in output
