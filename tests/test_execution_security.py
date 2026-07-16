from __future__ import annotations

import inspect
from pathlib import Path

from trading_desk.ig.execution import IGDemoExecutionAdapter
from trading_desk.ports.broker import Broker

ROOT = Path(__file__).parents[1]


def test_read_only_broker_port_remains_without_mutation_methods() -> None:
    public = {
        name
        for name, member in inspect.getmembers(Broker, predicate=inspect.isfunction)
        if not name.startswith("_")
    }
    assert public == {"get_portfolio_state"}


def test_only_execution_and_ig_execution_packages_reference_mutation_surface() -> None:
    source_root = ROOT / "src" / "trading_desk"
    allowed = {
        source_root / "execution",
        source_root / "ig" / "execution.py",
        source_root / "ig" / "execution_policy.py",
        source_root / "ports" / "execution.py",
        source_root / "cli.py",
    }
    prohibited = ("/positions/otc", "submit_market_position", "get_deal_confirmation")
    offenders: list[str] = []
    for path in source_root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if any(value in text for value in prohibited) and not any(
            path == root or root in path.parents for root in allowed
        ):
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def test_strategy_risk_portfolio_and_ai_do_not_import_execution_or_ig() -> None:
    for package in ("strategy", "risk", "portfolio", "ai"):
        corpus = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (ROOT / "src" / "trading_desk" / package).glob("*.py")
        ).lower()
        assert "trading_desk.execution" not in corpus
        if package != "portfolio":
            assert "trading_desk.ig.execution" not in corpus


def test_execution_adapter_has_no_close_amend_working_order_or_switch_surface() -> None:
    public = {
        name
        for name, member in inspect.getmembers(IGDemoExecutionAdapter, predicate=inspect.isfunction)
        if not name.startswith("_")
    }
    forbidden = {
        "close_position",
        "amend_position",
        "create_working_order",
        "switch_account",
        "request",
    }
    assert public.isdisjoint(forbidden)


def test_no_live_host_or_secret_storage_in_execution_package() -> None:
    corpus = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "src" / "trading_desk" / "execution").glob("*.py")
    )
    assert "https://api.ig.com" not in corpus
    assert "SecretStr" not in corpus
    assert "OPENAI_API_KEY" not in corpus
    assert "IG_PASSWORD" not in corpus
    assert "Authorization" not in corpus
