from __future__ import annotations

from decimal import Decimal

import pytest

from portfolio_helpers import approval, configured_portfolio, later
from risk_helpers import EPIC, NOW, candidate, market
from trading_desk.portfolio import replay, validate_event_chain
from trading_desk.portfolio.errors import LedgerValidationError
from trading_desk.portfolio.fingerprints import canonical_json
from trading_desk.portfolio.ledger import build_event
from trading_desk.portfolio.models import EventType
from trading_desk.risk import RiskEngine
from trading_desk.risk.models import AssetClass, RiskDecisionStatus


def test_event_sequences_fingerprints_and_replay_are_deterministic() -> None:
    portfolio = configured_portfolio()
    decision, trade_candidate, quote = approval(portfolio)
    opened = portfolio.open_position(decision, trade_candidate, quote, NOW)
    assert opened.position is not None
    portfolio.mark(
        quote.model_copy(
            update={"timestamp": later(), "bid": Decimal("101"), "ask": Decimal("101.1")}
        ),
        later(),
    )
    reconstructed = replay(portfolio.events)
    assert canonical_json(reconstructed) == canonical_json(portfolio.state)
    assert [event.sequence_number for event in portfolio.events] == list(
        range(1, len(portfolio.events) + 1)
    )
    assert validate_event_chain(portfolio.events) == portfolio.events


@pytest.mark.parametrize("mutation", ["sequence", "chain", "fingerprint"])
def test_corrupt_ledger_fails_closed(mutation: str) -> None:
    portfolio = configured_portfolio()
    events = list(portfolio.events)
    if mutation == "sequence":
        events[1] = events[1].model_copy(update={"sequence_number": 1})
    elif mutation == "chain":
        events[1] = events[1].model_copy(update={"previous_event_fingerprint": "f" * 64})
    else:
        events[1] = events[1].model_copy(update={"event_fingerprint": "f" * 64})
    with pytest.raises(LedgerValidationError):
        replay(events)


def test_unknown_position_and_double_close_events_are_rejected() -> None:
    empty = configured_portfolio()
    unknown = build_event(
        sequence_number=3,
        event_type=EventType.POSITION_MARKED,
        timestamp=NOW,
        portfolio_id=empty.state.portfolio_id,
        payload={"mark": "unknown"},
        previous_event_fingerprint=empty.events[-1].event_fingerprint,
        position_id="f" * 64,
    )
    with pytest.raises(LedgerValidationError, match="unknown position"):
        validate_event_chain(empty.events + (unknown,))

    portfolio = configured_portfolio()
    decision, trade_candidate, quote = approval(portfolio)
    result = portfolio.open_position(decision, trade_candidate, quote, NOW)
    assert result.position is not None
    portfolio.close_position(
        result.position.position_id, quote.model_copy(update={"timestamp": later()}), later()
    )
    closed = next(
        event for event in portfolio.events if event.event_type is EventType.POSITION_CLOSED
    )
    duplicate = build_event(
        sequence_number=len(portfolio.events) + 1,
        event_type=EventType.POSITION_CLOSED,
        timestamp=closed.timestamp,
        portfolio_id=closed.portfolio_id,
        payload={"duplicate": True},
        previous_event_fingerprint=portfolio.events[-1].event_fingerprint,
        position_id=closed.position_id,
        risk_decision_id=closed.risk_decision_id,
        candidate_id=closed.candidate_id,
    )
    with pytest.raises(LedgerValidationError, match="already closed"):
        validate_event_chain(portfolio.events + (duplicate,))


def test_account_risk_state_feedback_is_accepted_by_real_risk_engine() -> None:
    portfolio = configured_portfolio()
    state = portfolio.to_account_risk_state(
        required_epics=(EPIC,), required_asset_classes=(AssetClass.FOREX.value,)
    )
    assert state.snapshot_id == portfolio.state.snapshot_id
    assert state.account_equity == portfolio.state.equity
    assert state.open_position_count == 0
    next_candidate = candidate(candidate_id="next", signal_id="next-signal")
    decision = RiskEngine().evaluate(next_candidate, state, market(), NOW)
    assert decision.status is RiskDecisionStatus.APPROVED


def test_identical_inputs_produce_identical_events_and_trade_fingerprints() -> None:
    outputs: list[tuple[tuple[str, ...], str]] = []
    for _ in range(2):
        portfolio = configured_portfolio()
        decision, trade_candidate, quote = approval(portfolio)
        opened = portfolio.open_position(decision, trade_candidate, quote, NOW)
        assert opened.position is not None
        closed = portfolio.close_position(
            opened.position.position_id,
            quote.model_copy(
                update={"timestamp": later(), "bid": Decimal("105"), "ask": Decimal("105.1")}
            ),
            later(),
        )
        outputs.append(
            (
                tuple(event.event_fingerprint for event in portfolio.events),
                closed.trade.trade_fingerprint,
            )
        )
    assert outputs[0] == outputs[1]


def test_portfolio_package_has_no_forbidden_dependencies_or_operations() -> None:
    from pathlib import Path

    root = Path("src/trading_desk/portfolio")
    source = "\n".join(path.read_text(encoding="utf-8") for path in root.glob("*.py"))
    forbidden = (
        "httpx",
        "trading_desk.ig",
        "OPENAI_API_KEY",
        "X-SECURITY-TOKEN",
        "place_order",
        "create_order",
        "execute_order",
        "close_position/otc",
    )
    assert all(item not in source for item in forbidden)
