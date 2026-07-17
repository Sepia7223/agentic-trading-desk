"""Deterministic no-trade reconstruction across linked journal stages."""

from trading_desk.journal.models import JournalRecordType
from trading_desk.operations.fingerprints import fingerprint
from trading_desk.operations.lineage import connected_records
from trading_desk.operations.models import RecordProjection, WhyNoTradeProjection

_SEED_TYPES = {
    JournalRecordType.SCHEDULER_CYCLE.value,
    JournalRecordType.CAPITAL_PRESERVATION_DECISION.value,
    JournalRecordType.STRATEGY_SIGNAL.value,
    JournalRecordType.STRATEGY_REJECTION.value,
}
_REASON_STAGE_ORDER = (
    JournalRecordType.MARKET_CONTEXT.value,
    JournalRecordType.EVENT_CONTEXT.value,
    JournalRecordType.ROUTER_DECISION.value,
    JournalRecordType.CAPITAL_PRESERVATION_DECISION.value,
    JournalRecordType.STRATEGY_REJECTION.value,
    JournalRecordType.STRATEGY_SIGNAL.value,
    JournalRecordType.RISK_DECISION.value,
    JournalRecordType.EXECUTION_PREFLIGHT.value,
    JournalRecordType.EXECUTION_FAILURE.value,
)


def build_why_no_trade(
    records: tuple[RecordProjection, ...], limit: int
) -> tuple[WhyNoTradeProjection, ...]:
    scheduler = tuple(
        item for item in records if item.record_type == JournalRecordType.SCHEDULER_CYCLE.value
    )
    seeds = scheduler or tuple(item for item in records if item.record_type in _SEED_TYPES)
    results: dict[tuple[str, ...], WhyNoTradeProjection] = {}
    for seed in seeds:
        linked = connected_records(seed, records)
        identity = tuple(sorted(item.source_record_id for item in linked))
        if identity in results or _submitted(linked):
            continue
        result = _projection(seed, linked)
        results[identity] = result
    return tuple(
        sorted(results.values(), key=lambda item: item.evaluation_timestamp, reverse=True)[:limit]
    )


def _projection(
    seed: RecordProjection, linked: tuple[RecordProjection, ...]
) -> WhyNoTradeProjection:
    context = _latest(linked, JournalRecordType.MARKET_CONTEXT)
    session_record = _latest(linked, JournalRecordType.SESSION_CLASSIFICATION)
    router = _latest(linked, JournalRecordType.ROUTER_DECISION)
    capital = _latest(linked, JournalRecordType.CAPITAL_PRESERVATION_DECISION)
    strategy = _latest(linked, JournalRecordType.STRATEGY_SIGNAL) or _latest(
        linked, JournalRecordType.STRATEGY_REJECTION
    )
    risk = _latest(linked, JournalRecordType.RISK_DECISION)
    preflight = _latest(linked, JournalRecordType.EXECUTION_PREFLIGHT)
    reasons = _ordered_reasons(linked)
    passed = _ordered_gates(linked, passed=True)
    failed = _ordered_gates(linked, passed=False)
    primary = reasons[0] if reasons else failed[0] if failed else "NO_ORDER_REQUESTED"
    fields: dict[str, object] = {
        "evaluation_timestamp": seed.effective_at,
        "instrument": seed.instrument or _instrument(linked),
        "session": _value(session_record or context, "session", "session_name", "current_session"),
        "router_result": (
            _value(router, "status", "selected_strategy", "route")
            or ("CAPITAL_PRESERVATION" if capital else "NOT_SELECTED")
        ),
        "strategy_result": _value(strategy, "action", "status") or "NOT_EVALUATED",
        "risk_result": _value(risk, "status", "decision") or "NOT_EVALUATED",
        "preflight_result": _value(preflight, "status") or "NOT_EVALUATED",
        "final_action": "NO ORDER",
        "primary_reason": primary,
        "secondary_reasons": reasons[1:],
        "passed_gates": passed,
        "failed_gates": failed,
        "source_record_ids": tuple(item.source_record_id for item in linked),
    }
    return WhyNoTradeProjection(
        evaluation_timestamp=seed.effective_at,
        instrument=seed.instrument or _instrument(linked),
        session=_value(session_record or context, "session", "session_name", "current_session"),
        router_result=str(fields["router_result"]),
        strategy_result=str(fields["strategy_result"]),
        risk_result=str(fields["risk_result"]),
        preflight_result=str(fields["preflight_result"]),
        final_action="NO ORDER",
        primary_reason=primary,
        secondary_reasons=reasons[1:],
        passed_gates=passed,
        failed_gates=failed,
        source_record_ids=tuple(item.source_record_id for item in linked),
        projection_fingerprint=fingerprint(fields),
    )


def _submitted(records: tuple[RecordProjection, ...]) -> bool:
    for record in records:
        if record.record_type not in {
            JournalRecordType.BROKER_SUBMISSION.value,
            JournalRecordType.BROKER_CONFIRMATION.value,
        }:
            continue
        status = _value(record, "status", "confirmation_status")
        if status and status.upper() in {"SUBMITTED", "ACCEPTED", "CONFIRMED"}:
            return True
    return False


def _ordered_reasons(records: tuple[RecordProjection, ...]) -> tuple[str, ...]:
    found: list[str] = []
    for record_type in _REASON_STAGE_ORDER:
        for record in records:
            if record.record_type != record_type:
                continue
            for key in ("reason_codes", "rejection_reasons", "reasons"):
                _extend_unique(found, _strings(record.payload.get(key)))
    return tuple(found)


def _ordered_gates(records: tuple[RecordProjection, ...], *, passed: bool) -> tuple[str, ...]:
    found: list[str] = []
    for record in records:
        direct = record.payload.get("passed_gates" if passed else "failed_gates")
        _extend_unique(found, _strings(direct))
        gates = record.payload.get("mandatory_gates")
        if not isinstance(gates, (list, tuple)):
            continue
        for gate in gates:
            if not isinstance(gate, dict) or bool(gate.get("passed")) is not passed:
                continue
            _extend_unique(found, (str(gate.get("name") or gate.get("gate") or "UNKNOWN_GATE"),))
    return tuple(found)


def _latest(
    records: tuple[RecordProjection, ...], record_type: JournalRecordType
) -> RecordProjection | None:
    return next((item for item in reversed(records) if item.record_type == record_type.value), None)


def _value(record: RecordProjection | None, *keys: str) -> str | None:
    if record is None:
        return None
    for key in keys:
        value = record.payload.get(key)
        if value is not None:
            return str(value)
    return None


def _instrument(records: tuple[RecordProjection, ...]) -> str | None:
    return next((item.instrument for item in records if item.instrument), None)


def _strings(value: object | None) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value)
    return ()


def _extend_unique(target: list[str], values: tuple[str, ...]) -> None:
    target.extend(item for item in values if item not in target)
