import ReactECharts from "echarts-for-react";

import { Metric, Panel } from "../components/Panel";
import { useOperations } from "../hooks/useOperations";
import type { PerformanceSummary } from "../models/operations";

export function Performance() {
  const state = useOperations<PerformanceSummary>("/api/v1/performance");
  if (state.loading)
    return <div className="state">Loading deterministic metrics...</div>;
  if (state.error || !state.data)
    return (
      <div className="state state-error">
        Metrics unavailable: {state.error}
      </div>
    );
  const data = state.data;
  const option = {
    backgroundColor: "transparent",
    textStyle: { color: "#aeb8c6" },
    grid: { left: 48, right: 20, top: 24, bottom: 36 },
    xAxis: {
      type: "time",
      name: "UTC",
      axisLine: { lineStyle: { color: "#3a4655" } },
    },
    yAxis: {
      type: "value",
      name: "P&L",
      scale: true,
      splitLine: { lineStyle: { color: "#24303d" } },
    },
    tooltip: { trigger: "axis" },
    series: [
      {
        name: "Realized equity",
        type: "line",
        showSymbol: false,
        data: data.equity_curve,
      },
      {
        name: "Drawdown",
        type: "line",
        showSymbol: false,
        data: data.drawdown_curve,
        lineStyle: { color: "#e98787" },
      },
    ],
  };
  return (
    <>
      <div className="metrics">
        <Metric label="Realized P&L" value={data.realized_pnl} />
        <Metric label="Total costs" value={data.total_costs} />
        <Metric label="Win rate" value={data.win_rate ?? "N/A"} />
        <Metric label="Expectancy" value={data.expectancy ?? "N/A"} />
        <Metric label="Unrealized P&L" value={data.unrealized_pnl} />
        <Metric label="Gross exposure" value={data.gross_exposure} />
        <Metric label="Turnover" value={data.turnover} />
        <Metric label="Payoff ratio" value={data.payoff_ratio ?? "N/A"} />
      </div>
      <Panel
        title="Equity curve"
        meta={`${data.sample_size} authoritative closed trades`}
      >
        {data.equity_curve.length ? (
          <ReactECharts option={option} style={{ height: 360 }} />
        ) : (
          <div className="empty">No closed-trade curve available.</div>
        )}
      </Panel>
      <div className="split-panels">
        <Panel title="Execution costs" meta="Authoritative journal totals">
          <div className="detail-grid">
            <span>
              Spread <b>{data.spread_costs}</b>
            </span>
            <span>
              Slippage <b>{data.slippage_costs}</b>
            </span>
            <span>
              Commissions <b>{data.commissions}</b>
            </span>
            <span>
              Funding <b>{data.funding}</b>
            </span>
          </div>
        </Panel>
        <Panel
          title="Performance breakdown"
          meta="Instrument / strategy / regime"
        >
          <div className="breakdown-list">
            {[
              ...data.by_instrument,
              ...data.by_strategy,
              ...data.by_regime,
            ].map((item) => (
              <span key={`${item.label}-${item.sample_size}`}>
                <b>{item.label}</b>
                {item.net_pnl} / {item.sample_size} trades
              </span>
            ))}
            {data.by_instrument.length +
              data.by_strategy.length +
              data.by_regime.length ===
              0 && (
              <div className="empty">No closed-trade breakdown available.</div>
            )}
          </div>
        </Panel>
      </div>
      <Panel title="Bounded evidence exports" meta="Sanitized projections only">
        <div className="export-actions">
          <a href="/api/v1/exports?format=jsonl&limit=500">JSONL</a>
          <a href="/api/v1/exports?format=csv&limit=500">CSV</a>
          <a href="/api/v1/exports?format=markdown&limit=500">Markdown</a>
        </div>
      </Panel>
    </>
  );
}
