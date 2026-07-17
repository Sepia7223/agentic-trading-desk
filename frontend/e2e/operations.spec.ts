import { expect, test } from "@playwright/test";

const now = "2026-07-16T12:00:00Z";
const health = {
  name: "scheduler",
  status: "UNKNOWN",
  observed_at: now,
  reason_codes: ["STATUS_UNAVAILABLE"],
  safe_details: {},
};
const snapshot = {
  snapshot_id: "a".repeat(64),
  created_at: now,
  environment: "IG DEMO",
  application_version: "0.1.0",
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

test.beforeEach(async ({ page }) => {
  await page.route("**/api/v1/**", async (route) => {
    const body = route.request().url().includes("/system")
      ? snapshot
      : { records: [], total_matches: 0 };
    await route.fulfill({ json: body });
  });
});

test("shows read-only Demo authority and navigates evidence views", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page.getByText("Environment: IG DEMO")).toBeVisible();
  await expect(page.getByText("Dashboard authority: READ ONLY")).toBeVisible();
  await expect(page.getByText("Subsystem health")).toBeVisible();
  await page.getByRole("button", { name: "Router" }).click();
  await expect(
    page.getByText("RESEARCH ONLY - EXECUTION PROHIBITED", { exact: false }),
  ).toBeVisible();
});
