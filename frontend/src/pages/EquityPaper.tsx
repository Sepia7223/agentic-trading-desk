import { Metric, Panel } from "../components/Panel";
import { useOperations } from "../hooks/useOperations";

interface EquityPaperSession {
  session: string;
  equity: number;
  positions: number;
  entries_approved: number;
  exits_queued: number;
  target_exits: number;
  entries_rejected: Record<string, number>;
  gross_target: string;
}

interface ConfidenceBucket {
  bucket: string;
  n: number;
  win_rate: number;
  expectancy_r: number;
  payoff_ratio: number;
}

interface OpenConfidence {
  confidence: number;
  bucket: string;
  target_r: number;
  multiplier?: number;
  opened?: string;
}

interface EquityPaperSummary {
  available: boolean;
  reason?: string;
  environment?: string;
  authority?: string;
  last_session?: string;
  equity?: number;
  positions?: number;
  gross_target?: string;
  sessions?: EquityPaperSession[];
  confidence_buckets?: ConfidenceBucket[];
  open_position_confidence?: Record<string, OpenConfidence>;
}

function EquityCurve({ sessions }: { sessions: EquityPaperSession[] }) {
  if (sessions.length < 2)
    return <div className="state">Curve appears after two sessions.</div>;
  const values = sessions.map((s) => s.equity);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const width = 640;
  const height = 120;
  const points = values
    .map((v, i) => {
      const x = (i / (values.length - 1)) * (width - 8) + 4;
      const y = height - 8 - ((v - min) / span) * (height - 16);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label="Equity curve"
      style={{ width: "100%", height: "auto" }}
    >
      <polyline
        points={points}
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
      />
    </svg>
  );
}

export function EquityPaperMonitor() {
  const state = useOperations<EquityPaperSummary>(
    "/api/v1/equity-paper/summary",
  );
  if (state.loading)
    return <div className="state">Loading equity paper account...</div>;
  if (state.error || !state.data)
    return (
      <div className="state state-error">Data unavailable: {state.error}</div>
    );
  const data = state.data;
  if (!data.available)
    return (
      <div className="state">
        Equity paper journal not found on this host. It is written by the
        mini PC nightly session and published to the repository; pull the
        branch or set EQUITY_PAPER_DIR. ({data.reason})
      </div>
    );
  const sessions = data.sessions ?? [];
  const buckets = data.confidence_buckets ?? [];
  const openConf = Object.entries(data.open_position_confidence ?? {}).sort(
    (a, b) => b[1].confidence - a[1].confidence,
  );
  const first = sessions[0]?.equity ?? 0;
  const last = data.equity ?? 0;
  const change = first > 0 ? ((last - first) / first) * 100 : 0;
  return (
    <>
      <div className="metrics">
        <Metric label="Equity" value={`$${last.toFixed(2)}`} />
        <Metric
          label="Since start"
          value={`${change >= 0 ? "+" : ""}${change.toFixed(2)}%`}
        />
        <Metric label="Positions" value={String(data.positions ?? 0)} />
        <Metric label="Last session" value={data.last_session ?? "n/a"} />
        <Metric label="Gross target" value={data.gross_target ?? "n/a"} />
      </div>
      <Panel title="Equity curve" meta={data.environment}>
        <EquityCurve sessions={sessions} />
      </Panel>
      <Panel
        title="Confidence calibration"
        meta="how often each confidence bucket actually works (closed trades)"
      >
        {buckets.length === 0 ? (
          <div className="state">
            No closed confidence-era trades yet; the table grows as trades
            complete.
          </div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Bucket</th>
                <th>Trades</th>
                <th>Win rate</th>
                <th>Expectancy (R)</th>
                <th>Payoff</th>
              </tr>
            </thead>
            <tbody>
              {buckets.map((b) => (
                <tr key={b.bucket}>
                  <td>{b.bucket}</td>
                  <td>{b.n}</td>
                  <td>{(b.win_rate * 100).toFixed(1)}%</td>
                  <td>{b.expectancy_r.toFixed(2)}</td>
                  <td>{b.payoff_ratio.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>
      <Panel
        title="Open positions by confidence"
        meta={`${openConf.length} confidence-era open positions`}
      >
        {openConf.length === 0 ? (
          <div className="state">No confidence-era open positions yet.</div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Confidence</th>
                <th>Bucket</th>
                <th>Target R</th>
                <th>Opened</th>
              </tr>
            </thead>
            <tbody>
              {openConf.slice(0, 20).map(([symbol, c]) => (
                <tr key={symbol}>
                  <td>{symbol}</td>
                  <td>{(c.confidence * 100).toFixed(0)}%</td>
                  <td>{c.bucket}</td>
                  <td>{c.target_r.toFixed(2)}</td>
                  <td>{c.opened ?? "n/a"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>
      <Panel title="Sessions" meta={`${sessions.length} sessions`}>
        <table>
          <thead>
            <tr>
              <th>Session</th>
              <th>Equity</th>
              <th>Positions</th>
              <th>Entries</th>
              <th>Exits (at target)</th>
              <th>Rejected</th>
            </tr>
          </thead>
          <tbody>
            {[...sessions].reverse().map((s) => (
              <tr key={s.session}>
                <td>{s.session}</td>
                <td>${s.equity.toFixed(2)}</td>
                <td>{s.positions}</td>
                <td>{s.entries_approved}</td>
                <td>
                  {s.exits_queued} ({s.target_exits ?? 0})
                </td>
                <td>
                  {Object.values(s.entries_rejected ?? {}).reduce(
                    (a, b) => a + b,
                    0,
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </>
  );
}
