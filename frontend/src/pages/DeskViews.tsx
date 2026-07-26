import { Metric, Panel } from "../components/Panel";
import { useOperations } from "../hooks/useOperations";

/* ------------------------------------------------------------ shared */

function Spark({ values }: { values: number[] }) {
  if (values.length < 2)
    return <div className="state">Curve appears after two data points.</div>;
  const min = Math.min(...values, 0);
  const max = Math.max(...values, 0);
  const span = max - min || 1;
  const width = 640;
  const height = 110;
  const pts = values
    .map((v, i) => {
      const x = (i / (values.length - 1)) * (width - 8) + 4;
      const y = height - 8 - ((v - min) / span) * (height - 16);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  const zeroY = height - 8 - ((0 - min) / span) * (height - 16);
  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className="sparkline"
      role="img"
      aria-label="Cumulative curve"
      style={{ width: "100%", height: "auto" }}
    >
      <line
        x1="4"
        x2={width - 4}
        y1={zeroY}
        y2={zeroY}
        stroke="rgba(148,163,184,0.25)"
        strokeDasharray="4 4"
      />
      <polyline points={pts} fill="none" strokeWidth="2" />
    </svg>
  );
}

function pct(value: number | null | undefined, digits = 1): string {
  return value === null || value === undefined
    ? "–"
    : `${(value * 100).toFixed(digits)}%`;
}

/* ------------------------------------------------------- desk overview */

interface DeskOps {
  equity: number | null;
  last_session: string | null;
  open_positions: number | null;
  sessions_recorded: number;
  held_news_exits_total: number;
  rejections_by_session: Record<string, number>;
  jobs: { job: string; last_output: string | null }[];
  disk_free_gb: number;
  disk_used_pct: number;
}

export function DeskOverview() {
  const state = useOperations<DeskOps>("/api/v1/ops/desk");
  if (state.loading) return <div className="state">Reading the desk...</div>;
  if (state.error || !state.data)
    return <div className="state state-error">Desk unavailable: {state.error}</div>;
  const d = state.data;
  return (
    <>
      <div className="metrics">
        <Metric
          label="Equity"
          value={d.equity === null ? "–" : `$${d.equity.toFixed(2)}`}
        />
        <Metric label="Open positions" value={String(d.open_positions ?? "–")} />
        <Metric label="Last session" value={d.last_session ?? "none"} />
        <Metric label="Sessions recorded" value={String(d.sessions_recorded)} />
        <Metric
          label="Disk"
          value={`${d.disk_used_pct.toFixed(0)}% (${d.disk_free_gb} GB free)`}
        />
      </div>
      <Panel title="Nightly jobs" meta="last output per job (UTC)">
        <div className="health-grid">
          {d.jobs.map((j) => (
            <div className="health-row" key={j.job}>
              <div>
                <strong>{j.job}</strong>
                <small>{j.last_output ?? "never ran on this machine"}</small>
              </div>
              <span className={j.last_output ? "status status-healthy" : "status"}>
                {j.last_output ? "active" : "waiting"}
              </span>
            </div>
          ))}
        </div>
      </Panel>
      <Panel
        title="News gate activity"
        meta={`${d.held_news_exits_total} held-position news exits so far`}
      >
        {Object.keys(d.rejections_by_session).length === 0 ? (
          <div className="state">No rejections recorded yet.</div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Session</th>
                <th>Entries blocked by news gate</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(d.rejections_by_session)
                .reverse()
                .map(([session, count]) => (
                  <tr key={session}>
                    <td>{session}</td>
                    <td>{count}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        )}
      </Panel>
    </>
  );
}

/* ---------------------------------------------------------- positions */

interface PositionRow {
  symbol: string;
  side: string;
  quantity: number;
  entry: number;
  mark: number | null;
  pnl: number | null;
  pnl_pct: number | null;
  confidence: number | null;
  target_r: number | null;
}

interface PositionsDoc {
  available: boolean;
  reason?: string;
  marked_at?: string | null;
  winners: number;
  losers: number;
  long_pnl: number;
  short_pnl: number;
  positions: PositionRow[];
}

export function PositionsBook() {
  const state = useOperations<PositionsDoc>("/api/v1/equity-paper/positions");
  if (state.loading) return <div className="state">Loading the book...</div>;
  if (state.error || !state.data)
    return <div className="state state-error">Data unavailable: {state.error}</div>;
  const d = state.data;
  if (!d.available)
    return <div className="state">No paper positions on this machine. ({d.reason})</div>;
  return (
    <>
      <div className="metrics">
        <Metric label="Winning" value={String(d.winners)} />
        <Metric label="Losing" value={String(d.losers)} />
        <Metric
          label="Long book P&L"
          value={
            <span className={d.long_pnl >= 0 ? "pos" : "neg"}>
              {d.long_pnl >= 0 ? "+" : ""}
              {d.long_pnl.toFixed(2)}
            </span>
          }
        />
        <Metric
          label="Short book P&L"
          value={
            <span className={d.short_pnl >= 0 ? "pos" : "neg"}>
              {d.short_pnl >= 0 ? "+" : ""}
              {d.short_pnl.toFixed(2)}
            </span>
          }
        />
      </div>
      <Panel
        title="Open positions"
        meta={d.marked_at ? `marks: ${d.marked_at}` : "marks pending (cron)"}
      >
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Side</th>
                <th>Entry</th>
                <th>Mark</th>
                <th>P&L $</th>
                <th>P&L %</th>
                <th>Confidence</th>
              </tr>
            </thead>
            <tbody>
              {d.positions.map((r) => (
                <tr key={r.symbol}>
                  <td>{r.symbol}</td>
                  <td>{r.side}</td>
                  <td>{r.entry.toFixed(2)}</td>
                  <td>{r.mark === null ? "–" : r.mark.toFixed(2)}</td>
                  <td className={(r.pnl ?? 0) >= 0 ? "pos" : "neg"}>
                    {r.pnl === null ? "–" : r.pnl.toFixed(2)}
                  </td>
                  <td className={(r.pnl_pct ?? 0) >= 0 ? "pos" : "neg"}>
                    {pct(r.pnl_pct)}
                  </td>
                  <td>
                    {r.confidence === null || r.confidence === undefined
                      ? "pre-CWK"
                      : `${pct(r.confidence, 0)} → ${r.target_r?.toFixed(1)}R`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </>
  );
}

/* ----------------------------------------------------------- evidence */

interface ShadowStream {
  name: string;
  n: number;
  cumulative: number;
  latest: { date: string; net: number; cum: number } | null;
  points: { date: string; net: number; cum: number }[];
}

export function EvidenceStreams() {
  const state = useOperations<{ decision_date: string; streams: ShadowStream[] }>(
    "/api/v1/evidence/shadow",
  );
  if (state.loading) return <div className="state">Loading evidence...</div>;
  if (state.error || !state.data)
    return <div className="state state-error">Data unavailable: {state.error}</div>;
  return (
    <>
      <div className="notice">
        Forward out-of-sample evidence accrues nightly; the prop-challenge
        verdict is scheduled for {state.data.decision_date}.
      </div>
      {state.data.streams.map((s) => (
        <Panel
          key={s.name}
          title={s.name}
          meta={`${s.n} trading days | cumulative ${pct(s.cumulative, 2)}`}
        >
          {s.n === 0 ? (
            <div className="state">No rows yet.</div>
          ) : (
            <Spark values={s.points.map((p) => p.cum)} />
          )}
        </Panel>
      ))}
    </>
  );
}

/* ----------------------------------------------------------- research */

export function ResearchBoard() {
  const state = useOperations<{
    decision_date: string;
    fee_plan: string;
    status: string;
    documents: Record<string, Record<string, unknown>>;
  }>("/api/v1/research/challenge");
  if (state.loading) return <div className="state">Loading research...</div>;
  if (state.error || !state.data)
    return <div className="state state-error">Data unavailable: {state.error}</div>;
  const d = state.data;
  const names = Object.keys(d.documents);
  return (
    <>
      <div className="metrics">
        <Metric label="Status" value={d.status} />
        <Metric label="Decision date" value={d.decision_date} />
      </div>
      <div className="notice">{d.fee_plan}</div>
      {names.length === 0 ? (
        <div className="state">
          Research result files not present on this machine.
        </div>
      ) : (
        names.map((name) => (
          <Panel key={name} title={name.replaceAll("_", " ")}>
            <div className="detail-grid">
              {Object.entries(d.documents[name])
                .filter(([, v]) => typeof v !== "object" || v === null)
                .map(([k, v]) => (
                  <span key={k}>
                    {k.replaceAll("_", " ")} <b>{String(v)}</b>
                  </span>
                ))}
            </div>
          </Panel>
        ))
      )}
    </>
  );
}

/* ------------------------------------------------------------ journal */

interface JournalRow {
  type: string;
  session?: string;
  symbol?: string;
  [key: string]: unknown;
}

export function PaperJournal() {
  const state = useOperations<{ rows: JournalRow[] }>(
    "/api/v1/equity-paper/journal?limit=80",
  );
  if (state.loading) return <div className="state">Loading journal...</div>;
  if (state.error || !state.data)
    return <div className="state state-error">Data unavailable: {state.error}</div>;
  const describe = (r: JournalRow): string => {
    if (r.type === "session")
      return `equity $${Number(r.equity).toFixed(2)} | ${String(r.positions)} positions | ${String(r.entries_approved)} entries approved`;
    if (r.type === "fill")
      return `${String(r.direction)} ${String(r.symbol)} @ ${Number(r.price).toFixed(2)}`;
    if (r.type === "rejection")
      return `${String(r.symbol)} blocked: ${(r.codes as string[] | undefined)?.join(", ") ?? ""}`;
    if (r.type === "held_news_exit")
      return `${String(r.symbol)} exited on held-news BLOCK`;
    if (r.type === "confidence_report") return "confidence calibration updated";
    return JSON.stringify(r).slice(0, 90);
  };
  return (
    <Panel title="Paper journal" meta="newest first">
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Session</th>
              <th>Type</th>
              <th>Detail</th>
            </tr>
          </thead>
          <tbody>
            {state.data.rows.map((r, i) => (
              <tr key={i}>
                <td>{r.session ?? ""}</td>
                <td>{r.type}</td>
                <td>{describe(r)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}
