import { useOperations } from "../hooks/useOperations";
import type { SearchResult } from "../models/operations";
import { EvidenceTable } from "../components/EvidenceTable";
import { Panel } from "../components/Panel";

export function OpportunityBoard() {
  const { data, error } = useOperations<SearchResult>("/api/v1/opportunities");
  return (
    <Panel title="Opportunity Board" meta={error ?? undefined}>
      <EvidenceTable result={data} />
    </Panel>
  );
}

function JsonView({ title, endpoint }: { title: string; endpoint: string }) {
  const { data, error } = useOperations<unknown>(endpoint);
  return (
    <Panel title={title} meta={error ?? undefined}>
      <pre>{data ? JSON.stringify(data, null, 2) : "Data unavailable"}</pre>
    </Panel>
  );
}

export const ActivityDashboard = () => (
  <JsonView title="Activity Dashboard" endpoint="/api/v1/activity" />
);
export const StrategyLeaderboard = () => (
  <JsonView
    title="Strategy Leaderboard"
    endpoint="/api/v1/strategy-leaderboard"
  />
);
export const InstrumentPerformance = () => (
  <JsonView
    title="Instrument Performance"
    endpoint="/api/v1/instrument-performance"
  />
);
export const RegimePerformance = () => (
  <JsonView title="Regime Performance" endpoint="/api/v1/regime-performance" />
);
export const InactivityDiagnostics = () => (
  <JsonView
    title="Inactivity Diagnostics"
    endpoint="/api/v1/inactivity-diagnostics"
  />
);
export const DemoCampaign = () => (
  <JsonView title="Demo Campaign" endpoint="/api/v1/demo-campaign" />
);
export const StrategyValidationMatrix = () => (
  <JsonView
    title="Strategy Validation Matrix"
    endpoint="/api/v1/strategies/validation-matrix"
  />
);
export const StrategyPerformanceComparison = () => (
  <JsonView
    title="Strategy Performance Comparison"
    endpoint="/api/v1/strategies/performance-comparison"
  />
);
export const StrategyRegimeMatrix = () => (
  <JsonView
    title="Strategy-Regime Matrix"
    endpoint="/api/v1/strategies/regime-matrix"
  />
);
export const StrategyPortfolioContribution = () => (
  <JsonView
    title="Portfolio Contribution"
    endpoint="/api/v1/strategies/portfolio-contribution"
  />
);
export const StrategyCircuitBreakers = () => (
  <JsonView
    title="Strategy Circuit Breakers"
    endpoint="/api/v1/strategies/circuit-breakers"
  />
);
