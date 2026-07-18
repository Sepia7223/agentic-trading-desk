from pathlib import Path

from trading_desk.execution.config import ExecutionMode


def test_opportunity_package_has_no_broker_http_or_secret_dependency() -> None:
    root = Path("src/trading_desk/opportunity")
    source = "\n".join(path.read_text(encoding="utf-8") for path in root.glob("*.py")).lower()
    forbidden = (
        "igdemoexecutionadapter",
        "igdemopositionexitadapter",
        "import httpx",
        "x-security-token",
        "access_token",
        "api_key",
        "random.",
        "martingale",
    )
    assert not [term for term in forbidden if term in source]


def test_exploration_mode_exists_without_live_or_short_support() -> None:
    assert ExecutionMode.DEMO_EXPLORATION.value == "DEMO_EXPLORATION"
    source = Path("src/trading_desk/opportunity/models.py").read_text(encoding="utf-8")
    assert 'LONG = "LONG"' in source
    assert 'SHORT = "SHORT"' not in source
