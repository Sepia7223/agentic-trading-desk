import { Metric, Panel } from "../components/Panel";
import { StatusPill } from "../components/StatusPill";
import { useOperations } from "../hooks/useOperations";
import type {
  ExecutionLifecycles,
  HealthState,
  OpenPosition,
  OpenPositions,
  RecordProjection,
  SearchResult,
} from "../models/operations";

function value(payload: Record<string, unknown>, ...keys: string[]) {
  for (const key of keys)
    if (payload[key] !== undefined) return String(payload[key]);
  return "Unavailable";
}

function utc(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.valueOf())
    ? "Timestamp unavailable"
    : date.toISOString();
}

function RecordState({
  endpoint,
  children,
}: {
  endpoint: string;
  children: (record: RecordProjection) => React.ReactNode;
}) {
  const state = useOperations<RecordProjection>(endpoint);
  if (state.loading)
    return <div className="state">Loading current evidence...</div>;
  if (state.error || !state.data)
    return (
      <div className="state state-error">Data unavailable: {state.error}</div>
    );
  return <>{children(state.data)}</>;
}

export function MarketContext() {
  return (
    <RecordState endpoint="/api/v1/context/latest">
      {(record) => {
        const p = record.payload;
        return (
          <>
            <div className="metrics">
              <Metric
                label="Instrument"
                value={record.instrument ?? record.epic ?? "Unavailable"}
              />
              <Metric
                label="Context"
                value={value(p, "status", "context_status")}
              />
              <Metric
                label="Regime"
                value={value(p, "regime", "market_regime")}
              />
              <Metric
                label="Session"
                value={value(p, "session", "session_classification")}
              />
            </div>
            <Panel
              title="Authoritative market context"
              meta={utc(record.effective_at)}
            >
              <div className="detail-grid">
                <span>
                  HMM probability{" "}
                  <b>
                    {value(
                      p,
                      "regime_probability",
                      "selected_regime_probability",
                    )}
                  </b>
                </span>
                <span>
                  Regime uncertainty{" "}
                  <b>{value(p, "regime_uncertainty", "uncertainty")}</b>
                </span>
                <span>
                  Kalman slope <b>{value(p, "kalman_slope", "slope")}</b>
                </span>
                <span>
                  Volatility <b>{value(p, "volatility_state", "volatility")}</b>
                </span>
                <span>
                  Event state <b>{value(p, "event_state")}</b>
                </span>
                <span>
                  Staleness <b>{value(p, "stale", "data_status")}</b>
                </span>
              </div>
            </Panel>
          </>
        );
      }}
    </RecordState>
  );
}

export function RouterMonitor() {
  return (
    <RecordState endpoint="/api/v1/router/latest">
      {(record) => {
        const p = record.payload;
        return (
          <Panel
            title="Strategy routing decision"
            meta={utc(record.effective_at)}
          >
            <div className="notice">
              Research strategies: RESEARCH ONLY - EXECUTION PROHIBITED
            </div>
            <div className="detail-grid">
              <span>
                Selected strategy{" "}
                <b>{value(p, "selected_strategy", "strategy")}</b>
              </span>
              <span>
                Router result <b>{value(p, "status", "action", "decision")}</b>
              </span>
              <span>
                Executable <b>{value(p, "executable", "execution_eligible")}</b>
              </span>
              <span>
                Capital preservation <b>{value(p, "capital_preservation")}</b>
              </span>
              <span>
                Eligible variants <b>{value(p, "eligible_strategies")}</b>
              </span>
              <span>
                Reason codes <b>{value(p, "reason_codes")}</b>
              </span>
            </div>
          </Panel>
        );
      }}
    </RecordState>
  );
}

export function RiskMonitor() {
  return (
    <RecordState endpoint="/api/v1/risk/latest">
      {(record) => {
        const p = record.payload;
        return (
          <>
            <div className="metrics">
              <Metric label="Decision" value={value(p, "decision", "status")} />
              <Metric
                label="Approved quantity"
                value={value(p, "approved_quantity", "quantity")}
              />
              <Metric
                label="Open exposure"
                value={value(p, "portfolio_exposure", "gross_exposure")}
              />
              <Metric
                label="Daily loss"
                value={value(p, "daily_loss", "daily_pnl")}
              />
            </div>
            <Panel title="Deterministic risk gates">
              <div className="gate-list">
                {(Array.isArray(p.gates)
                  ? p.gates
                  : Array.isArray(p.reason_codes)
                    ? p.reason_codes
                    : ["No gate evidence available"]
                ).map((gate) => (
                  <span key={JSON.stringify(gate)}>
                    {typeof gate === "string" ? gate : JSON.stringify(gate)}
                  </span>
                ))}
              </div>
            </Panel>
          </>
        );
      }}
    </RecordState>
  );
}

export function ExecutionMonitor() {
  const state = useOperations<ExecutionLifecycles>("/api/v1/execution");
  if (state.loading)
    return <div className="state">Loading execution evidence...</div>;
  if (state.error || !state.data)
    return (
      <div className="state state-error">
        Execution evidence unavailable: {state.error}
      </div>
    );
  return (
    <Panel
      title="Execution lifecycle"
      meta={`${state.data.total_matches} joined requests`}
    >
      {state.data.lifecycles.length === 0 ? (
        <div className="empty">No execution lifecycle recorded.</div>
      ) : (
        <div className="lifecycle-list">
          {state.data.lifecycles.map((item) => (
            <article className="lifecycle" key={item.execution_request_id}>
              <header>
                <strong>
                  {item.instrument ?? item.epic ?? "Unknown instrument"}
                </strong>
                <span>{item.reconciliation_status}</span>
              </header>
              <p>
                {item.direction ?? "Unknown direction"} / quantity{" "}
                {item.submitted_quantity ??
                  item.approved_quantity ??
                  "Unavailable"}{" "}
                / deal {item.safely_truncated_deal_reference ?? "Unavailable"}
              </p>
              <ol>
                {item.stages.map((stage) => (
                  <li key={stage.source_record_id}>
                    <b>{stage.stage}</b>
                    <span>{stage.status}</span>
                    <time>{new Date(stage.timestamp).toISOString()}</time>
                  </li>
                ))}
              </ol>
              {item.discrepancies.length > 0 && (
                <div className="state-error">
                  Discrepancies: {item.discrepancies.join(", ")}
                </div>
              )}
            </article>
          ))}
        </div>
      )}
    </Panel>
  );
}

function PositionTable({ positions }: { positions: OpenPosition[] }) {
  if (!positions.length)
    return <div className="empty">No reconstructed open positions.</div>;
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Instrument</th>
            <th>Direction</th>
            <th>Quantity</th>
            <th>Entry</th>
            <th>Mark</th>
            <th>Unrealized P&amp;L</th>
            <th>Evidence</th>
          </tr>
        </thead>
        <tbody>
          {positions.map((position) => (
            <tr key={position.position_id}>
              <td>{position.instrument ?? position.epic ?? "Unavailable"}</td>
              <td>{position.direction ?? "Unavailable"}</td>
              <td>{position.quantity ?? "Unavailable"}</td>
              <td>{position.entry_price ?? "Unavailable"}</td>
              <td>{position.current_mark ?? "Unavailable"}</td>
              <td>{position.unrealized_pnl ?? "Unavailable"}</td>
              <td>{position.evidence_status}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function PositionsMonitor() {
  const state = useOperations<OpenPositions>("/api/v1/positions/open");
  if (state.loading)
    return <div className="state">Reconstructing positions...</div>;
  if (state.error || !state.data)
    return (
      <div className="state state-error">
        Positions unavailable: {state.error}
      </div>
    );
  return (
    <div className="split-panels">
      <Panel title="Paper positions" meta={state.data.paper_source}>
        <PositionTable positions={state.data.paper} />
      </Panel>
      <Panel title="IG Demo positions" meta={state.data.demo_source}>
        <PositionTable positions={state.data.demo} />
      </Panel>
    </div>
  );
}

export function TradesMonitor() {
  const state = useOperations<SearchResult>("/api/v1/trades");
  if (state.loading)
    return <div className="state">Loading closed trades...</div>;
  if (state.error || !state.data)
    return (
      <div className="state state-error">Trades unavailable: {state.error}</div>
    );
  return (
    <Panel
      title="Closed trade ledger"
      meta={`${state.data.total_matches} records`}
    >
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Closed UTC</th>
              <th>Instrument</th>
              <th>Strategy</th>
              <th>Net P&amp;L</th>
              <th>Exit reason</th>
              <th>Evidence ID</th>
            </tr>
          </thead>
          <tbody>
            {state.data.records.map((trade) => (
              <tr key={trade.source_record_id}>
                <td>{new Date(trade.effective_at).toISOString()}</td>
                <td>{trade.instrument ?? trade.epic ?? "Unavailable"}</td>
                <td>{trade.strategy_variant ?? "Unavailable"}</td>
                <td>{value(trade.payload, "net_pnl")}</td>
                <td>{value(trade.payload, "exit_reason", "reason")}</td>
                <td className="mono">{trade.source_record_id.slice(0, 12)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}

export function AlertsMonitor() {
  const state = useOperations<
    Array<{
      alert_id: string;
      severity: string;
      title: string;
      description: string;
      status: string;
      reason_codes: string[];
    }>
  >("/api/v1/alerts");
  if (state.loading) return <div className="state">Loading alerts...</div>;
  if (state.error)
    return (
      <div className="state state-error">Alerts unavailable: {state.error}</div>
    );
  return (
    <Panel
      title="Operational alerts"
      meta={`${state.data?.length ?? 0} findings`}
    >
      <div className="alert-list">
        {state.data?.map((alert) => (
          <article
            className={`alert severity-${alert.severity.toLowerCase()}`}
            key={alert.alert_id}
          >
            <header>
              <b>{alert.title}</b>
              <span>
                {alert.severity} / {alert.status}
              </span>
            </header>
            <p>{alert.description}</p>
            <small>{alert.reason_codes.join(", ")}</small>
          </article>
        ))}
        {state.data?.length === 0 && (
          <div className="empty">No active alerts.</div>
        )}
      </div>
    </Panel>
  );
}

export function JournalMonitor() {
  const state = useOperations<HealthState>("/api/v1/journal/status");
  if (state.loading)
    return <div className="state">Loading journal health...</div>;
  if (state.error || !state.data)
    return (
      <div className="state state-error">
        Journal status unavailable: {state.error}
      </div>
    );
  return (
    <>
      <div className="metrics">
        <Metric
          label="Status"
          value={<StatusPill status={state.data.status} />}
        />
        <Metric
          label="Heartbeat age"
          value={
            state.data.heartbeat_age_seconds !== undefined
              ? `${state.data.heartbeat_age_seconds}s`
              : "Unavailable"
          }
        />
        <Metric label="Findings" value={state.data.reason_codes.length} />
        <Metric label="Authority" value="READ ONLY" />
      </div>
      <Panel title="Journal integrity evidence">
        <div className="detail-grid">
          {Object.entries(state.data.safe_details).map(([key, detail]) => (
            <span key={key}>
              {key}
              <b>{String(detail)}</b>
            </span>
          ))}
        </div>
      </Panel>
    </>
  );
}

export function AIReviews() {
  const state = useOperations<SearchResult>("/api/v1/ai-reviews");
  if (state.loading)
    return <div className="state">Loading advisory reviews...</div>;
  if (state.error || !state.data)
    return (
      <div className="state state-error">
        AI reviews unavailable: {state.error}
      </div>
    );
  return (
    <Panel title="AI analyst reviews" meta="ADVISORY ONLY">
      <div className="notice">
        AI authority: ADVISORY ONLY - no strategy, risk, or execution authority
      </div>
      {state.data.records.length === 0 ? (
        <div className="empty">No advisory review evidence.</div>
      ) : (
        <div className="decision-list">
          {state.data.records.map((record) => (
            <article className="decision" key={record.source_record_id}>
              <div className="decision-head">
                <time>{new Date(record.effective_at).toISOString()}</time>
                <strong>ADVISORY</strong>
              </div>
              <h3>{record.instrument ?? record.epic ?? "Portfolio review"}</h3>
              <p>
                {value(record.payload, "summary", "recommendation", "status")}
              </p>
            </article>
          ))}
        </div>
      )}
    </Panel>
  );
}
