# Agentic Trading Desk Development Guide

This repository is being adapted into a safety-first automated trading application.
Codex is the development tool for changing this codebase. The OpenAI API is a future
runtime analysis provider and must not receive broker credentials.

## Required Architecture Reading

Before architectural or milestone work, every human, AI, or coding agent must read,
in order:

1. `docs/00_ENGINEERING_BLUEPRINT.md`
2. `docs/01_SYSTEM_ARCHITECTURE.md`
3. `docs/02_ROADMAP.md`
4. The subsystem-specific document relevant to the task
5. `docs/10_DEVELOPMENT_STANDARDS.md`
6. `docs/11_ARCHITECTURAL_DECISIONS.md`

A milestone is not complete until implementation, tests, and affected documentation
are aligned.

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

- `POST /session` version 3: OAuth login.
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

- Use OAuth session v3 only. Do not retain a parallel CST/X-SECURITY-TOKEN path.
- Keep access and refresh tokens in private in-memory `SecretStr` fields only.
- Use `Authorization: Bearer <access token>` and `IG-ACCOUNT-ID` only after the
  central policy confirms an authenticated read-only operation.
- Clear access token, refresh token, expiry, and account ID after every logout
  attempt, failed login, or detected access-token expiry.
- Never persist or expose tokens through properties, representations, logs,
  exceptions, CLI output, screenshots, tests, or journal records.
- Errors may contain only HTTP status, IG error code, request ID, and operation.
- Do not retry login automatically.
- Do not refresh OAuth tokens automatically. No refresh operation belongs in the
  allowlist until separately documented, implemented, and reviewed.
- Calculate token expiry with a monotonic clock and fail before transport when the
  configured safety margin is reached.
- Missing environment information is accepted because the exact demo gateway and
  local runtime boundary establish `DEMO`; an explicit non-demo value fails closed.
- Missing credentials or session state must fail before an authenticated request.

## Deterministic Strategy Boundary

- Strategy output is limited to `LONG_CANDIDATE`, `WATCH`, and `NO_TRADE`.
- Strategy code has no execution authority and must not import IG configuration,
  credentials, session state, HTTP clients, or broker mutation interfaces.
- Indicator, baseline score, Kalman, HMM, and signal-gate behavior is deterministic.
  Runtime AI and user prompts cannot modify safety-critical model settings.
- Missing, stale, invalid, non-finite, inconsistent, or uncertain state fails closed
  to `NO_TRADE`.
- Long-only mode is fixed. Transitional and bear/high-volatility regimes cannot
  create long candidates under the default reviewed policy.

## Leakage And Reproducibility

- At evaluation time `t`, every price, rolling statistic, Kalman state, scaler,
  HMM fit, state mapping, threshold, and decision must use data through `t` only.
- Historical evaluation must use the explicit cutoff API. Walk-forward analysis
  refits one cutoff at a time; never fit once on a full dataset and report
  in-sample historical signals from that fit.
- HMM raw state indices have no semantic meaning. Map all three states after each
  fit using state-weighted return, volatility, and normalized slope statistics.
- Keep the random seed fixed and include component versions and the configuration
  fingerprint in every result.
- Any model non-convergence, singular or non-finite covariance, insufficient state
  support, malformed probability vector, low selected probability, or excessive
  entropy must fail closed without weaker automatic retries.
- Require at least 30 Kalman observations, 120 usable HMM feature rows after rolling
  loss, and 10 effective observations per state unless a separately reviewed
  configuration raises those floors.
- Treat `predict_proba` at the cutoff as an endpoint smoothed posterior, never as a
  filtered probability. Ambiguous semantic mappings fail closed.
- Signals using completed bar `t` are eligible only from `NEXT_VALID_BAR`; future
  backtests must never assume same-bar-close execution.
- Generic spread gates use basis points, not absolute price units. Daily staleness is
  resolution-aware with explicit weekend grace; unknown cadence fails closed.
- Reproducibility claims apply within a pinned numerical environment. Record numerical
  package versions and the selected ablation variant in every result.
- Preserve regression tests proving that appending future bars cannot change an
  earlier cutoff result and that original three-pillar outputs remain unchanged.
