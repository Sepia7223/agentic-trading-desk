from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError
from tests.backtest_helpers import configuration, dataset

from trading_desk.backtest.engine import BacktestEngine
from trading_desk.backtest.reports import export_json, export_markdown, export_trades_csv
from trading_desk.cli import main


def test_backtest_source_has_no_network_credentials_or_mutation_surface() -> None:
    root = Path(__file__).parents[1] / "src" / "trading_desk" / "backtest"
    source = "\n".join(path.read_text(encoding="utf-8") for path in root.glob("*.py"))
    prohibited = (
        "trading_desk.ig.client",
        "trading_desk.config",
        "httpx",
        "SecretStr",
        "Authorization",
        "IG_API_KEY",
        "IG_IDENTIFIER",
        "IG_PASSWORD",
        "OPENAI_API_KEY",
        "/positions/otc",
        "/working-orders/otc",
        "/workingorders/otc",
        "/confirms/",
        "place_order",
        "create_order",
        "execute_order",
        "close_position",
        "switch_account",
    )
    assert all(item not in source for item in prohibited)


def test_reports_and_models_contain_no_account_or_credential_fields() -> None:
    run = BacktestEngine(configuration()).run(dataset())
    serialized = run.model_dump_json()
    assert "account_id" not in serialized.lower()
    assert "password" not in serialized.lower()
    assert "api_key" not in serialized.lower()


def test_json_csv_and_markdown_reports_are_safe_local_outputs(tmp_path: Path) -> None:
    run = BacktestEngine(configuration()).run(dataset())
    targets = (tmp_path / "run.json", tmp_path / "trades.csv", tmp_path / "summary.md")
    export_json(run, targets[0])
    export_trades_csv(run, targets[1])
    export_markdown(run, targets[2])
    combined = "\n".join(path.read_text(encoding="utf-8") for path in targets)
    assert "password" not in combined.lower()
    assert "api_key" not in combined.lower()
    assert "proof of a profitable live strategy" in combined


def test_backtest_cli_bypasses_ig_configuration(tmp_path: Path, monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    source = tmp_path / "prices.csv"
    fields = (
        "epic,timestamp,open_bid,open_ask,high_bid,high_ask,low_bid,low_ask,"
        "close_bid,close_ask,last_traded_volume,market_status"
    )
    rows = [fields]
    data = dataset()
    for bar in data.bars:
        rows.append(
            ",".join(
                str(value)
                for value in (
                    bar.epic,
                    bar.timestamp.isoformat(),
                    bar.open_bid,
                    bar.open_ask,
                    bar.high_bid,
                    bar.high_ask,
                    bar.low_bid,
                    bar.low_ask,
                    bar.close_bid,
                    bar.close_ask,
                    bar.last_traded_volume,
                    bar.market_status,
                )
            )
        )
    source.write_text("\n".join(rows) + "\n", encoding="utf-8")
    monkeypatch.setattr(
        "trading_desk.cli.AppSettings.from_environment",
        lambda: (_ for _ in ()).throw(AssertionError("IG configuration was accessed")),
    )
    exit_code = main(
        [
            "backtest",
            "run",
            "--data",
            str(source),
            "--epic",
            data.bars[0].epic,
            "--variant",
            "BASELINE_ONLY",
            "--train-end",
            data.bars[219].timestamp.date().isoformat(),
            "--validation-end",
            data.bars[234].timestamp.date().isoformat(),
            "--test-end",
            data.bars[-1].timestamp.date().isoformat(),
        ]
    )
    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Mode: BACKTEST" in output
    assert "Execution: SIMULATED ONLY" in output
    assert "Live trading: DISABLED" in output


def test_local_path_does_not_change_run_fingerprint() -> None:
    data = dataset()
    first = configuration(dataset_source="C:/one/location/prices.csv")
    second = configuration(dataset_source="D:/different/location/prices.csv")
    assert (
        BacktestEngine(first).run(data).run_fingerprint
        == BacktestEngine(second).run(data).run_fingerprint
    )
    assert (
        BacktestEngine(first).run(data).run_fingerprint
        == BacktestEngine(first).run(data).run_fingerprint
    )


def test_live_execution_fields_are_rejected_by_immutable_configuration() -> None:
    values = configuration().model_dump()
    values["live_trading_allowed"] = True
    with pytest.raises(ValidationError):
        type(configuration()).model_validate(values)


def test_cost_split_and_data_changes_change_fingerprints() -> None:
    data = dataset()
    baseline = BacktestEngine(configuration()).run(data)
    costly = BacktestEngine(configuration(slippage_bps=3.0)).run(data)
    changed_split = configuration().model_copy(
        update={
            "splits": configuration().splits.model_copy(
                update={"validation_end": data.bars[233].timestamp}
            )
        }
    )
    split_run = BacktestEngine(changed_split).run(data)
    changed_data = dataset(251)
    changed_data_run = BacktestEngine(configuration(count=251)).run(changed_data)

    assert baseline.run_fingerprint != costly.run_fingerprint
    assert baseline.run_fingerprint != split_run.run_fingerprint
    assert baseline.run_fingerprint != changed_data_run.run_fingerprint
