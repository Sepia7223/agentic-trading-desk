from pathlib import Path

from trading_desk.journal.models import JournalRecordType

ROOT = Path(__file__).parents[1]


def test_context_router_scheduler_have_no_execution_ai_or_secret_authority() -> None:
    forbidden = (
        "trading_desk.execution",
        "trading_desk.broker",
        "OPENAI_API_KEY",
        "IG_PASSWORD",
        "X-SECURITY-TOKEN",
        "place_order",
        "create_order",
    )
    for package in ("context", "router", "scheduler"):
        text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (ROOT / "src" / "trading_desk" / package).glob("*.py")
        )
        assert all(value not in text for value in forbidden)


def test_market_context_journal_record_types_are_available() -> None:
    expected = {
        "SCHEDULER_CYCLE",
        "MARKET_CONTEXT",
        "SESSION_CLASSIFICATION",
        "EVENT_CONTEXT",
        "ROUTER_DECISION",
        "STRATEGY_ELIGIBILITY",
        "RESEARCH_STRATEGY_RESULT",
        "CAPITAL_PRESERVATION_DECISION",
    }
    assert expected <= {item.value for item in JournalRecordType}
