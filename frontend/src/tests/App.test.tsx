import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import App from "../App";

const snapshot = {
  snapshot_id: "a".repeat(64),
  created_at: "2026-07-16T12:00:00Z",
  environment: "IG DEMO",
  application_version: "0.1.0",
  git_commit: "abc123",
  system_status: "DEGRADED",
  latest_alerts: [],
};
const record = {
  journal_record_id: "journal-context",
  source_record_id: "context",
  source_parent_ids: [],
  record_type: "market_context",
  effective_at: snapshot.created_at,
  instrument: "EUR/USD",
  epic: "CS.D.EURUSD.CFD.IP",
  strategy_variant: "BASELINE_KALMAN_HMM",
  environment: "DEMO",
  payload: {
    status: "AVAILABLE",
    regime: "BULL_LOW_VOL",
    selected_strategy: "TREND",
    executable: true,
  },
  record_fingerprint: "b".repeat(64),
};
const health = {
  name: "scheduler",
  status: "UNKNOWN",
  observed_at: snapshot.created_at,
  reason_codes: ["STATUS_UNAVAILABLE"],
  safe_details: {},
};
Object.assign(snapshot, {
  scheduler_status: health,
  broker_status: { ...health, name: "broker" },
  journal_status: { ...health, name: "journal", status: "HEALTHY" },
  execution_status: { ...health, name: "execution" },
  risk_status: { ...health, name: "risk" },
  portfolio_status: { ...health, name: "portfolio" },
  market_context_status: { ...health, name: "market_context" },
  router_status: { ...health, name: "router" },
});

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      const body = path.includes("/system")
        ? snapshot
        : path.includes("/context/latest") ||
            path.includes("/router/latest") ||
            path.includes("/risk/latest")
          ? record
          : path.includes("why-no-trade")
            ? [
                {
                  evaluation_timestamp: snapshot.created_at,
                  instrument: "EUR/USD",
                  router_result: "TREND",
                  strategy_result: "WATCH",
                  risk_result: "NOT_EVALUATED",
                  preflight_result: "NOT_EVALUATED",
                  final_action: "NO ORDER",
                  primary_reason: "MOMENTUM_THRESHOLD",
                  secondary_reasons: [],
                  passed_gates: ["SPREAD"],
                  failed_gates: ["MOMENTUM"],
                },
              ]
            : path.includes("/execution")
              ? { lifecycles: [], total_matches: 0 }
              : path.includes("/positions/open")
                ? {
                    paper: [],
                    demo: [],
                    paper_source: "LATEST_PORTFOLIO_STATE",
                    demo_source: "LATEST_RECONCILED_DEMO_EXECUTION",
                  }
                : path.includes("/alerts")
                  ? []
                  : path.includes("/journal/status")
                    ? health
                    : path.includes("/performance")
                      ? {
                          sample_size: 0,
                          realized_pnl: "0",
                          total_costs: "0",
                          wins: 0,
                          losses: 0,
                          equity_curve: [],
                          drawdown_curve: [],
                          daily_pnl: [],
                          unrealized_pnl: "0",
                          spread_costs: "0",
                          slippage_costs: "0",
                          commissions: "0",
                          funding: "0",
                          gross_exposure: "0",
                          turnover: "0",
                          by_instrument: [],
                          by_strategy: [],
                          by_regime: [],
                          by_session: [],
                          by_volatility_state: [],
                          by_event_state: [],
                          by_environment: [],
                        }
                      : { records: [], total_matches: 0 };
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("renders immutable Demo and read-only status", async () => {
  render(<App />);
  expect(screen.getByText("Environment: IG DEMO")).toBeInTheDocument();
  expect(
    screen.getByText("Dashboard authority: READ ONLY"),
  ).toBeInTheDocument();
  await waitFor(() =>
    expect(screen.getByText("Application")).toBeInTheDocument(),
  );
});

it("navigates to deterministic why-no-trade evidence", async () => {
  render(<App />);
  await userEvent.click(screen.getByRole("button", { name: "Why No Trade" }));
  expect(
    await screen.findByText("EUR/USD: MOMENTUM_THRESHOLD"),
  ).toBeInTheDocument();
  expect(screen.getByText("NO ORDER")).toBeInTheDocument();
});

it("labels research strategies and AI as non-operational", async () => {
  render(<App />);
  await userEvent.click(screen.getByRole("button", { name: "Router" }));
  expect(
    screen.getByText(
      "Research strategies: RESEARCH ONLY - EXECUTION PROHIBITED",
    ),
  ).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "AI Reviews" }));
  expect(
    await screen.findByText(/AI authority: ADVISORY ONLY/),
  ).toBeInTheDocument();
});

it("refreshes authoritative REST data after a typed websocket event", async () => {
  const fetchMock = vi.mocked(fetch);
  render(<App />);
  await screen.findByText("Application");
  const initialCalls = fetchMock.mock.calls.length;
  const emit = (
    globalThis as unknown as { __emitOperationsEvent: (event: object) => void }
  ).__emitOperationsEvent;
  emit({
    event_id: "e".repeat(64),
    event_type: "MARKET_CONTEXT_UPDATED",
    created_at: snapshot.created_at,
    source_record_ids: ["context"],
    payload: { status: "AVAILABLE" },
  });
  await waitFor(() =>
    expect(fetchMock.mock.calls.length).toBeGreaterThan(initialCalls),
  );
  expect(
    screen.getByText(/Live events: MARKET_CONTEXT_UPDATED/),
  ).toBeInTheDocument();
});

it("renders dedicated market and position states", async () => {
  render(<App />);
  await userEvent.click(screen.getByRole("button", { name: "Market" }));
  expect(
    await screen.findByText("Authoritative market context"),
  ).toBeInTheDocument();
  expect(screen.getByText("BULL_LOW_VOL")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Positions" }));
  expect(await screen.findByText("Paper positions")).toBeInTheDocument();
  expect(screen.getByText("IG Demo positions")).toBeInTheDocument();
});

it("renders execution lifecycle and alert empty states safely", async () => {
  render(<App />);
  await userEvent.click(screen.getByRole("button", { name: "Execution" }));
  expect(
    await screen.findByText("No execution lifecycle recorded."),
  ).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Alerts" }));
  expect(await screen.findByText("No active alerts.")).toBeInTheDocument();
});

it("exposes bounded sanitized evidence export formats", async () => {
  render(<App />);
  await userEvent.click(screen.getByRole("button", { name: "Performance" }));
  expect(
    await screen.findByText("Bounded evidence exports"),
  ).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "JSONL" })).toHaveAttribute(
    "href",
    "/api/v1/exports?format=jsonl&limit=500",
  );
});

it("renders dedicated risk gate evidence", async () => {
  render(<App />);
  await userEvent.click(screen.getByRole("button", { name: "Risk" }));
  expect(
    await screen.findByText("Deterministic risk gates"),
  ).toBeInTheDocument();
  expect(screen.getByText("No gate evidence available")).toBeInTheDocument();
});

it("renders journal integrity health without mutation controls", async () => {
  render(<App />);
  await userEvent.click(screen.getByRole("button", { name: "Journal" }));
  expect(
    await screen.findByText("Journal integrity evidence"),
  ).toBeInTheDocument();
  expect(screen.getByText("READ ONLY")).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: /repair|delete|amend/i }),
  ).not.toBeInTheDocument();
});

it("fails closed when a domain projection is unavailable", async () => {
  const existing = vi.mocked(fetch).getMockImplementation();
  vi.mocked(fetch).mockImplementation(async (input, init) => {
    if (String(input).includes("/context/latest"))
      throw new Error("projection offline");
    if (!existing) throw new Error("missing test transport");
    return existing(input, init);
  });
  render(<App />);
  await userEvent.click(screen.getByRole("button", { name: "Market" }));
  expect(
    await screen.findByText(/Data unavailable: projection offline/),
  ).toBeInTheDocument();
});
