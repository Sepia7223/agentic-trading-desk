import { Panel, Metric } from "../components/Panel";
import { StatusPill } from "../components/StatusPill";
import { useOperations } from "../hooks/useOperations";
import type { OperationsSnapshot } from "../models/operations";

export function Overview() {
  const { data, loading, error } =
    useOperations<OperationsSnapshot>("/api/v1/system");
  if (loading) return <div className="state">Loading system evidence...</div>;
  if (error || !data)
    return (
      <div className="state state-error">
        System evidence unavailable: {error}
      </div>
    );
  const states = [
    data.scheduler_status,
    data.broker_status,
    data.journal_status,
    data.execution_status,
    data.risk_status,
    data.portfolio_status,
    data.market_context_status,
    data.router_status,
  ];
  return (
    <>
      <div className="metrics">
        <Metric
          label="System"
          value={<StatusPill status={data.system_status} />}
        />
        <Metric label="Application" value={data.application_version} />
        <Metric
          label="Commit"
          value={<span className="mono">{data.git_commit.slice(0, 12)}</span>}
        />
        <Metric label="Alerts" value={data.latest_alerts.length} />
      </div>
      <Panel
        title="Subsystem health"
        meta={`Observed ${new Date(data.created_at).toISOString()}`}
      >
        <div className="health-grid">
          {states.map((item) => (
            <article className="health-row" key={item.name}>
              <div>
                <strong>{item.name}</strong>
                <small>{item.reason_codes.join(", ") || "No findings"}</small>
              </div>
              <StatusPill status={item.status} />
            </article>
          ))}
        </div>
      </Panel>
    </>
  );
}
