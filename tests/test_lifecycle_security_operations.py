from pathlib import Path

from trading_desk.journal.models import JournalRecordType
from trading_desk.operations.models import OperationsEventType


def test_lifecycle_journal_and_operations_event_types_are_complete() -> None:
    required = {
        "POSITION_MONITOR_SNAPSHOT",
        "EXIT_DECISION",
        "EXIT_PREFLIGHT",
        "CLOSE_REQUEST",
        "CLOSE_SUBMISSION",
        "CLOSE_CONFIRMATION",
        "CLOSE_RECONCILIATION",
        "POSITION_CLOSED",
        "POSITION_CLOSE_BLOCKED",
        "POSITION_LIFECYCLE_HALTED",
        "POST_TRADE_REVIEW",
    }
    assert required <= {item.value for item in JournalRecordType}
    assert {
        "POSITION_MONITORED",
        "EXIT_DECISION_CREATED",
        "CLOSE_SUBMITTED",
        "POSITION_CLOSED",
        "POSITION_LIFECYCLE_HALTED",
    } <= {item.value for item in OperationsEventType}


def test_only_lifecycle_and_ig_adapter_import_close_mutation_port() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "trading_desk"
    offenders = []
    for path in root.rglob("*.py"):
        source = path.read_text(encoding="utf-8").lower()
        if "positionexitport" not in source and "position_exit import" not in source:
            continue
        relative = path.relative_to(root).as_posix()
        if not relative.startswith(("lifecycle/", "ports/", "ig/")):
            offenders.append(relative)
    assert offenders == []


def test_ai_dashboard_risk_strategy_journal_have_no_close_authority() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "trading_desk"
    for package in ("ai", "risk", "strategy", "journal", "operations", "api"):
        source = "\n".join(
            path.read_text(encoding="utf-8") for path in (root / package).rglob("*.py")
        ).lower()
        assert "submit_position_close" not in source
        assert "positionexitport" not in source


def test_lifecycle_has_no_secret_or_ai_dependencies() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "trading_desk" / "lifecycle"
    source = "\n".join(path.read_text(encoding="utf-8") for path in root.rglob("*.py")).lower()
    for forbidden in (
        "ig_password",
        "ig_api_key",
        "openai_api_key",
        "access_token",
        "refresh_token",
        "authorization",
        "trading_desk.ai",
    ):
        assert forbidden not in source
