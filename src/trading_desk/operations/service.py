"""Journal-first read-only Operations Center application service."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from trading_desk.journal.models import JournalQuery, JournalRecordType
from trading_desk.operations.alerts import derive_alerts
from trading_desk.operations.config import OperationsConfiguration
from trading_desk.operations.fingerprints import fingerprint
from trading_desk.operations.health import aggregate_status, unknown_health
from trading_desk.operations.models import (
    OperationsSnapshot,
    PerformanceSummary,
    RecordProjection,
    RuntimeSubsystemHealth,
    SearchResult,
    SystemStatus,
    WhyNoTradeProjection,
)
from trading_desk.operations.ports import JournalHealthReader, RuntimeStateReader
from trading_desk.operations.projections import project_record, sanitize_mapping
from trading_desk.operations.queries import bounded_query
from trading_desk.operations.replay import build_replay

if TYPE_CHECKING:
    from trading_desk.operations.models import ReplayTimeline
    from trading_desk.operations.ports import OperationsJournalReader

_LATEST_TYPES = {
    "cycle": JournalRecordType.SCHEDULER_CYCLE,
    "context": JournalRecordType.MARKET_CONTEXT,
    "router": JournalRecordType.ROUTER_DECISION,
    "strategy": JournalRecordType.STRATEGY_SIGNAL,
    "risk": JournalRecordType.RISK_DECISION,
    "execution": JournalRecordType.EXECUTION_RECONCILIATION,
}


class OperationsService:
    def __init__(
        self,
        reader: OperationsJournalReader,
        configuration: OperationsConfiguration,
        *,
        runtime_reader: RuntimeStateReader | None = None,
        journal_health_reader: JournalHealthReader | None = None,
        application_version: str = "0.1.0",
        git_commit: str = "unknown",
        branch: str | None = None,
        safe_configurations: dict[str, object] | None = None,
    ) -> None:
        self.reader = reader
        self.configuration = configuration
        self.runtime_reader = runtime_reader
        self.journal_health_reader = journal_health_reader
        self.application_version = application_version
        self.git_commit = git_commit
        self.branch = branch
        self.safe_configurations = sanitize_mapping(safe_configurations or {})

    def snapshot(self, observed_at: datetime | None = None) -> OperationsSnapshot:
        now = _utc(observed_at or datetime.now(UTC))
        scheduler = self._runtime("scheduler", now)
        broker = self._runtime("broker", now)
        execution = self._runtime("execution", now)
        journal = (
            _sanitize_health(self.journal_health_reader.journal_state(now))
            if self.journal_health_reader
            else unknown_health("journal", now, "JOURNAL_STATUS_UNAVAILABLE")
        )
        latest = {name: self.latest(record_type) for name, record_type in _LATEST_TYPES.items()}
        context_health = _record_health("market_context", latest["context"], now)
        router_health = _record_health("router", latest["router"], now)
        risk_health = _record_health("risk", latest["risk"], now)
        portfolio_health = _record_health(
            "portfolio", self.latest(JournalRecordType.PAPER_PORTFOLIO_EVENT), now
        )
        states = (
            scheduler,
            broker,
            journal,
            execution,
            risk_health,
            portfolio_health,
            context_health,
            router_health,
        )
        alerts = derive_alerts(states, now)
        fields: dict[str, object] = {
            "created_at": now,
            "environment": self.configuration.environment,
            "application_version": self.application_version,
            "git_commit": self.git_commit,
            "branch": self.branch,
            "operations_configuration_fingerprint": (self.configuration.configuration_fingerprint),
            "system_status": aggregate_status(states),
            "scheduler_status": scheduler,
            "broker_status": broker,
            "journal_status": journal,
            "execution_status": execution,
            "risk_status": risk_health,
            "portfolio_status": portfolio_health,
            "market_context_status": context_health,
            "router_status": router_health,
            "latest_alerts": alerts,
            "latest_cycle_id": _source_id(latest["cycle"]),
            "latest_context_id": _source_id(latest["context"]),
            "latest_router_decision_id": _source_id(latest["router"]),
            "latest_strategy_signal_id": _source_id(latest["strategy"]),
            "latest_risk_decision_id": _source_id(latest["risk"]),
            "latest_execution_result_id": _source_id(latest["execution"]),
        }
        identity = fingerprint(fields)
        return OperationsSnapshot.model_validate(
            {**fields, "snapshot_id": identity, "snapshot_fingerprint": identity}
        )

    def latest(self, record_type: JournalRecordType) -> RecordProjection | None:
        first_page = self.reader.query(JournalQuery(record_type=record_type, limit=1))
        if first_page.total_matches == 0:
            return None
        final_page = self.reader.query(
            JournalQuery(
                record_type=record_type,
                limit=1,
                offset=first_page.total_matches - 1,
            )
        )
        return project_record(final_page.records[0]) if final_page.records else None

    def records(
        self,
        *,
        record_type: JournalRecordType | None = None,
        limit: int = 100,
        offset: int = 0,
        cutoff_at: datetime | None = None,
    ) -> SearchResult:
        query = bounded_query(
            limit=limit,
            offset=offset,
            maximum=self.configuration.maximum_query_records,
            cutoff_at=cutoff_at,
            record_type=record_type,
        )
        result = self.reader.query(query)
        return SearchResult(
            records=tuple(project_record(item) for item in result.records),
            total_matches=result.total_matches,
            next_offset=result.next_offset,
        )

    def evaluations(self, *, limit: int = 100, offset: int = 0) -> SearchResult:
        return self.records(
            record_type=JournalRecordType.SCHEDULER_CYCLE, limit=limit, offset=offset
        )

    def why_no_trade(self, *, limit: int = 100) -> tuple[WhyNoTradeProjection, ...]:
        records = self.records(
            limit=min(limit * 8, self.configuration.maximum_query_records)
        ).records
        signals = tuple(
            item
            for item in records
            if item.record_type
            in {JournalRecordType.STRATEGY_SIGNAL.value, JournalRecordType.STRATEGY_REJECTION.value}
        )[-limit:]
        projections: list[WhyNoTradeProjection] = []
        for signal in signals:
            payload = signal.payload
            reasons = _strings(payload.get("rejection_reasons") or payload.get("reason_codes"))
            failed = _gate_names(payload.get("mandatory_gates"), passed=False)
            passed = _gate_names(payload.get("mandatory_gates"), passed=True)
            primary = reasons[0] if reasons else failed[0] if failed else "NO_ORDER_REQUESTED"
            fields: dict[str, object] = {
                "evaluation_timestamp": signal.effective_at,
                "instrument": signal.instrument,
                "session": _optional_text(payload.get("session")),
                "router_result": _optional_text(payload.get("router_status")) or "UNKNOWN",
                "strategy_result": _optional_text(payload.get("action")) or "NO_TRADE",
                "risk_result": _optional_text(payload.get("risk_status")) or "NOT_EVALUATED",
                "preflight_result": _optional_text(payload.get("preflight_status"))
                or "NOT_EVALUATED",
                "final_action": "NO ORDER",
                "primary_reason": primary,
                "secondary_reasons": reasons[1:],
                "passed_gates": passed,
                "failed_gates": failed,
                "source_record_ids": (signal.source_record_id,),
            }
            projections.append(
                WhyNoTradeProjection(
                    evaluation_timestamp=signal.effective_at,
                    instrument=signal.instrument,
                    session=_optional_text(payload.get("session")),
                    router_result=_optional_text(payload.get("router_status")) or "UNKNOWN",
                    strategy_result=_optional_text(payload.get("action")) or "NO_TRADE",
                    risk_result=_optional_text(payload.get("risk_status")) or "NOT_EVALUATED",
                    preflight_result=(
                        _optional_text(payload.get("preflight_status")) or "NOT_EVALUATED"
                    ),
                    final_action="NO ORDER",
                    primary_reason=primary,
                    secondary_reasons=reasons[1:],
                    passed_gates=passed,
                    failed_gates=failed,
                    source_record_ids=(signal.source_record_id,),
                    projection_fingerprint=fingerprint(fields),
                )
            )
        return tuple(projections)

    def replay(self, *, cutoff_at: datetime, limit: int | None = None) -> ReplayTimeline:
        bounded = min(
            limit or self.configuration.maximum_replay_records,
            self.configuration.maximum_replay_records,
        )
        cutoff = _utc(cutoff_at)
        records: list[RecordProjection] = []
        offset = 0
        while len(records) < bounded:
            page_size = min(bounded - len(records), self.configuration.maximum_query_records)
            page = self.records(limit=page_size, offset=offset, cutoff_at=cutoff)
            records.extend(page.records)
            if page.next_offset is None:
                break
            offset = page.next_offset
        return build_replay(tuple(records), cutoff)

    def search(self, term: str, *, limit: int = 100, offset: int = 0) -> SearchResult:
        if not self.configuration.enable_search:
            raise ValueError("Operations Center search is disabled")
        needle = term.strip().lower()
        if not needle or len(needle) > 128:
            raise ValueError("search term is invalid")
        scan_limit = self.configuration.maximum_query_records
        source = self.records(limit=scan_limit).records
        matches = tuple(item for item in source if needle in item.model_dump_json().lower())
        page = matches[offset : offset + limit]
        next_offset = offset + limit if offset + limit < len(matches) else None
        return SearchResult(records=page, total_matches=len(matches), next_offset=next_offset)

    def lineage(self, source_record_id: str) -> tuple[RecordProjection, ...]:
        lineage = self.reader.lineage(source_record_id)
        return tuple(project_record(item) for item in lineage.records)

    def performance(self, *, limit: int = 500) -> PerformanceSummary:
        records = self.records(
            record_type=JournalRecordType.PAPER_CLOSED_TRADE, limit=limit
        ).records
        pnl_values = tuple(_decimal(item.payload.get("net_pnl")) for item in records)
        pnl = tuple(value for value in pnl_values if value is not None)
        costs = sum(
            (_decimal(item.payload.get("total_costs")) or Decimal("0") for item in records),
            Decimal("0"),
        )
        wins = tuple(value for value in pnl if value > 0)
        losses = tuple(value for value in pnl if value < 0)
        total = sum(pnl, Decimal("0"))
        curve: list[tuple[datetime, Decimal]] = []
        cumulative = Decimal("0")
        for record, value in zip(records, pnl_values, strict=True):
            cumulative += value or Decimal("0")
            curve.append((record.effective_at, cumulative))
        return PerformanceSummary(
            sample_size=len(pnl),
            realized_pnl=total,
            total_costs=costs,
            wins=len(wins),
            losses=len(losses),
            win_rate=(Decimal(len(wins)) / Decimal(len(pnl))) if pnl else None,
            profit_factor=(
                sum(wins, Decimal("0")) / abs(sum(losses, Decimal("0"))) if losses else None
            ),
            expectancy=(total / Decimal(len(pnl))) if pnl else None,
            equity_curve=tuple(curve),
        )

    def configuration_view(self) -> dict[str, object]:
        return {
            "environment": self.configuration.environment,
            "authority": "READ ONLY",
            "live_trading": "DISABLED",
            "operations": self.configuration.model_dump(
                mode="json", exclude={"frontend_directory"}
            ),
            "operations_fingerprint": self.configuration.configuration_fingerprint,
            "subsystems": self.safe_configurations,
        }

    def _runtime(self, name: str, observed_at: datetime) -> RuntimeSubsystemHealth:
        if self.runtime_reader is None:
            return unknown_health(name, observed_at, f"{name.upper()}_STATUS_UNAVAILABLE")
        readers = {
            "scheduler": self.runtime_reader.scheduler_state,
            "broker": self.runtime_reader.broker_state,
            "execution": self.runtime_reader.execution_state,
        }
        return _sanitize_health(readers[name](observed_at))


def _record_health(
    name: str, record: RecordProjection | None, observed_at: datetime
) -> RuntimeSubsystemHealth:
    if record is None:
        return unknown_health(name, observed_at, f"{name.upper()}_UNAVAILABLE")
    status = SystemStatus.HEALTHY
    reasons = _strings(record.payload.get("reason_codes"))
    if any("HALT" in item or "RECOVERY" in item for item in reasons):
        status = SystemStatus.HALTED
    elif any("STALE" in item or "UNAVAILABLE" in item for item in reasons):
        status = SystemStatus.DEGRADED
    return RuntimeSubsystemHealth(
        name=name,
        status=status,
        observed_at=observed_at,
        heartbeat_age_seconds=max(0, int((observed_at - record.effective_at).total_seconds())),
        reason_codes=reasons,
        safe_details={"source_record_id": record.source_record_id},
    )


def _source_id(record: RecordProjection | None) -> str | None:
    return record.source_record_id if record else None


def _sanitize_health(state: RuntimeSubsystemHealth) -> RuntimeSubsystemHealth:
    return state.model_copy(update={"safe_details": sanitize_mapping(state.safe_details)})


def _strings(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value)
    return ()


def _gate_names(value: object, *, passed: bool) -> tuple[str, ...]:
    if not isinstance(value, (tuple, list)):
        return ()
    result: list[str] = []
    for item in value:
        if not isinstance(item, dict) or bool(item.get("passed")) is not passed:
            continue
        result.append(str(item.get("name") or item.get("gate") or "UNKNOWN_GATE"))
    return tuple(result)


def _optional_text(value: object) -> str | None:
    return str(value) if value is not None else None


def _decimal(value: object) -> Decimal | None:
    try:
        return Decimal(str(value)) if value is not None else None
    except Exception:
        return None


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("operations timestamp must be timezone-aware")
    return value.astimezone(UTC)
