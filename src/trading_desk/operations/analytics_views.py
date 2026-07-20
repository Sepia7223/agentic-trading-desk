"""Read-only analytics projections built from authoritative journal records.

Translates immutable closed-trade and opportunity records into the deterministic
analytics contracts (Milestone 14) and exposes them as plain read-only mappings.
Records whose gross/cost/net do not internally reconcile, or that lack the fields
required to attribute them, are excluded with an explicit reason rather than
being silently coerced — so every included number ties back to authoritative P&L.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from trading_desk.analytics import (
    DimensionName,
    FunnelTally,
    MeasureConvention,
    RejectionTally,
    TradeEvidence,
    build_funnel,
    build_scorecard,
)
from trading_desk.operations.models import RecordProjection

OPERATIONS_CONVENTION = MeasureConvention(returns_definition="account_currency_realized_pnl")

# Records must reconcile to this tolerance; tighter drift is a data-integrity fault.
_RECONCILIATION_TOLERANCE = Decimal("0.00000001")


def _decimal(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _timestamp(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def trade_evidence_from_record(
    record: RecordProjection,
) -> tuple[TradeEvidence | None, str | None]:
    """Reconstruct one closed trade as evidence, or explain why it cannot be."""

    payload = record.payload
    net_pnl = _decimal(payload.get("net_pnl"))
    if net_pnl is None:
        return None, "MISSING_NET_PNL"
    entry_at = _timestamp(payload.get("entry_timestamp"))
    exit_at = _timestamp(payload.get("exit_timestamp")) or record.effective_at
    if entry_at is None or exit_at is None or exit_at <= entry_at:
        return None, "INVALID_TRADE_WINDOW"

    commission = (
        (_decimal(payload.get("entry_commission")) or Decimal(0))
        + (_decimal(payload.get("exit_commission")) or Decimal(0))
    ) or (_decimal(payload.get("commission")) or Decimal(0))
    slippage = _decimal(payload.get("slippage_cost")) or Decimal(0)
    spread = (
        _decimal(payload.get("spread_cost")) or _decimal(payload.get("spread_costs")) or Decimal(0)
    )
    funding = (
        _decimal(payload.get("funding")) or _decimal(payload.get("accrued_funding")) or Decimal(0)
    )
    total_cost = commission + slippage + spread + funding
    if min(commission, slippage, spread, funding) < 0:
        return None, "NEGATIVE_COST_COMPONENT"

    gross = _decimal(payload.get("gross_pnl"))
    if gross is None:
        gross = net_pnl + total_cost
    elif abs(gross - total_cost - net_pnl) > _RECONCILIATION_TOLERANCE:
        return None, "PNL_DECOMPOSITION_INCONSISTENT"

    entry_price = _decimal(payload.get("entry_price"))
    quantity = _decimal(payload.get("quantity"))
    turnover = (
        abs(entry_price * quantity)
        if entry_price is not None and quantity is not None
        else Decimal(0)
    )

    evidence = TradeEvidence(
        trade_id=str(payload.get("trade_id") or record.source_record_id),
        source_record_ids=(record.source_record_id, *record.source_parent_ids),
        strategy_id=str(payload.get("strategy_variant") or record.strategy_variant or "UNKNOWN"),
        instrument=str(payload.get("instrument") or record.instrument or "UNKNOWN"),
        timeframe=str(payload.get("timeframe") or "UNKNOWN"),
        regime=str(payload.get("regime") or "UNKNOWN"),
        exit_reason=str(payload.get("exit_reason") or "UNKNOWN"),
        currency=OPERATIONS_CONVENTION.reporting_currency,
        entry_at=entry_at,
        exit_at=exit_at,
        gross_return=gross,
        spread_cost=spread,
        slippage_cost=slippage,
        commission_cost=commission,
        funding_cost=funding,
        turnover=turnover,
    )
    return evidence, None


def _attribution_waterfall(scorecard_dump: dict[str, object]) -> list[dict[str, object]]:
    slices = scorecard_dump.get("attribution", ())
    assert isinstance(slices, (list, tuple))
    ordered: list[dict[str, object]] = []
    for dimension in DimensionName:
        for item in slices:
            assert isinstance(item, dict)
            if item.get("dimension") == dimension.value:
                ordered.append(dict(item))
    return ordered


def build_portfolio_analytics(
    closed_trades: tuple[RecordProjection, ...],
    funnel_records: tuple[RecordProjection, ...],
    funnel_counts: dict[str, int],
    rejection_counts: dict[str, int],
) -> dict[str, object]:
    """Assemble the deterministic read-only portfolio-analytics projection."""

    evidence: list[TradeEvidence] = []
    excluded: list[dict[str, str]] = []
    authoritative_net = Decimal(0)
    for record in closed_trades:
        item, reason = trade_evidence_from_record(record)
        if item is None:
            assert reason is not None
            excluded.append({"source_record_id": record.source_record_id, "reason": reason})
        else:
            evidence.append(item)
            authoritative_net += item.net_return

    scorecard = build_scorecard(tuple(evidence), OPERATIONS_CONVENTION)
    scorecard_dump = scorecard.model_dump(mode="json")
    reported_net = scorecard.net_return.value
    reconciled_to_authoritative = (
        reported_net is not None
        and abs(reported_net - authoritative_net) <= _RECONCILIATION_TOLERANCE
    )

    rejections = tuple(
        RejectionTally(reason=reason, count=count)
        for reason, count in sorted(rejection_counts.items())
        if count > 0
    )
    tally = FunnelTally(
        discovered=funnel_counts.get("discovered", 0),
        evaluated=funnel_counts.get("evaluated", 0),
        selected=funnel_counts.get("selected", 0),
        execution_approved=funnel_counts.get("execution_approved", 0),
        executed=funnel_counts.get("executed", 0),
        closed=funnel_counts.get("closed", 0),
        rejections=rejections,
        system_halts=funnel_counts.get("system_halts", 0),
    )
    funnel = build_funnel(tally)

    return {
        "authority": "READ_ONLY",
        "convention": OPERATIONS_CONVENTION.model_dump(mode="json"),
        "convention_fingerprint": OPERATIONS_CONVENTION.fingerprint,
        "scorecard": scorecard_dump,
        "attribution_waterfall": _attribution_waterfall(scorecard_dump),
        "cost_analysis": scorecard_dump.get("costs"),
        "opportunity_funnel": funnel.model_dump(mode="json"),
        "reconciliation": {
            "authoritative_net_pnl": str(authoritative_net),
            "reported_net_pnl": None if reported_net is None else str(reported_net),
            "reconciled": reconciled_to_authoritative,
        },
        "completeness": {
            "closed_trade_records_seen": len(closed_trades),
            "closed_trades_included": len(evidence),
            "closed_trades_excluded": len(excluded),
            "exclusions": tuple(excluded),
            "funnel_records_seen": len(funnel_records),
            "currency_basis": "ACCOUNT_CURRENCY_UNIFORM",
        },
    }
