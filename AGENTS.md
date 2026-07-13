# Agentic Trading Desk Development Guide

This repository is being adapted into a safety-first automated trading application.
Codex is the development tool for changing this codebase. The OpenAI API is a future
runtime analysis provider and must not receive broker credentials.

## Non-Negotiable Safety Constraints

- Default broker environment is always `DEMO`.
- Default operating mode is always `READ_ONLY`.
- Live trading is technically disabled.
- Automatic execution is technically disabled.
- Unknown broker, position, market, or risk state must result in no trade.
- The language model must never control position size or bypass hard-coded risk limits.
- Never use an IG production host. The only broker base URL is
  `https://demo-api.ig.com/gateway/deal`.
- Do not add real credentials or secrets.
- Do not implement order execution unless a separately reviewed milestone explicitly
  authorizes it; the current application remains strictly read-only.
- Do not allow any AI provider to access IG credentials.

## Development Rules

- Preserve the existing deterministic indicator, score, and macro-pillar calculations
  unless a defect is explicitly fixed and covered by tests.
- Keep the MIT license and attribution intact.
- Add tests before or alongside behavioral changes.
- Prefer typed boundaries, small modules, and fail-closed behavior.
- Keep provider-neutral boundaries abstract. The concrete IG adapter must remain
  behind its centralized read-only policy.

## IG Read-Only Boundary

Every IG request must pass through the central allowlist. The complete allowed
operation surface is:

- `POST /session` version 2: login.
- `DELETE /session` version 1: logout.
- `GET /accounts` version 1: account review.
- `GET /positions` version 2: open-position review.
- `GET /markets` version 1: market search.
- `GET /markets/{epic}` version 3: market details.
- `GET /prices/{epic}` version 3: one page of historical prices.

All other methods, paths, versions, hosts, and absolute URLs must fail before
HTTP transport. In particular, never add `/positions/otc`,
`/working-orders/otc`, `/workingorders/otc`, `/confirms/`, `PUT /session`, or
any endpoint that creates, changes, closes, deletes, confirms, or switches an
account, position, order, or working order.

## Session Safety

- Keep `CST` and `X-SECURITY-TOKEN` in private in-memory `SecretStr` fields only.
- Clear both tokens after every logout attempt and every failed login.
- Never persist or expose tokens through properties, representations, logs,
  exceptions, CLI output, screenshots, tests, or journal records.
- Errors may contain only HTTP status, IG error code, request ID, and operation.
- Do not retry login automatically.
- A login response must explicitly report `DEMO`; missing, unknown, or non-demo
  environment state fails closed and clears the session.
- Missing credentials or session state must fail before an authenticated request.
