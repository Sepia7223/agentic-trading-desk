"""Strict immutable monitoring projections with no operational authority."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from trading_desk.operations.fingerprints import fingerprint


class OperationsModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


class SystemStatus(StrEnum):
    STARTING = "STARTING"
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    HALTED = "HALTED"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    STOPPED = "STOPPED"
    UNKNOWN = "UNKNOWN"


class AlertSeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class AlertStatus(StrEnum):
    ACTIVE = "ACTIVE"
    RESOLVED = "RESOLVED"


class OperationsEventType(StrEnum):
    SYSTEM_HEALTH_UPDATED = "SYSTEM_HEALTH_UPDATED"
    SCHEDULER_CYCLE_STARTED = "SCHEDULER_CYCLE_STARTED"
    SCHEDULER_CYCLE_COMPLETED = "SCHEDULER_CYCLE_COMPLETED"
    MARKET_CONTEXT_UPDATED = "MARKET_CONTEXT_UPDATED"
    ROUTER_DECISION_CREATED = "ROUTER_DECISION_CREATED"
    STRATEGY_RESULT_CREATED = "STRATEGY_RESULT_CREATED"
    RISK_DECISION_CREATED = "RISK_DECISION_CREATED"
    PORTFOLIO_UPDATED = "PORTFOLIO_UPDATED"
    EXECUTION_STATE_UPDATED = "EXECUTION_STATE_UPDATED"
    BROKER_CONFIRMATION_UPDATED = "BROKER_CONFIRMATION_UPDATED"
    RECONCILIATION_UPDATED = "RECONCILIATION_UPDATED"
    JOURNAL_STATUS_UPDATED = "JOURNAL_STATUS_UPDATED"
    ALERT_CREATED = "ALERT_CREATED"
    ALERT_UPDATED = "ALERT_UPDATED"
    AI_ANALYSIS_CREATED = "AI_ANALYSIS_CREATED"


class RuntimeSubsystemHealth(OperationsModel):
    name: str
    status: SystemStatus
    observed_at: datetime
    heartbeat_age_seconds: int | None = Field(default=None, ge=0)
    reason_codes: tuple[str, ...] = ()
    safe_details: dict[str, object] = Field(default_factory=dict)

    @field_validator("observed_at")
    @classmethod
    def utc_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("health timestamp must be timezone-aware")
        return value.astimezone(UTC)


class OperationsAlert(OperationsModel):
    alert_id: str = Field(min_length=64, max_length=64)
    severity: AlertSeverity
    category: str
    created_at: datetime
    status: AlertStatus = AlertStatus.ACTIVE
    title: str
    description: str
    source_record_ids: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    acknowledgment_state: str = "UNACKNOWLEDGED"
    alert_fingerprint: str = Field(min_length=64, max_length=64)

    @model_validator(mode="after")
    def identity(self) -> Self:
        fields = self.model_dump(mode="python", exclude={"alert_id", "alert_fingerprint"})
        expected = fingerprint(fields)
        if self.alert_id != expected or self.alert_fingerprint != expected:
            raise ValueError("alert fingerprint mismatch")
        return self


class RecordProjection(OperationsModel):
    journal_record_id: str
    source_record_id: str
    source_parent_ids: tuple[str, ...] = ()
    atomic_group_id: str | None = None
    record_type: str
    effective_at: datetime
    instrument: str | None = None
    epic: str | None = None
    strategy_variant: str | None = None
    environment: str
    payload: dict[str, object]
    record_fingerprint: str


class WhyNoTradeProjection(OperationsModel):
    evaluation_timestamp: datetime
    instrument: str | None
    session: str | None
    router_result: str
    strategy_result: str
    risk_result: str
    preflight_result: str
    final_action: str
    primary_reason: str
    secondary_reasons: tuple[str, ...]
    passed_gates: tuple[str, ...]
    failed_gates: tuple[str, ...]
    source_record_ids: tuple[str, ...]
    projection_fingerprint: str = Field(min_length=64, max_length=64)


class OpenPositionProjection(OperationsModel):
    position_id: str
    environment: str
    evidence_status: str
    instrument: str | None
    epic: str | None
    direction: str | None
    quantity: Decimal | None
    entry_timestamp: datetime | None
    entry_price: Decimal | None
    current_mark: Decimal | None
    stop_price: Decimal | None
    target_price: Decimal | None
    unrealized_pnl: Decimal | None
    realized_costs: Decimal | None
    funding: Decimal | None
    exposure: Decimal | None
    open_risk: Decimal | None
    duration_seconds: int | None = Field(default=None, ge=0)
    source_strategy: str | None
    risk_decision_id: str | None
    execution_id: str | None
    reconciliation_status: str | None
    source_record_ids: tuple[str, ...]
    projection_fingerprint: str = Field(min_length=64, max_length=64)


class OpenPositionsProjection(OperationsModel):
    generated_at: datetime
    paper: tuple[OpenPositionProjection, ...]
    demo: tuple[OpenPositionProjection, ...]
    paper_source: str
    demo_source: str
    projection_fingerprint: str = Field(min_length=64, max_length=64)


class ExecutionStageProjection(OperationsModel):
    stage: str
    status: str
    timestamp: datetime
    source_record_id: str
    reason_codes: tuple[str, ...] = ()
    safe_details: dict[str, object] = Field(default_factory=dict)


class ExecutionLifecycleProjection(OperationsModel):
    execution_request_id: str
    instrument: str | None
    epic: str | None
    direction: str | None
    approved_quantity: Decimal | None
    submitted_quantity: Decimal | None
    stop_price: Decimal | None
    target_price: Decimal | None
    safely_truncated_deal_reference: str | None
    confirmation_status: str
    confirmed_entry: Decimal | None
    confirmed_size: Decimal | None
    reconciliation_status: str
    discrepancies: tuple[str, ...]
    halt_status: str
    stages: tuple[ExecutionStageProjection, ...]
    source_record_ids: tuple[str, ...]
    lifecycle_fingerprint: str = Field(min_length=64, max_length=64)


class ExecutionLifecyclesProjection(OperationsModel):
    lifecycles: tuple[ExecutionLifecycleProjection, ...]
    total_matches: int = Field(ge=0)
    next_offset: int | None


class ReplayTimeline(OperationsModel):
    replay_mode: str = "REPLAY MODE - NO OPERATIONAL AUTHORITY"
    cutoff_at: datetime
    events: tuple[RecordProjection, ...]
    timeline_fingerprint: str = Field(min_length=64, max_length=64)


class PerformanceSummary(OperationsModel):
    sample_size: int = Field(ge=0)
    realized_pnl: Decimal
    total_costs: Decimal
    wins: int = Field(ge=0)
    losses: int = Field(ge=0)
    win_rate: Decimal | None
    profit_factor: Decimal | None
    expectancy: Decimal | None
    equity_curve: tuple[tuple[datetime, Decimal], ...]
    drawdown_curve: tuple[tuple[datetime, Decimal], ...]
    daily_pnl: tuple[tuple[str, Decimal], ...]
    unrealized_pnl: Decimal
    spread_costs: Decimal
    slippage_costs: Decimal
    commissions: Decimal
    funding: Decimal
    gross_exposure: Decimal
    turnover: Decimal
    payoff_ratio: Decimal | None
    by_instrument: tuple[PerformanceBreakdown, ...]
    by_strategy: tuple[PerformanceBreakdown, ...]
    by_regime: tuple[PerformanceBreakdown, ...]
    by_session: tuple[PerformanceBreakdown, ...]
    by_volatility_state: tuple[PerformanceBreakdown, ...]
    by_event_state: tuple[PerformanceBreakdown, ...]
    by_environment: tuple[PerformanceBreakdown, ...]


class PerformanceBreakdown(OperationsModel):
    label: str
    sample_size: int = Field(ge=0)
    net_pnl: Decimal
    wins: int = Field(ge=0)
    losses: int = Field(ge=0)
    win_rate: Decimal | None


class SearchResult(OperationsModel):
    records: tuple[RecordProjection, ...]
    total_matches: int = Field(ge=0)
    next_offset: int | None


class OperationsEvent(OperationsModel):
    event_id: str = Field(min_length=64, max_length=64)
    event_type: OperationsEventType
    created_at: datetime
    source_record_ids: tuple[str, ...] = ()
    payload: dict[str, object]
    event_fingerprint: str = Field(min_length=64, max_length=64)

    @model_validator(mode="after")
    def identity(self) -> Self:
        fields = self.model_dump(mode="python", exclude={"event_id", "event_fingerprint"})
        expected = fingerprint(fields)
        if self.event_id != expected or self.event_fingerprint != expected:
            raise ValueError("operations event fingerprint mismatch")
        return self


class OperationsSnapshot(OperationsModel):
    snapshot_id: str = Field(min_length=64, max_length=64)
    created_at: datetime
    environment: str
    application_version: str
    git_commit: str
    branch: str | None = None
    operations_configuration_fingerprint: str
    system_status: SystemStatus
    scheduler_status: RuntimeSubsystemHealth
    broker_status: RuntimeSubsystemHealth
    journal_status: RuntimeSubsystemHealth
    execution_status: RuntimeSubsystemHealth
    risk_status: RuntimeSubsystemHealth
    portfolio_status: RuntimeSubsystemHealth
    market_context_status: RuntimeSubsystemHealth
    router_status: RuntimeSubsystemHealth
    latest_alerts: tuple[OperationsAlert, ...]
    latest_cycle_id: str | None = None
    latest_context_id: str | None = None
    latest_router_decision_id: str | None = None
    latest_strategy_signal_id: str | None = None
    latest_risk_decision_id: str | None = None
    latest_execution_result_id: str | None = None
    snapshot_fingerprint: str = Field(min_length=64, max_length=64)

    @model_validator(mode="after")
    def identity(self) -> Self:
        fields = self.model_dump(mode="python", exclude={"snapshot_id", "snapshot_fingerprint"})
        expected = fingerprint(fields)
        if self.snapshot_id != expected or self.snapshot_fingerprint != expected:
            raise ValueError("operations snapshot fingerprint mismatch")
        return self
