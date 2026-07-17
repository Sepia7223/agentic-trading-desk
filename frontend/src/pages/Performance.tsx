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
    ],
  };
  return (
    <>
      <div className="metrics">
        <Metric label="Realized P&L" value={data.realized_pnl} />
        <Metric label="Total costs" value={data.total_costs} />
        <Metric label="Win rate" value={data.win_rate ?? "N/A"} />
        <Metric label="Expectancy" value={data.expectancy ?? "N/A"} />
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
    </>
  );
}
