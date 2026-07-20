# Agentic Trading Desk Development Guide

This repository is being adapted into a safety-first automated trading application.
Codex is the development tool for changing this codebase. The OpenAI API is a future
runtime analysis provider and must not receive broker credentials.

## Milestone 9 Operations Boundary

- The Operations Center is a read-only projection over sanitized immutable
  journal and typed runtime evidence.
- API operational routes are GET-only. WebSockets stream server events and
  cannot receive commands. Frontend event handling may only invalidate and
  refresh sanitized read-only REST projections.
- The default is disabled and the server may bind only to loopback. Remote
  unauthenticated access is prohibited.
- Monitoring dependencies expose query and health methods only. Never inject a
  mutation adapter, writable journal, mutable Risk Engine, portfolio engine, or
  execution submission function.
- Replay always uses an explicit cutoff, stable chronological ordering, and the
  banner `REPLAY MODE - NO OPERATIONAL AUTHORITY`.
- Why-no-trade explanations are reconstructed from deterministic source records;
  AI summaries remain separate and advisory.
- Position views must distinguish current Paper portfolio state from reconciled
  IG Demo evidence. Entry fills or confirmations alone are not authoritative
  evidence that a position remains open.
- Execution monitoring joins approved intent, request, preflight, operator
  confirmation, submission, broker confirmation, and reconciliation evidence.
  It must truncate deal references and may not expose transport headers.
- Frontend code formats backend-authoritative risk and P&L values and must not
  recalculate or alter them.
- Operations exports are bounded in-memory projections. CSV cells are protected
  against formula injection; exports cannot read raw broker responses or local
  credential files.
- Redact credentials, OAuth values, raw headers, raw broker responses, machine
  paths, and full account/deal references from every projection and error.

## Non-Negotiable Safety Constraints

- Default broker environment is always `DEMO`.
- Default operating mode is always `READ_ONLY`.
- Live trading is technically disabled.
- Automatic execution is disabled by default. Only the separately reviewed,
  hard-limited `AUTOMATED_DEMO` mode may enable it.
- Unknown broker, position, market, or risk state must result in no trade.
- The language model must never control position size or bypass hard-coded risk limits.
- Never use an IG production host. The only broker base URL is
  `https://demo-api.ig.com/gateway/deal`.
- Do not add real credentials or secrets.
- Do not expand the separately reviewed controlled Demo execution surface.
- Do not allow any AI provider to access IG credentials.

## Controlled Execution Boundary

- Milestone 7 permits only one long IG Demo market-position opening through the
  dedicated execution port. The read-only broker port and
  read-only endpoint allowlist remain mutation-free.
- Execution defaults to disabled and requires `CONTROLLED_EXECUTION`, canonical
  Demo gateway validation, explicit enablement, and current Risk Engine
  revalidation. `MANUAL_CONFIRMED` requires a request-bound confirmation;
  `AUTOMATED_DEMO` requires dual enable switches and immutable policy authority.
- The exact execution allowlist is `POST /positions/otc` version 2 and
  `GET /confirms/{dealReference}` version 1. No other mutation path is permitted.
- Never increase approved quantity, remove or loosen the approved stop, alter
  direction, invent missing fields, or submit an unapproved or consumed intent.
- Attempt submission once. Ambiguous outcomes consume the idempotency key and
  require reconciliation; never retry them automatically.
- Broker acceptance requires confirmation evidence. Final completion requires
  reconciliation against read-only positions. Mismatches are recorded and are
  never amended automatically.
- Automated Demo state must be fingerprinted, persist idempotency and journal
  links, reject concurrent runners, and latch every unresolved execution halt.
- Strategy, Risk, AI, Paper Portfolio, and journal packages must not import the
  mutation adapter. AI cannot create, confirm, retry, or reconcile execution.
- Live hosts, position closure/amendment, working orders, account switching,
  short execution, and policy-changing automation remain prohibited.

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

## AI Analyst Boundary

- AI is advisory only. Strategy, Risk Engine, and Paper Portfolio records remain
  authoritative and immutable to AI.
- Analysis and network-provider access default to disabled. No deterministic
  workflow may depend on provider availability.
- Only strict sanitized records may cross the provider interface. Reject secrets,
  authorization structures, raw broker responses, account identifiers, local
  paths, unsafe questions, oversized input, and future historical records.
- Providers cannot approve or reject trades, determine quantity, change stops,
  targets, configurations, risk limits, kill switches, or portfolio state, or
  provide execution instructions.
- Prompts are versioned and deterministic. Responses must be structured,
  source-linked, policy-validated, fingerprinted, and include the mandatory
  advisory statement.
- AI analysis records are append-only. Raw provider responses are not stored.
  Structured retrieval precedes any future semantic retrieval.

## Durable Journal Boundary

- The journal is an append-only evidence store. It has no broker, strategy,
  risk, portfolio, or execution authority and must not import IG or execution
  adapters.
- Wrap validated immutable source records in the common envelope. Do not create
  divergent copies of Strategy, Risk, Paper, Execution, reconciliation, or AI
  domain models.
- Use explicit database and export paths, UTC timestamps, deterministic
  Decimal-safe serialization, schema migrations, foreign keys, transactional
  batches, and a globally ordered SHA-256 fingerprint chain.
- Never update or hard-delete historical records. A correction is a linked,
  immutable amendment with evidence; the original remains unchanged.
- Reject duplicate identities and missing required parents. Deferred linkage is
  explicit, limited by record type, visible to integrity checks, and never a
  silent repair.
- Startup verifies schema, SQLite integrity, foreign keys, sequence, chain,
  payload/source fingerprints, parents, and amendments. Corruption fails closed
  into recovery-read-only mode; never silently rewrite evidence.
- Reviews and similarity calculations are deterministic and cutoff bounded.
  Process quality and financial outcome remain separate classifications.
- AI receives only the `ReadOnlyJournal` facade. It may query sanitized evidence
  and append a separate AI analysis through an authorized writer, but cannot
  amend, rewrite, delete, or use future records.
- Prohibit credentials, OAuth values, authorization headers, raw login or
  provider responses, unnecessary account identifiers, and machine-specific
  paths in persisted payloads and exports.
- Backups use SQLite's consistent backup API, an explicit destination, checksum
  verification, and retention. Exports are bounded and sanitized.
- Semantic embeddings, autonomous parameter changes, cloud storage, distributed
  queues, multi-user mutation, and any journal-to-execution flow remain future.

## Market Context And Router Boundary

- Build every context snapshot at an explicit UTC cutoff. No session, event,
  volatility, spread percentile, model output, or historical summary may use a
  record after that cutoff.
- Session classification uses configured IANA time zones and must preserve London
  and New York DST behavior. Unknown time zones or malformed times fail closed.
- Structured scheduled events are authoritative. Event actuals and revisions are
  invisible until their release timestamps. Unscheduled news can only add caution.
- The registry status is authoritative. Only `VALIDATED` strategies can be
  selected for candidate generation. `RESEARCH_ONLY`, `DISABLED`, and `REJECTED`
  strategies cannot reach Risk or execution.
- The existing trend/regime strategy is the only validated strategy. Range mean
  reversion, volatility breakout, and post-news continuation remain research only.
- Capital preservation is an explicit valid route. The router never forces a trade,
  changes strategy parameters, approves risk, calculates quantity, or submits.
- Operational candidate and automated Demo paths require an authoritative context
  provider. Missing or non-authoritative context must suppress candidates before Risk
  or execution.
- Operational economic and holiday calendars must be explicit, structured, UTC-aware,
  fresh, and cover the evaluation timestamp. Never interpret an absent or implicit
  empty source as a normal day.
- Select completed bars before strategy evaluation. Current or future bars, stale
  quotes, missing bid/ask, and invalid chronology must preserve capital.
- Operational context may consume only typed read-only IG observations. It must not
  import the mutation adapter, load `.env`, approve Risk, or use AI for direction.
- AI cannot classify strategy eligibility, select a strategy, promote research,
  override event policy, or weaken capital-preservation reasons.
- Scheduler identity comes from completed UTC bar boundaries, not sleep timing.
  Duplicate actions and unfinished bars must not be evaluated after restart.
- Promotion requires frozen rules, configuration fingerprints, leakage-controlled
  validation, walk-forward evidence, costs, sufficient context samples, an
  untouched test, documentation, and a separate review.
- Milestone 11.5-B real-entry certification must use `certify-lifecycle`, a populated
  authoritative calendar, and a persisted one-submission limit. Never treat the
  temporary weekend calendar snapshots as execution authorization. After one
  submission, entry remains latched off while reconciliation and lifecycle polling
  continue across restart.
- Certification history must use bounded incremental updates after one full
  bootstrap and fail closed on malformed incremental timestamps.
- Only a uniquely matched, reconciled, ledger-backed Demo position may enter the
  automatic lifecycle; untracked or ambiguous broker positions remain untouched.
- Controlled execution and lifecycle evidence must be mirrored into the durable
  append-only journal used by Operations Center projections.

## IG Read-Only Boundary

Every IG request must pass through the central allowlist. The complete allowed
operation surface is:

- `POST /session` version 3: OAuth login.
- `POST /session/refresh-token` version 1: one bounded OAuth renewal.
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
  attempt, failed login, or failed token refresh.
- Never persist or expose tokens through properties, representations, logs,
  exceptions, CLI output, screenshots, tests, or journal records.
- Errors may contain only HTTP status, IG error code, request ID, and operation.
- Do not retry login automatically.
- When the monotonic expiry safety margin is reached, make exactly one allowlisted
  refresh request before the intended operation. Never retry a failed refresh or
  fall back to login; clear all session state and fail closed.
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

## Position Lifecycle Boundary

- Only `DemoPositionLifecycleEngine` may invoke the dedicated position-exit port.
- The close allowlist is exactly `DELETE /positions/otc` version 1 on the canonical
  IG Demo gateway; confirmation remains `GET /confirms/{dealReference}` version 1.
- Supported mutation is one full offsetting `SELL` close of an exact existing long
  Demo position. It does not authorize short entry, partial close, or amendment.
- Exit precedence is kill/emergency/risk, protective stop, market-closure policy,
  profit target, strategy invalidation, maximum holding, then hold.
- Preflight must re-read current broker positions and validate identity, quantity,
  market/account freshness, risk state, limits, idempotency, and persistent halt.
- A close request is attempted once. Timeout, malformed acknowledgement, unknown
  confirmation, or reconciliation mismatch requires reconciliation and a persistent
  human-cleared halt; automatic retry is forbidden.
- Dashboard, AI, Strategy, Risk, Paper Portfolio, and Journal code must not import or
  call the close adapter. Operations Center lifecycle routes remain GET-only.
- Tests use mock transport. Never inspect `.env`, expose OAuth values, or perform a
  real Demo close without separate operator authorization and an existing position.

## Opportunity Engine Boundary

- `trading_desk.opportunity` is deterministic and provider-neutral. It must not import
  broker adapters, HTTP mutation clients, credential providers, AI execution paths, or
  dashboard command services.
- The governed universe is immutable during a cycle. Unknown or arbitrary epics,
  disabled markets, unfinished/stale bars, missing evidence, non-positive net expected
  value, and research-only strategies fail closed.
- Candidate direction is long only. Opportunity output contains no quantity and cannot
  raise Risk limits. A risk multiplier is a reduction recommendation only.
- Persistent evaluation identity is instrument + timeframe + completed-bar timestamp +
  strategy fingerprint. Do not replace it with wall-clock cycle identity.
- Strategy promotion requires both `BACKTEST_VALIDATED` and
  `DEMO_EXPLORATION_ENABLED`; never promote to increase activity.
- Demo Exploration is disabled by default, requires an explicit enable flag, and is
  technically unavailable outside DEMO. Activity and stretch targets are diagnostic,
  never entry rules.
- Risk alone approves and sizes. Controlled execution alone opens; lifecycle alone
  closes. Ambiguous mutation is never retried.
- Journal every evaluation lineage. Operations APIs remain GET-only and WebSockets
  server-to-client. Dashboard, AI, and Journal have no trade authority.
- `OperationalOpportunityEvidenceProvider` may depend on read-only IG market data,
  Candidate Context, and Strategy Router only. It must not import Risk, execution,
  credentials, tokens, or broker mutation adapters.
- Read-only scan and ranking commands never invoke Risk. Demo exploration requires the
  opportunity, exploration, and execution enable flags before authentication or
  mutation; environment, campaign, ambiguity, reconciliation, and halt checks fail
  closed first.
- Load authoritative broker exposure before ranking. Missing exposure prevents new
  Risk submissions but must not prevent lifecycle monitoring and protective exits.
- Persist completed-bar keys, fair-scheduling cursor, submitted-order ledger, campaign
  state, and safety halts. Daily limits count submitted orders on a UTC date, including
  ambiguous submissions. Never retry an ambiguous mutation.
- Campaign objectives are reporting only. Hard daily-loss, drawdown, consecutive-loss,
  execution-incident, and reconciliation-incident thresholds persist an entry halt;
  they never stop monitoring, reconciliation, or governed exits.

## Multi-Regime Strategy Governance

- Portfolio evaluators consume immutable cutoff-safe market/context records only. They
  must not import broker, HTTP, Risk, execution, credentials, AI, or dashboard modules.
- Decisions are `CANDIDATE`, `REJECT`, `INELIGIBLE_REGIME`, `INSUFFICIENT_DATA`, or
  `STALE_DATA`. Direction is long only. Results contain no quantity, leverage,
  monetary risk, or execution command.
- Shared indicator definitions are canonical and versioned. Observations after the
  current or higher-timeframe evaluation cutoff are prohibited.
- Final-test data is locked before exposure and never selects parameters. Walk-forward
  windows are chronological; failed windows and unstable regions remain visible.
- Promotion is never automatic. A complete fingerprinted artifact, passed gates, and
  explicit promotion record are mandatory. Corrupt or incomplete artifacts fail closed.
- Research-only strategies can be evaluated and journaled but cannot reach Risk.
  Strategy breakers stop new entries only and never disable lifecycle exits.
- Synthetic fixtures validate mechanics only and are not profitability or promotion evidence.

## Historical Validation Boundary

- `trading_desk.strategy.validation_runner`, `validation_orchestration`, and
  `validation_cli` are research tooling. They must not import broker adapters,
  HTTP clients, credentials, Risk, execution, journal writers, or AI providers.
- The approved dataset is described by a committed, fingerprinted manifest:
  source, instruments, timeframes, coverage, retrieval time, bar counts,
  missing-bar policy, timezone, price fields, spread source, cost assumptions,
  and stage boundaries. Raw price files stay local and uncommitted; every
  derived bar file is referenced by SHA-256.
- Simulation is strictly chronological. Entries fill on the next bar's ask
  side plus adverse slippage; exits fill from the bid side; intrabar
  stop/target ambiguity is adverse-first; costs are itemized per trade.
- Context state is built from bounded trailing windows. HMM parameters refit
  on a fixed causal cadence; between refits the latest strictly-older fit is
  reused. Model parameters must never see observations after the cutoff.
- Intraday context classification requires the explicit intraday context
  configuration: the default `hmm_covariance_floor` is calibrated to daily
  feature scale and fails closed on every intraday window. Any operational
  intraday use of the new strategies requires the same reviewed calibration.
- The final-test partition is technically protected: development and
  validation simulation never reads bars past the validation end, and
  final-test simulation requires a pre-existing, fingerprint-verified,
  immutable lock document created after gate review.
- Validation gates are predetermined. Failed strategies remain
  `RESEARCH_ONLY` or become `DISABLED`; artifacts retain failed results.
  Promotion requires a named human approver and is never automatic.
- The accepted trend/regime strategy's portfolio-contribution simulation uses
  its unmodified default configuration on daily bars. Its original acceptance
  evidence predates this framework and is not equivalent to a Milestone 12
  validation artifact.

## Portfolio Analytics Boundary

- `trading_desk.analytics` is a pure, deterministic, read-only calculator. It
  must not import broker adapters, HTTP/mutation clients, execution, lifecycle,
  Risk, portfolio, journal, operations, or opportunity modules; an authority
  scan test enforces this. It cannot change allocations, strategy states, Risk
  policy, execution, lifecycle, campaign state, or broker data.
- Every result carries a declared `MeasureConvention` (reporting currency,
  returns definition, risk/downside conventions, timezone) and is fingerprinted.
  Attribution reconciles exactly: dimension slices sum to portfolio totals,
  cost decomposition sums to total cost, and net equals gross minus costs.
- Missing evidence fails visibly. A metric with no supporting data is an
  explicitly unavailable `Measure` with a reason, never a fabricated zero.
  Notional normalization without an entry notional, cost decomposition without a
  split, currency roll-up without a dated conversion rate, and the outcome of a
  rejected candidate are all reported as unavailable.
- Counterfactuals use frozen evidence only. Accepted-versus-rejected reporting
  never estimates the foregone P&L of a path not taken.
- Currency handling is explicit: a reporting-currency roll-up is produced only
  when every native currency has timestamped conversion evidence dated at or
  before the trade; otherwise the roll-up is unavailable.
- The Operations analytics view (`GET /api/v1/portfolio-analytics`) reconstructs
  closed-trade evidence from authoritative `PAPER_CLOSED_TRADE` records in the
  account currency and reconciles the scorecard net to the authoritative net
  P&L. Records whose gross/cost/net do not internally reconcile, or that lack
  required fields, are excluded with an explicit reason. The route is GET-only.

## Operational Resilience Boundary

- `trading_desk.resilience` holds no trading authority and performs no broker,
  execution, or lifecycle mutation. It imports no ig/execution/lifecycle/api/
  operations/risk/portfolio/opportunity modules and no HTTP client; an authority
  scan test enforces this. It decides whether the desk may start, whether new
  entries are permitted, and records resilience events as immutable evidence.
- Startup preflight fails closed. An unknown diagnostic reading is FAILED, never
  healthy. New entries are permitted only from a fully healthy state; durable
  journal or state corruption forces RECOVERY_REQUIRED with nothing running until
  a human-cleared restore.
- Recovery is reconciliation-first. New entries stay blocked until an
  authoritative reconciliation returns SUCCEEDED; success is never inferred from
  local intent. A model validator makes it structurally impossible for a recovery
  decision to permit entries without a succeeded reconciliation. Protective
  lifecycle monitoring takes priority and runs whenever connectivity is healthy.
- Ambiguous broker mutations are never retried; they halt and require
  reconciliation. Only read-only operations retry, under a bounded, capped
  backoff budget. Transient mutation failures require reconciliation, not retry.
- Corrupt durable state is quarantined and reported, never silently overwritten.
  Backups preserve fingerprints and journal hash-chain lineage byte-for-byte, and
  restore refuses unless every backed-up digest verifies and re-verifies after
  writing.
- Exclusive process ownership is enforced by a fingerprinted lock with a
  heartbeat. A fresh, live foreign lock refuses acquisition; a stale or known-dead
  lock is taken over with an incident. Ownership is never inferred.
- Incident evidence is sanitized: incident detail keys that look like credentials
  or tokens are rejected at the model boundary, so resilience evidence is safe to
  persist and commit. No credentials or raw broker payloads are ever committed;
  CI runs secret, authority, and repository-cleanliness scans.

## Operational Certification Boundary

- `trading_desk.certification` is a pure, deterministic calculator with no trading
  authority. It imports no ig/execution/lifecycle/api/risk/portfolio module and no
  HTTP client; it structures and evaluates certification evidence that actually
  occurred and never manufactures a candidate or forces a trade.
- The verdict is deterministic and fingerprinted: any recorded defect (safety,
  consistency, reconciliation, authority, duplicate mutation) forces FAILED; all
  seventeen required items observed yields CERTIFIED; otherwise
  PARTIALLY_CERTIFIED. A validator makes a CERTIFIED verdict with pending items or
  defects structurally impossible.
- An absent natural trade — markets closed or no candidate appearing — is an
  explicit non-defect and yields PARTIALLY_CERTIFIED, a legitimate reason to
  continue certification later.
- The journal-record collector (`operations/certification_views.py`) derives the
  software/read-only items from immutable record types. The two restart
  checkpoints are operator-recorded and never inferred. `GET
  /api/v1/certification-status` exposes the read-only status; there is no mutation
  route.
- CERTIFIED is reached only by a real operational run
  (`docs/runbooks/ig-demo-certification.md`): a naturally occurring bounded Demo
  trade observed through entry, restart, monitoring, close, reconciliation,
  attribution, and final restart, with no gate weakened and no ambiguous mutation
  retried. The software builds the tooling; it does not fabricate the trade.

## Live-Trading Readiness Boundary

- `trading_desk.readiness` is optional governance tooling. It adds no Live
  capability: no Live host or adapter, no Live credentials, no Live order path,
  no HTTP client. It produces an advisory go/no-go readiness dossier and never
  authorizes anything.
- The recommendation is deterministic and fail-closed: a failed domain or an
  unresolved HIGH/CRITICAL finding forces NO_GO; GO requires every domain PASS,
  no material unresolved finding, every human-gated prerequisite met (milestones
  accepted, Demo certified, legal/financial review, independent safety review,
  separate Live infrastructure and credentials), and named approvers. A validator
  makes a GO recommendation with unmet prerequisites or no approvers structurally
  impossible.
- Demo certification is not financial suitability; a certified Demo alone never
  yields GO. Software cannot satisfy the prerequisites, so an unattended
  assessment can never reach GO by itself.
- The system remains Demo-only regardless of the assessment outcome. Any future
  Live work requires a new architecture decision, a new milestone specification,
  explicit legal and financial approval, separate credentials and infrastructure,
  and an independent safety review. No AI, dashboard, strategy, portfolio, or
  research tooling may approve Live activity.
