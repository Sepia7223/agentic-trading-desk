import { expect, test } from "@playwright/test";

const now = "2026-07-16T12:00:00Z";
const health = {
  name: "scheduler",
  status: "UNKNOWN",
  observed_at: now,
  reason_codes: ["STATUS_UNAVAILABLE"],
  safe_details: {},
};

function snapshot(version: string) {
  return {
    snapshot_id: "a".repeat(64),
    created_at: now,
    environment: "IG DEMO",
    application_version: version,
    git_commit: "abc123",
    system_status: "DEGRADED",
    latest_alerts: [],
    scheduler_status: health,
    broker_status: { ...health, name: "broker" },
    journal_status: { ...health, name: "journal", status: "HEALTHY" },
    execution_status: { ...health, name: "execution" },
    risk_status: { ...health, name: "risk" },
    portfolio_status: { ...health, name: "portfolio" },
    market_context_status: { ...health, name: "market_context" },
    router_status: { ...health, name: "router" },
  };
}

test.beforeEach(async ({ page }) => {
  let systemCalls = 0;
  await page.route("**/api/v1/**", async (route) => {
    const url = route.request().url();
    let body: object = { records: [], total_matches: 0 };
    if (url.includes("/system")) body = snapshot(`0.1.${++systemCalls}`);
    if (url.includes("/execution")) {
      body = {
        lifecycles: [
          {
            execution_request_id: "request-1",
            instrument: "EUR/USD",
            direction: "BUY",
            submitted_quantity: "1",
            safely_truncated_deal_reference: "***3456",
            confirmation_status: "ACCEPTED",
            reconciliation_status: "RECONCILED",
            discrepancies: [],
            halt_status: "CLEAR",
            stages: [
              {
                stage: "PREFLIGHT",
                status: "READY",
                timestamp: now,
                source_record_id: "preflight",
                reason_codes: [],
              },
              {
                stage: "BROKER CONFIRMATION",
                status: "ACCEPTED",
                timestamp: now,
                source_record_id: "confirmation",
                reason_codes: [],
              },
              {
                stage: "RECONCILIATION",
                status: "RECONCILED",
                timestamp: now,
                source_record_id: "reconciliation",
                reason_codes: [],
              },
            ],
          },
        ],
        total_matches: 1,
      };
    }
    if (url.includes("/lifecycle")) {
      body = {
        records: [
          {
            journal_record_id: "lifecycle-journal-1",
            source_record_id: "lifecycle-1",
            source_parent_ids: [],
            record_type: "POSITION_LIFECYCLE_HALTED",
            effective_at: now,
            environment: "DEMO",
            payload: {
              position_id: "position-1",
              status: "RECONCILIATION_REQUIRED",
              remaining_quantity: "1",
              exit_reason: "PROTECTIVE_STOP",
            },
            record_fingerprint: "b".repeat(64),
          },
        ],
        total_matches: 1,
      };
    }
    if (url.includes("/why-no-trade")) {
      body = [
        {
          evaluation_timestamp: now,
          instrument: "EUR/USD",
          router_result: "TREND",
          strategy_result: "NO_TRADE",
          risk_result: "NOT_EVALUATED",
          preflight_result: "NOT_EVALUATED",
          final_action: "NO ORDER",
          primary_reason: "MOMENTUM_THRESHOLD",
          secondary_reasons: ["REBOUND_MISSING"],
          passed_gates: ["SPREAD_ACCEPTABLE"],
          failed_gates: ["MOMENTUM"],
        },
      ];
    }
    if (url.includes("/positions/open")) {
      body = {
        generated_at: now,
        paper_source: "LATEST_PORTFOLIO_STATE",
        demo_source: "LATEST_RECONCILED_DEMO_EXECUTION",
        paper: [
          {
            position_id: "paper-1",
            environment: "PAPER",
            evidence_status: "CURRENT_PORTFOLIO_STATE",
            instrument: "EUR/USD",
            direction: "LONG",
            quantity: "2",
          },
        ],
        demo: [
          {
            position_id: "demo-1",
            environment: "IG DEMO",
            evidence_status: "LATEST_RECONCILED_DEMO_STATE",
            instrument: "EUR/USD",
            direction: "BUY",
            quantity: "1",
          },
        ],
      };
    }
    if (url.includes("/opportunities")) {
      body = {
        records: [
          {
            journal_record_id: "opportunity-journal-1",
            source_record_id: "candidate-1",
            source_parent_ids: ["context-1"],
            record_type: "OPPORTUNITY_CANDIDATE_CREATED",
            effective_at: now,
            instrument: "EUR/USD",
            epic: "CS.D.EURUSD.CFD.IP",
            strategy_variant: "trend-regime-v1",
            environment: "DEMO",
            payload: { status: "ELIGIBLE", score: "86.2" },
            record_fingerprint: "c".repeat(64),
          },
        ],
        total_matches: 1,
      };
    }
    await route.fulfill({ json: body });
  });
});

test("live event refreshes the authoritative dashboard projection", async ({
  page,
}) => {
  await page.addInitScript(() => {
    class MockWebSocket {
      onopen: (() => void) | null = null;
      onclose: (() => void) | null = null;
      onmessage: ((event: { data: string }) => void) | null = null;
      constructor() {
        setTimeout(() => this.onopen?.(), 10);
        setTimeout(
          () =>
            this.onmessage?.({
              data: JSON.stringify({
                event_id: "e".repeat(64),
                event_type: "SYSTEM_HEALTH_UPDATED",
                created_at: "2026-07-16T12:00:00Z",
                source_record_ids: [],
                payload: {},
              }),
            }),
          250,
        );
      }
      close() {
        this.onclose?.();
      }
    }
    Object.defineProperty(window, "WebSocket", { value: MockWebSocket });
  });
  await page.goto("/");
  await expect(page.getByText("Environment: IG DEMO")).toBeVisible();
  await expect(page.getByText("0.1.2")).toBeVisible();
  await expect(
    page.getByText(/Live events: SYSTEM_HEALTH_UPDATED/),
  ).toBeVisible();
});

test("operator inspects the joined execution lifecycle", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Execution" }).click();
  await expect(page.getByText("Execution lifecycle")).toBeVisible();
  await expect(page.getByText("BROKER CONFIRMATION")).toBeVisible();
  await expect(
    page.getByText("RECONCILED", { exact: true }).first(),
  ).toBeVisible();
  await expect(page.getByText("***3456")).toBeVisible();
});

test("operator inspects lifecycle halt without mutation controls", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Lifecycle" }).click();
  await expect(page.getByText("Demo position lifecycle")).toBeVisible();
  await expect(page.getByText("ACTIVE")).toBeVisible();
  await expect(page.getByText("PROTECTIVE_STOP")).toBeVisible();
  await expect(
    page.getByText(/close submission is unavailable/i),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: /close|retry/i })).toHaveCount(
    0,
  );
});

test("operator traces no-trade evidence and separates Paper from Demo", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Why No Trade" }).click();
  await expect(page.getByText("EUR/USD: MOMENTUM_THRESHOLD")).toBeVisible();
  await expect(page.getByText("NO ORDER")).toBeVisible();
  await page.getByRole("button", { name: "Positions" }).click();
  await expect(page.getByText("Paper positions")).toBeVisible();
  await expect(page.getByText("IG Demo positions")).toBeVisible();
  await expect(page.getByText("CURRENT_PORTFOLIO_STATE")).toBeVisible();
  await expect(page.getByText("LATEST_RECONCILED_DEMO_STATE")).toBeVisible();
});

test("operator reviews opportunities without mutation controls", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Opportunities" }).click();
  await expect(page.getByText("Opportunity Board")).toBeVisible();
  await expect(page.getByText("OPPORTUNITY_CANDIDATE_CREATED")).toBeVisible();
  await expect(page.getByText("EUR/USD")).toBeVisible();
  for (const pageName of [
    "Activity Dashboard",
    "Strategy Leaderboard",
    "Instrument Performance",
    "Regime Performance",
    "Inactivity Diagnostics",
    "Demo Campaign",
  ]) {
    await page.getByRole("button", { name: pageName }).click();
    await expect(
      page.getByRole("heading", { name: pageName, level: 1 }),
    ).toBeVisible();
  }
  await expect(
    page.getByRole("button", {
      name: /buy|sell|close|override|enable strategy/i,
    }),
  ).toHaveCount(0);
  await page.screenshot({
    path: "test-results/opportunity-board.png",
    fullPage: true,
  });
});
