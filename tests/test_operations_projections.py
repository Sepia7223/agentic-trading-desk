from datetime import UTC, datetime, timedelta

from trading_desk.journal.models import JournalRecordType
from trading_desk.operations.decision_trace import build_why_no_trade
from trading_desk.operations.execution_views import build_execution_lifecycles
from trading_desk.operations.exports import OperationsExportFormat, export_records
from trading_desk.operations.models import RecordProjection
from trading_desk.operations.performance import build_performance
from trading_desk.operations.position_views import build_open_positions

NOW = datetime(2026, 7, 16, 12, tzinfo=UTC)


def record(
    source_id: str,
    record_type: JournalRecordType,
    payload: dict[str, object],
    *,
    parents: tuple[str, ...] = (),
    minutes: int = 0,
) -> RecordProjection:
    return RecordProjection(
        journal_record_id=f"journal-{source_id}",
        source_record_id=source_id,
        source_parent_ids=parents,
        record_type=record_type.value,
        effective_at=NOW + timedelta(minutes=minutes),
        instrument="EUR/USD",
        epic="CS.D.EURUSD.CFD.IP",
        strategy_variant="BASELINE_KALMAN_HMM",
        environment="DEMO",
        payload=payload,
        record_fingerprint="a" * 64,
    )


def test_why_no_trade_joins_complete_descendant_lineage() -> None:
    records = (
        record("cycle", JournalRecordType.SCHEDULER_CYCLE, {"status": "COMPLETED"}),
        record(
            "context",
            JournalRecordType.MARKET_CONTEXT,
            {"session": "LONDON", "reason_codes": ["CONTEXT_AVAILABLE"]},
            parents=("cycle",),
            minutes=1,
        ),
        record(
            "router",
            JournalRecordType.ROUTER_DECISION,
            {"selected_strategy": "TREND", "reason_codes": ["ROUTED"]},
            parents=("context",),
            minutes=2,
        ),
        record(
            "signal",
            JournalRecordType.STRATEGY_SIGNAL,
            {
                "action": "NO_TRADE",
                "rejection_reasons": ["MOMENTUM_THRESHOLD"],
                "mandatory_gates": [{"name": "MOMENTUM", "passed": False}],
            },
            parents=("router",),
            minutes=3,
        ),
    )
    result = build_why_no_trade(records, 10)
    assert len(result) == 1
    assert result[0].session == "LONDON"
    assert result[0].router_result == "TREND"
    assert result[0].primary_reason == "CONTEXT_AVAILABLE"
    assert result[0].secondary_reasons == ("ROUTED", "MOMENTUM_THRESHOLD")
    assert result[0].failed_gates == ("MOMENTUM",)
    assert result[0].source_record_ids == ("cycle", "context", "router", "signal")


def test_execution_projection_joins_and_redacts_complete_lifecycle() -> None:
    records = (
        record(
            "request",
            JournalRecordType.EXECUTION_REQUEST,
            {"execution_request_id": "request", "direction": "BUY", "approved_quantity": "1"},
        ),
        record(
            "preflight",
            JournalRecordType.EXECUTION_PREFLIGHT,
            {"status": "READY", "requested_quantity": "1"},
            parents=("request",),
            minutes=1,
        ),
        record(
            "submission",
            JournalRecordType.BROKER_SUBMISSION,
            {"status": "SUBMITTED", "deal_reference": "DEAL-REFERENCE-123456"},
            parents=("preflight",),
            minutes=2,
        ),
        record(
            "confirmation",
            JournalRecordType.BROKER_CONFIRMATION,
            {
                "confirmation_status": "ACCEPTED",
                "deal_reference": "DEAL-REFERENCE-123456",
                "executed_level": "1.085",
                "executed_size": "1",
            },
            parents=("submission",),
            minutes=3,
        ),
        record(
            "reconciliation",
            JournalRecordType.EXECUTION_RECONCILIATION,
            {"reconciliation_status": "RECONCILED", "discrepancies": []},
            parents=("confirmation",),
            minutes=4,
        ),
    )
    lifecycle = build_execution_lifecycles(records)[0]
    assert tuple(stage.stage for stage in lifecycle.stages) == (
        "EXECUTION REQUEST",
        "PREFLIGHT",
        "SUBMISSION",
        "BROKER CONFIRMATION",
        "RECONCILIATION",
    )
    assert lifecycle.confirmation_status == "ACCEPTED"
    assert lifecycle.reconciliation_status == "RECONCILED"
    assert lifecycle.safely_truncated_deal_reference == "***3456"
    assert "DEAL-REFERENCE" not in lifecycle.model_dump_json()


def test_open_positions_use_latest_paper_state_and_reconciled_demo_only() -> None:
    portfolio = record(
        "portfolio",
        JournalRecordType.PAPER_PORTFOLIO_EVENT,
        {
            "positions": [
                {
                    "position_id": "paper-open",
                    "status": "OPEN",
                    "direction": "LONG",
                    "quantity": "2",
                    "entry_price": "1.08",
                    "current_mark_price": "1.09",
                    "net_unrealized_pnl": "20",
                },
                {"position_id": "paper-closed", "status": "CLOSED"},
            ]
        },
    )
    execution_records = (
        record(
            "request",
            JournalRecordType.EXECUTION_REQUEST,
            {"execution_request_id": "request", "direction": "BUY", "approved_quantity": "1"},
        ),
        record(
            "confirmation",
            JournalRecordType.BROKER_CONFIRMATION,
            {"confirmation_status": "ACCEPTED", "executed_level": "1.08", "executed_size": "1"},
            parents=("request",),
            minutes=1,
        ),
        record(
            "reconciliation",
            JournalRecordType.EXECUTION_RECONCILIATION,
            {"reconciliation_status": "RECONCILED"},
            parents=("confirmation",),
            minutes=2,
        ),
    )
    result = build_open_positions(
        (portfolio, *execution_records), build_execution_lifecycles(execution_records), NOW
    )
    assert tuple(item.position_id for item in result.paper) == ("paper-open",)
    assert result.paper[0].unrealized_pnl == 20
    assert tuple(item.position_id for item in result.demo) == ("request",)
    assert result.demo[0].reconciliation_status == "RECONCILED"


def test_performance_contains_costs_drawdown_and_breakdowns() -> None:
    trades = (
        record(
            "win",
            JournalRecordType.PAPER_CLOSED_TRADE,
            {
                "net_pnl": "100",
                "quantity": "2",
                "entry_price": "10",
                "exit_price": "12",
                "commission": "2",
                "regime": "BULL_LOW_VOL",
                "session": "LONDON",
            },
        ),
        record(
            "loss",
            JournalRecordType.PAPER_CLOSED_TRADE,
            {
                "net_pnl": "-40",
                "quantity": "1",
                "entry_price": "12",
                "exit_price": "11",
                "spread_cost": "1",
                "regime": "TRANSITIONAL",
                "session": "NEW_YORK",
            },
            minutes=1,
        ),
    )
    portfolio = record(
        "portfolio",
        JournalRecordType.PAPER_PORTFOLIO_EVENT,
        {"gross_exposure": "500", "unrealized_pnl": "15"},
    )
    result = build_performance(trades, portfolio)
    assert result.realized_pnl == 60
    assert result.total_costs == 3
    assert result.drawdown_curve[-1][1] == -40
    assert result.unrealized_pnl == 15
    assert result.gross_exposure == 500
    assert result.turnover == 67
    assert {item.label for item in result.by_regime} == {"BULL_LOW_VOL", "TRANSITIONAL"}


def test_exports_are_bounded_projection_content_and_csv_safe() -> None:
    unsafe = record(
        "=formula",
        JournalRecordType.STRATEGY_SIGNAL,
        {"action": "NO_TRADE"},
    )
    csv_content, media_type, filename = export_records((unsafe,), OperationsExportFormat.CSV)
    assert "'=formula" in csv_content
    assert media_type.startswith("text/csv")
    assert filename.endswith(".csv")
    jsonl, _, _ = export_records((unsafe,), OperationsExportFormat.JSONL)
    assert f'"record_type":"{JournalRecordType.STRATEGY_SIGNAL.value}"' in jsonl
