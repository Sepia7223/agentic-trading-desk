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
}
