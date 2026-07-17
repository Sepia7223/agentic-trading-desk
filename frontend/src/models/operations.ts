export type Status =
  | "STARTING"
  | "HEALTHY"
  | "DEGRADED"
  | "HALTED"
  | "RECOVERY_REQUIRED"
  | "STOPPED"
  | "UNKNOWN";

export interface HealthState {
  name: string;
  status: Status;
  observed_at: string;
  heartbeat_age_seconds?: number;
  reason_codes: string[];
  safe_details: Record<string, unknown>;
}

export interface OperationsSnapshot {
  snapshot_id: string;
  created_at: string;
  environment: string;
  application_version: string;
  git_commit: string;
  branch?: string;
  system_status: Status;
  scheduler_status: HealthState;
  broker_status: HealthState;
  journal_status: HealthState;
  execution_status: HealthState;
  risk_status: HealthState;
  portfolio_status: HealthState;
  market_context_status: HealthState;
  router_status: HealthState;
  latest_alerts: unknown[];
}

export interface RecordProjection {
  journal_record_id: string;
  source_record_id: string;
  source_parent_ids: string[];
  atomic_group_id?: string;
  record_type: string;
  effective_at: string;
  instrument?: string;
  epic?: string;
  strategy_variant?: string;
  environment: string;
  payload: Record<string, unknown>;
  record_fingerprint: string;
}

export interface SearchResult {
  records: RecordProjection[];
  total_matches: number;
  next_offset?: number;
}

export interface WhyNoTrade {
  evaluation_timestamp: string;
  instrument?: string;
  session?: string;
  router_result: string;
  strategy_result: string;
  risk_result: string;
  preflight_result: string;
  final_action: string;
  primary_reason: string;
  secondary_reasons: string[];
  passed_gates: string[];
  failed_gates: string[];
}

export interface PerformanceSummary {
  sample_size: number;
  realized_pnl: string;
  total_costs: string;
  wins: number;
  losses: number;
  win_rate?: string;
  profit_factor?: string;
  expectancy?: string;
  equity_curve: [string, string][];
  drawdown_curve: [string, string][];
  daily_pnl: [string, string][];
  unrealized_pnl: string;
  spread_costs: string;
  slippage_costs: string;
  commissions: string;
  funding: string;
  gross_exposure: string;
  turnover: string;
  payoff_ratio?: string;
  by_instrument: PerformanceBreakdown[];
  by_strategy: PerformanceBreakdown[];
  by_regime: PerformanceBreakdown[];
  by_session: PerformanceBreakdown[];
  by_volatility_state: PerformanceBreakdown[];
  by_event_state: PerformanceBreakdown[];
  by_environment: PerformanceBreakdown[];
}

export interface PerformanceBreakdown {
  label: string;
  sample_size: number;
  net_pnl: string;
  wins: number;
  losses: number;
  win_rate?: string;
}

export interface OpenPosition {
  position_id: string;
  environment: string;
  evidence_status: string;
  instrument?: string;
  epic?: string;
  direction?: string;
  quantity?: string;
  entry_timestamp?: string;
  entry_price?: string;
  current_mark?: string;
  stop_price?: string;
  target_price?: string;
  unrealized_pnl?: string;
  realized_costs?: string;
  funding?: string;
  exposure?: string;
  open_risk?: string;
  duration_seconds?: number;
  reconciliation_status?: string;
}

export interface OpenPositions {
  generated_at: string;
  paper: OpenPosition[];
  demo: OpenPosition[];
  paper_source: string;
  demo_source: string;
}

export interface ExecutionStage {
  stage: string;
  status: string;
  timestamp: string;
  source_record_id: string;
  reason_codes: string[];
}

export interface ExecutionLifecycle {
  execution_request_id: string;
  instrument?: string;
  epic?: string;
  direction?: string;
  approved_quantity?: string;
  submitted_quantity?: string;
  safely_truncated_deal_reference?: string;
  confirmation_status: string;
  reconciliation_status: string;
  discrepancies: string[];
  halt_status: string;
  stages: ExecutionStage[];
}

export interface ExecutionLifecycles {
  lifecycles: ExecutionLifecycle[];
  total_matches: number;
  next_offset?: number;
}
