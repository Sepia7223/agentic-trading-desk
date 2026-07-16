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

## Paper Portfolio Boundary

- Only an intact, unexpired `APPROVED` Risk Decision and its matching immutable
  approved intent may open a simulated position.
- Never increase approved quantity or alter approved direction, stop, target,
  expiry, risk amount, or strategy/risk fingerprints.
- The paper ledger is append-only, sequence-ordered, and fingerprint-chained;
  replay must reproduce the canonical state exactly.
- Use ask plus adverse slippage for long entries and bid minus adverse slippage
  for long exits. Mark open longs at bid.
- Reject duplicate approvals and unknown, stale, malformed, mismatched, or
  non-tradeable state. Never fabricate a fill for unresolved positions.
- Use explicit UTC timestamps and `Decimal` accounting. AI, IG, HTTP, credentials,
  and broker mutation code must not be imported by `trading_desk.portfolio`.

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

## Backtest Boundary

- Backtests are local simulation only. Backtest modules must not import broker clients,
  OAuth or secret configuration, HTTP libraries, account state, or mutation surfaces.
- Use explicit chronological TRAIN, VALIDATION, and TEST periods. Never shuffle bars,
  tune on TEST, or fit any model, scaler, mapping, benchmark, or threshold with future
  data relative to its cutoff.
- A completed-bar signal may fill only on a later valid bar. Default long fills use ask
  for entry and bid for exit; spread must not be charged a second time.
- Apply identical data, costs, quantity, timing, and temporary exit policy to every
  ablation variant. Disabled components must not influence results.
- Keep quantity fixed at one normalized unit. Do not introduce Kelly, volatility,
  account-risk, or equity-based sizing.
- Intrabar ambiguity defaults to `ADVERSE_FIRST`. Open positions at dataset end must be
  liquidated only at the latest valid, tradeable bid after activation and labeled
  `FORCED_END_OF_DATA_LIQUIDATION`; otherwise record an unresolved position without a
  fill or realized P&L.
- A `NEXT_CLOSE` entry activates after its fill bar closes. Stop and target evaluation
  starts on the following eligible bar and must not use the fill bar's earlier range.
- Variant comparison is validation-only. Final TEST evaluation requires an immutable,
  tamper-evident frozen-selection artifact and may evaluate only its selected variant.
  Never feed final-test results back into selection.
- Run fingerprints must include data hash, splits, strategy fingerprint, variant,
  simulation assumptions, schema, and numerical versions while excluding absolute
  paths, credentials, account identifiers, machine data, and launch time.
- A profitable backtest is evidence for further testing, not proof of a profitable live
  strategy.

## Risk Boundary

- The Risk Engine is the sole approval and maximum-quantity authority after strategy
  analysis. Strategy, AI, Paper Portfolio, and broker adapters may not bypass it.
- Risk code is local and deterministic. It must not import broker or HTTP clients, load
  credentials or `.env`, use hidden clocks, call AI, or persist directly to SQLite.
- Inject complete immutable candidate, account, and market snapshots plus an explicit
  UTC evaluation timestamp. Unknown, incomplete, stale, inconsistent, or non-finite
  required state must reject.
- Use `Decimal` for every price, quantity, monetary value, ratio, and fraction. Quantity
  must round down to an increment compatible with both configured and market rules.
- Evaluate projected post-trade gross, instrument, and asset-class exposure, not only
  current exposure. Equality at daily-loss, drawdown, position-count, and
  consecutive-loss limits rejects.
- An active kill switch always prevents approval. AI cannot change limits, reset loss
  state, approve candidates, or override a rejection.
- Approved intents are immutable, fingerprinted, and invalid at or after expiry. They
  are decision records, not broker orders or Paper Portfolio transactions.
