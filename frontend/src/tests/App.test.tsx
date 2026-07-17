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
  expect(screen.getByText("AI authority: ADVISORY ONLY")).toBeInTheDocument();
});
