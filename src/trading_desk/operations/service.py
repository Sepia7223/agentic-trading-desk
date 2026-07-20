"""Journal-first read-only Operations Center application service."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from trading_desk.journal.models import JournalQuery, JournalRecordType
from trading_desk.operations.alerts import derive_alerts
from trading_desk.operations.analytics_views import build_portfolio_analytics
from trading_desk.operations.certification_views import build_certification_status
from trading_desk.operations.config import OperationsConfiguration
from trading_desk.operations.decision_trace import build_why_no_trade
from trading_desk.operations.execution_views import build_execution_lifecycles
from trading_desk.operations.fingerprints import fingerprint
from trading_desk.operations.health import aggregate_status, unknown_health
from trading_desk.operations.models import (
    ExecutionLifecyclesProjection,
    OpenPositionsProjection,
    OperationsSnapshot,
    PerformanceSummary,
    RecordProjection,
    RuntimeSubsystemHealth,
    SearchResult,
    SystemStatus,
    WhyNoTradeProjection,
)
from trading_desk.operations.performance import build_performance
from trading_desk.operations.ports import JournalHealthReader, RuntimeStateReader
from trading_desk.operations.position_views import build_open_positions
from trading_desk.operations.projections import project_record, sanitize_mapping
from trading_desk.operations.queries import bounded_query
from trading_desk.operations.replay import build_replay
from trading_desk.router.registry import StrategyRegistry

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
        return build_why_no_trade(self.all_records(), limit)

    def execution_lifecycles(
        self, *, limit: int = 100, offset: int = 0
    ) -> ExecutionLifecyclesProjection:
        if limit > self.configuration.maximum_query_records:
            raise ValueError("query limit exceeds Operations Center maximum")
        lifecycles = build_execution_lifecycles(self.all_records())
        page = lifecycles[offset : offset + limit]
        next_offset = offset + limit if offset + limit < len(lifecycles) else None
        return ExecutionLifecyclesProjection(
            lifecycles=page,
            total_matches=len(lifecycles),
            next_offset=next_offset,
        )

    def open_positions(self, observed_at: datetime | None = None) -> OpenPositionsProjection:
        now = _utc(observed_at or datetime.now(UTC))
        records = self.all_records()
        return build_open_positions(records, build_execution_lifecycles(records), now)

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

    def evidence_chain(self, source_record_id: str) -> tuple[RecordProjection, ...]:
        records = self.all_records()
        seed = next((item for item in records if item.source_record_id == source_record_id), None)
        if seed is None:
            return self.lineage(source_record_id)
        from trading_desk.operations.lineage import connected_records

        return connected_records(seed, records)

    def all_records(self) -> tuple[RecordProjection, ...]:
        maximum = self.configuration.maximum_replay_records
        records: list[RecordProjection] = []
        offset = 0
        while len(records) < maximum:
            page_size = min(maximum - len(records), self.configuration.maximum_query_records)
            page = self.records(limit=page_size, offset=offset)
            records.extend(page.records)
            if page.next_offset is None:
                break
            offset = page.next_offset
        return tuple(records)

    def performance(self, *, limit: int = 500) -> PerformanceSummary:
        records = self.records(
            record_type=JournalRecordType.PAPER_CLOSED_TRADE, limit=limit
        ).records
        return build_performance(records, self.latest(JournalRecordType.PAPER_PORTFOLIO_EVENT))

    def strategy_validation_matrix(self) -> dict[str, object]:
        strategies = StrategyRegistry().strategies
        return {
            "authority": "READ_ONLY",
            "strategies": [
                {
                    "strategy": item.strategy_id,
                    "version": item.strategy_version,
                    "validation_state": item.validation_status.value,
                    "supported_instruments": item.supported_instruments,
                    "supported_timeframes": tuple(
                        value.value for value in item.supported_timeframes
                    ),
                    "supported_regimes": tuple(value.value for value in item.eligible_trend_states),
                    "validation_report": item.validation_report_id,
                    "dataset_fingerprint": item.validation_dataset_fingerprint,
                    "promotion_timestamp": item.promotion_timestamp,
                    "promotion_authority": item.promotion_authority,
                    "failed_gates": ()
                    if item.validation_report_id
                    else ("VALIDATION_EVIDENCE_INCOMPLETE",),
                }
                for item in strategies
            ],
        }

    def strategy_regime_matrix(self) -> dict[str, object]:
        return {
            "authority": "READ_ONLY",
            "strategies": [
                {
                    "strategy": item.strategy_id,
                    "eligible_trends": tuple(value.value for value in item.eligible_trend_states),
                    "eligible_volatility": tuple(
                        value.value for value in item.eligible_volatility_states
                    ),
                    "eligible_events": tuple(value.value for value in item.eligible_event_states),
                }
                for item in StrategyRegistry().strategies
            ],
        }

    def strategy_comparison(self) -> dict[str, object]:
        performance = self.performance()
        return {
            "authority": "READ_ONLY",
            "performance": tuple(item.model_dump(mode="json") for item in performance.by_strategy),
            "validation_events": sum(
                1
                for item in self.all_records()
                if item.record_type
                in {
                    JournalRecordType.STRATEGY_VALIDATION_COMPLETED.value,
                    JournalRecordType.STRATEGY_WALK_FORWARD_COMPLETED.value,
                    JournalRecordType.STRATEGY_COST_STRESS_COMPLETED.value,
                }
            ),
        }

    def strategy_portfolio_contribution(self) -> dict[str, object]:
        records = self.all_records()
        events = tuple(
            item
            for item in records
            if item.record_type == JournalRecordType.STRATEGY_PORTFOLIO_TEST_COMPLETED.value
        )
        return {"authority": "READ_ONLY", "records": events, "total_matches": len(events)}

    def strategy_circuit_breakers(self) -> dict[str, object]:
        types = {
            JournalRecordType.STRATEGY_CIRCUIT_BREAKER_TRIGGERED.value,
            JournalRecordType.STRATEGY_CIRCUIT_BREAKER_CLEARED.value,
        }
        records = tuple(item for item in self.all_records() if item.record_type in types)
        return {"authority": "READ_ONLY", "records": records, "total_matches": len(records)}

    def portfolio_allocation(self) -> dict[str, object]:
        """Read-only projection of journaled portfolio batches and decisions."""

        batch_type = JournalRecordType.PORTFOLIO_BATCH_EVALUATED.value
        decision_type = JournalRecordType.PORTFOLIO_DECISION_CREATED.value
        records = tuple(
            item for item in self.all_records() if item.record_type in {batch_type, decision_type}
        )
        decisions = tuple(item for item in records if item.record_type == decision_type)
        by_strategy: dict[str, int] = {}
        for item in decisions:
            name = item.strategy_variant or "unknown"
            by_strategy[name] = by_strategy.get(name, 0) + 1
        return {
            "authority": "READ_ONLY",
            "batches_evaluated": sum(1 for item in records if item.record_type == batch_type),
            "decisions_recorded": len(decisions),
            "decisions_by_strategy": dict(sorted(by_strategy.items())),
            "records": records,
            "total_matches": len(records),
        }

    def portfolio_analytics(self) -> dict[str, object]:
        """Deterministic read-only P&L attribution reconciled to authoritative trades."""

        records = self.all_records()
        closed = tuple(
            item
            for item in records
            if item.record_type == JournalRecordType.PAPER_CLOSED_TRADE.value
        )
        funnel_records = tuple(
            item
            for item in records
            if item.record_type
            in {
                JournalRecordType.OPPORTUNITY_CANDIDATE_CREATED.value,
                JournalRecordType.STRATEGY_EVALUATED.value,
                JournalRecordType.OPPORTUNITY_SELECTED.value,
                JournalRecordType.OPPORTUNITY_EXECUTION_APPROVED.value,
            }
        )

        def _count(record_type: JournalRecordType) -> int:
            return sum(1 for item in records if item.record_type == record_type.value)

        funnel_counts = {
            "discovered": _count(JournalRecordType.OPPORTUNITY_CANDIDATE_CREATED),
            "evaluated": _count(JournalRecordType.STRATEGY_EVALUATED),
            "selected": _count(JournalRecordType.OPPORTUNITY_SELECTED),
            "execution_approved": _count(JournalRecordType.OPPORTUNITY_EXECUTION_APPROVED),
            "executed": _count(JournalRecordType.OPPORTUNITY_EXECUTION_APPROVED),
            "closed": len(closed),
            "system_halts": _count(JournalRecordType.DEMO_CAMPAIGN_HALTED),
        }
        rejection_counts = {
            "CONTEXT_OR_EVENT": _reason_count(records, ("CONTEXT", "EVENT", "HOLIDAY")),
            "STRATEGY_OR_REGIME": _reason_count(records, ("STRATEGY", "REGIME")),
            "STALE_DATA": _reason_count(records, ("STALE", "UNFINISHED")),
            "COST_OR_SPREAD": _reason_count(records, ("COST", "SPREAD")),
            "EXPECTED_VALUE": _reason_count(records, ("EXPECTED_VALUE",)),
            "RISK_REJECTED": _count(JournalRecordType.OPPORTUNITY_RISK_REJECTED),
            "CORRELATION": _count(JournalRecordType.OPPORTUNITY_CORRELATION_REJECTED),
            "EXECUTION_PREFLIGHT": _reason_count(records, ("PREFLIGHT",)),
        }
        return build_portfolio_analytics(closed, funnel_records, funnel_counts, rejection_counts)

    def certification_status(self) -> dict[str, object]:
        """Deterministic read-only IG Demo operational certification status."""

        return build_certification_status(self.all_records())

    def lifecycle(self, *, limit: int = 100, offset: int = 0) -> SearchResult:
        lifecycle_types = {
            JournalRecordType.POSITION_MONITOR_SNAPSHOT.value,
            JournalRecordType.EXIT_DECISION.value,
            JournalRecordType.EXIT_PREFLIGHT.value,
            JournalRecordType.CLOSE_REQUEST.value,
            JournalRecordType.CLOSE_SUBMISSION.value,
            JournalRecordType.CLOSE_CONFIRMATION.value,
            JournalRecordType.CLOSE_RECONCILIATION.value,
            JournalRecordType.POSITION_CLOSED.value,
            JournalRecordType.POSITION_CLOSE_BLOCKED.value,
            JournalRecordType.POSITION_LIFECYCLE_HALTED.value,
            JournalRecordType.POST_TRADE_REVIEW.value,
            JournalRecordType.PAPER_DEMO_EXIT_COMPARISON.value,
        }
        records = tuple(item for item in self.all_records() if item.record_type in lifecycle_types)
        page = records[offset : offset + limit]
        next_offset = offset + limit if offset + limit < len(records) else None
        return SearchResult(records=page, total_matches=len(records), next_offset=next_offset)

    def opportunity_records(self, *, limit: int = 100) -> SearchResult:
        types = {
            JournalRecordType.OPPORTUNITY_CANDIDATE_CREATED.value,
            JournalRecordType.OPPORTUNITY_REJECTED.value,
            JournalRecordType.OPPORTUNITY_SELECTED.value,
            JournalRecordType.OPPORTUNITY_RISK_REJECTED.value,
            JournalRecordType.OPPORTUNITY_EXECUTION_APPROVED.value,
        }
        records = tuple(item for item in self.all_records() if item.record_type in types)
        page = records[-limit:]
        return SearchResult(records=page, total_matches=len(records), next_offset=None)

    def opportunity_activity(self) -> dict[str, object]:
        records = self.all_records()
        counts = {
            name: sum(1 for item in records if item.record_type == record_type.value)
            for name, record_type in {
                "cycles": JournalRecordType.OPPORTUNITY_CYCLE_COMPLETED,
                "candidates": JournalRecordType.OPPORTUNITY_CANDIDATE_CREATED,
                "selected": JournalRecordType.OPPORTUNITY_SELECTED,
                "risk_rejections": JournalRecordType.OPPORTUNITY_RISK_REJECTED,
                "execution_approvals": JournalRecordType.OPPORTUNITY_EXECUTION_APPROVED,
            }.items()
        }
        evaluations = tuple(
            item
            for item in records
            if item.record_type == JournalRecordType.STRATEGY_EVALUATED.value
        )
        funnel = {
            "research_only_evaluations": sum(
                _safe_int(item.payload.get("research_only_evaluations")) for item in evaluations
            ),
            "demo_executable_evaluations": sum(
                _safe_int(item.payload.get("demo_executable_evaluations")) for item in evaluations
            ),
            "context_rejections": _reason_count(records, ("CONTEXT", "EVENT", "HOLIDAY")),
            "strategy_rejections": _reason_count(records, ("STRATEGY", "REGIME")),
            "stale_data_rejections": _reason_count(records, ("STALE", "UNFINISHED")),
            "cost_rejections": _reason_count(records, ("COST", "SPREAD")),
            "expected_value_rejections": _reason_count(records, ("EXPECTED_VALUE",)),
            "correlation_rejections": sum(
                1
                for item in records
                if item.record_type == JournalRecordType.OPPORTUNITY_CORRELATION_REJECTED.value
            ),
            "execution_preflight_rejections": _reason_count(records, ("PREFLIGHT",)),
            "system_halts": sum(
                1
                for item in records
                if item.record_type == JournalRecordType.DEMO_CAMPAIGN_HALTED.value
            ),
        }
        return {"environment": "DEMO", "authority": "READ ONLY", **counts, **funnel}

    def opportunity_breakdown(self, field: str) -> tuple[dict[str, object], ...]:
        counts: dict[str, int] = {}
        for record in self.opportunity_records(
            limit=self.configuration.maximum_replay_records
        ).records:
            value = record.payload.get(field)
            label = str(value) if value not in (None, "") else "UNKNOWN"
            counts[label] = counts.get(label, 0) + 1
        return tuple({"label": label, "records": count} for label, count in sorted(counts.items()))

    def inactivity_diagnostics(self, *, limit: int = 100) -> SearchResult:
        return self.records(
            record_type=JournalRecordType.INACTIVITY_DIAGNOSTIC_CREATED, limit=limit
        )

    def demo_campaign(self):  # type: ignore[no-untyped-def]
        halted = self.latest(JournalRecordType.DEMO_CAMPAIGN_HALTED)
        return (
            halted
            or self.latest(JournalRecordType.DEMO_CAMPAIGN_SNAPSHOT_CREATED)
            or self.latest(JournalRecordType.DEMO_CAMPAIGN_STARTED)
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


def _reason_count(records: tuple[RecordProjection, ...], markers: tuple[str, ...]) -> int:
    count = 0
    for record in records:
        values = _strings(record.payload.get("rejection_reasons")) + _strings(
            record.payload.get("rejection_codes")
        )
        if any(any(marker in value for marker in markers) for value in values):
            count += 1
    return count


def _safe_int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("operations timestamp must be timezone-aware")
    return value.astimezone(UTC)
