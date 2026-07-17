---
current_validated_milestone: 9
depends_on:
- 00_ENGINEERING_BLUEPRINT.md
- 01_SYSTEM_ARCHITECTURE.md
document: 11_ARCHITECTURAL_DECISIONS
owner: Agentic Trading Desk Project
review_required_after_every_milestone: true
status: Living Document
title: Architecture Decision Records
version: 1.0.0
---

# Purpose

This document records the significant architectural decisions made
throughout the project.

Every major decision should explain:

-   Context
-   Decision
-   Rationale
-   Trade-offs
-   Status
-   Affected milestones

This provides long-term engineering history for both human and AI
contributors.

------------------------------------------------------------------------

# ADR-001 --- IG.com as Initial Broker

**Status:** Accepted

## Context

The project required a broker with a documented API and a demo
environment.

## Decision

Use IG.com as the initial broker.

## Rationale

-   Mature API
-   Demo environment
-   OAuth v3 support
-   Clear separation between demo and live

## Trade-offs

Broker-specific adapter required.

Affected milestones:

-   M2+
-   Future execution milestones

------------------------------------------------------------------------

# ADR-002 --- Demo Before Live

**Status:** Accepted

## Decision

All development progresses through the IG Demo environment before any
live trading capability is introduced.

## Rationale

Reduces operational risk and allows safe validation.

------------------------------------------------------------------------

# ADR-003 --- Deterministic Before AI

**Status:** Accepted

## Decision

The deterministic strategy engine is the source of trade candidates. AI
provides analysis only.

## Rationale

Improves reproducibility, auditability, and safety.

------------------------------------------------------------------------

# ADR-004 --- Read-Only Before Execution

**Status:** Accepted

## Decision

Broker integration begins with read-only operations.

## Rationale

Validates connectivity and data quality before introducing execution
risk.

------------------------------------------------------------------------

# ADR-005 --- Modular Architecture

**Status:** Accepted

## Decision

Subsystems communicate through defined interfaces and may not bypass one
another.

## Rationale

Supports testing, maintainability, and future expansion.

------------------------------------------------------------------------

# ADR-006 --- Regime-Aware Strategy

**Status:** Accepted

## Decision

Use a deterministic baseline enhanced by a Kalman Filter and a
three-state Hidden Markov Model.

## Rationale

Combines trend estimation with statistical regime identification while
remaining explainable.

------------------------------------------------------------------------

# ADR-007 --- Documentation as a Deliverable

**Status:** Accepted

## Decision

A milestone is not complete until implementation, tests, and
documentation are aligned.

## Rationale

Prevents documentation drift and creates a durable engineering knowledge
base.

------------------------------------------------------------------------

# ADR-008 --- Frozen Final-Test Release

**Status:** Accepted

## Context

Allowing research comparison to inspect the final `TEST` period makes that
period available for iterative strategy selection.

## Decision

Variant comparison is restricted to `VALIDATION`. Releasing `TEST` requires a
tamper-evident frozen-selection artifact created from validation evidence. The
artifact fixes the variant, strategy and backtest configuration, dataset
identity, chronological splits, validation evidence, and authorization state.
Final testing evaluates only that frozen selection, and its results cannot be
accepted by the selection API.

## Rationale

This enforces the research/final-release boundary in code rather than relying
on researcher discipline or a bypassable Boolean option.

------------------------------------------------------------------------

# ADR-009 --- Fail-Closed End-Of-Data Positions

**Status:** Accepted

## Decision

End-of-data liquidation may use only the latest valid, tradeable exit quote
after position activation. If none exists, the backtest records an unresolved
position and does not fabricate a fill or realized P&L.

## Rationale

Non-tradeable or chronologically invalid prices are not executable evidence.
Explicit unresolved state preserves auditability and keeps metrics honest.

------------------------------------------------------------------------

# ADR-010 --- Risk Engine as Sole Approval Authority

**Status:** Accepted

## Decision

Every strategy candidate must pass through the deterministic Risk Engine. Only
it may approve a candidate and determine maximum permitted quantity. Strategy,
AI, Paper Portfolio, and future execution components cannot bypass or replace
that decision.

------------------------------------------------------------------------

# ADR-011 --- Fail Closed on Unknown Risk State

**Status:** Accepted

## Decision

Unknown, incomplete, stale, inconsistent, or non-finite candidate, account,
market, P&L, exposure, position-count, quote, or dealing-rule state rejects.
Unknown holding state is never treated as flat.

------------------------------------------------------------------------

# ADR-012 --- Decimal Financial Arithmetic

**Status:** Accepted

## Decision

Risk prices, quantities, money, ratios, percentages, sizing, and exposure use
`Decimal`. Quantity is constrained first and rounded down, never up, before
final risk and notional are recalculated.

------------------------------------------------------------------------

# ADR-013 --- Explicit State and Time Injection

**Status:** Accepted

## Decision

The caller supplies immutable account and market snapshots plus the UTC
evaluation timestamp. The Risk Engine has no hidden wall clock, broker lookup,
credential loader, HTTP client, or direct persistence dependency.

------------------------------------------------------------------------

# ADR-014 --- Immutable Expiring Approved Intents

**Status:** Accepted

## Decision

Approval produces an immutable, fingerprinted intent linked to candidate,
decision, account snapshot, and market snapshot IDs. The intent is invalid at
or after expiry and is not an order or execution instruction.

------------------------------------------------------------------------

# ADR-015 --- AI Cannot Override Risk

**Status:** Accepted

## Decision

AI may later explain decisions but cannot approve candidates, modify limits,
select quantity, reset loss or kill-switch state, or override any gate.

------------------------------------------------------------------------

# ADR-016 --- Paper Portfolio Is the Approved Simulated-Intent Consumer

**Status:** Accepted

Only the local Paper Portfolio may consume approved intents in Milestone 5. It
cannot bypass risk, increase quantity, access IG, or perform broker execution.

# ADR-017 --- Append-Only Ledger and Deterministic Replay

**Status:** Accepted

Fingerprint-chained monotonic events are the source of truth. State snapshots
are canonical and replay of an intact ordered stream must be byte-equivalent.

# ADR-018 --- Liquidation-Side Valuation and Ambiguity

**Status:** Accepted

Long entries use ask; long marks and exits use bid. Same-bar stop/target
ambiguity defaults to adverse-first, and rejection mode never fabricates a fill.

# ADR-019 --- Duplicate Approval and Unresolved Position Policy

**Status:** Accepted

Decision IDs, fingerprints, and candidate IDs are consumable at most once.
Positions without an eligible tradeable exit quote remain unresolved and
unrealized.

# ADR-020 --- Explicit UTC Daily Accounting

**Status:** Accepted

Callers supply UTC timestamps. UTC date boundaries reset only daily realized
P&L and start-of-day equity; cumulative history and consecutive losses persist.

# ADR-021 --- AI Is Advisory Only

**Status:** Accepted

AI may explain, review, compare, and propose research. Deterministic strategy,
risk, and portfolio systems remain authoritative; AI cannot approve, size,
execute, mutate, or override.

# ADR-022 --- Provider-Neutral Disabled-by-Default Interface

**Status:** Accepted

Domain code depends on an abstract provider protocol. Analysis and network
access default to disabled, and no concrete network provider is included.

# ADR-023 --- Deterministic Sanitization Boundary

**Status:** Accepted

Only bounded, structured, redacted records may reach a provider. Secrets,
authorization structures, raw broker data, paths, unsafe questions, and future
historical records fail closed.

# ADR-024 --- Structured Validated AI Output

**Status:** Accepted

Responses require a strict schema, advisory acknowledgment, source links,
operational-language policy checks, and canonical fingerprints.

# ADR-025 --- Provider Failure Isolation

**Status:** Accepted

Provider disablement, timeout, refusal, error, or malformed output cannot alter
or block deterministic workflows.

# ADR-026 --- Append-Only AI Analysis Records

**Status:** Accepted

Validated advisory responses may append immutable analysis records but cannot
rewrite source journal history. Raw provider responses are not stored.

# ADR-027 --- Structured Retrieval Before Semantic Retrieval

**Status:** Accepted

Historical evidence uses deterministic filters and explicit cutoffs first.
Future semantic retrieval is limited to qualitative records and cannot replace
structured evidence.

# ADR-028 --- No Automatic Strategy or Risk Changes

**Status:** Accepted

AI research hypotheses require human review and controlled deterministic tests.
They cannot deploy themselves or change strategy, risk, kill-switch, or
portfolio configuration.

# ADR-029 --- Dedicated Execution Mutation Boundary

**Status:** Accepted

Only the Execution Engine may use the separate broker mutation port. The
existing broker port and IG read-only allowlist remain mutation-free.

# ADR-030 --- Exact Demo Host for Execution

**Status:** Accepted

Controlled execution accepts only `https://demo-api.ig.com/gateway/deal` and
rejects production, redirects, alternate components, and caller URLs.

# ADR-031 --- Explicit Operator Confirmation

**Status:** Accepted

Confirmation is required by default and binds request fingerprint, quantity,
instrument, direction, drift limit, confirmation time, and expiry.

# ADR-032 --- Immediate Risk Revalidation

**Status:** Accepted

Fresh account, market, and position state must pass the deterministic Risk
Engine immediately before submission. Quantity may only remain equal or fall.

# ADR-033 --- One Submission Attempt

**Status:** Accepted

Idempotency is reserved before transport. Ambiguous outcomes are potentially
executed, consume the intent, require reconciliation, and are never retried.

# ADR-034 --- Confirmation Before Acceptance

**Status:** Accepted

An HTTP acknowledgement is not acceptance. A matching broker confirmation is
required; rejection, missing fields, mismatch, or timeout fails closed.

# ADR-035 --- Reconciliation Before Completion

**Status:** Accepted

Accepted deals are compared with read-only open positions. Discrepancies are
recorded and never corrected by automated amendment.

# ADR-036 --- Immutable Idempotency Keys

**Status:** Accepted

Intent IDs, decision fingerprints, request IDs, request fingerprints, and deal
references are replay-protected and exportable for restart persistence.

# ADR-037 --- Paper and Demo Records Stay Separate

**Status:** Accepted

Broker fills create separate Demo records and never overwrite Paper Portfolio
fills, events, positions, or history.

# ADR-038 --- AI Has No Execution Authority

**Status:** Accepted

AI may explain completed execution records but cannot create requests, confirm,
submit, retry, reconcile, choose quantity, or access broker credentials.

# ADR-039 --- Automated Demo Execution Is Explicit and Bounded

**Status:** Accepted

Automated execution is permitted only through an explicitly enabled
`AUTOMATED_DEMO` mode on the exact Demo gateway. It uses immutable limits,
minimum broker size, deterministic Risk Engine approval, one submission
attempt, persistent idempotency, confirmation, reconciliation, and a latched
halt state. It cannot increase approved quantity, remove protective stops,
retry ambiguous submissions, continue after unresolved state, use a live host,
or receive AI authority. `MANUAL_CONFIRMED` remains the default execution mode.

**Affected Milestones:** 7 and later Demo observation.

# ADR-040 --- Journal as Append-Only Evidence Store

**Status:** Accepted

The durable journal records immutable evidence and has no decision, risk,
portfolio, broker, or execution authority. Historical records have no update or
hard-delete operation.

# ADR-041 --- SQLite as Initial Persistence

**Status:** Accepted

SQLite schema version 2 provides local transactions, foreign keys, WAL,
consistent backup, migration support, and restart-safe operation. Cloud and
distributed persistence remain future.

# ADR-042 --- Wrap Existing Source Models

**Status:** Accepted

Validated Strategy, Risk, Paper, Execution, reconciliation, and AI models remain
authoritative. A stable journal envelope wraps their deterministic serialized
form rather than introducing divergent domain copies.

# ADR-043 --- Fingerprint-Chained Lineage

**Status:** Accepted

Every record has source, payload, previous-record, and journal fingerprints plus
source-parent identifiers and monotonic sequence. Lineage and integrity are
reconstructable after restart.

# ADR-044 --- Amendments Instead of Updates

**Status:** Accepted

Corrections append linked amendment evidence. The original remains intact;
realized-fact corrections require an approval reference and hard deletion is
unavailable.

# ADR-045 --- Deterministic Reviews Before AI

**Status:** Accepted

Post-trade and periodic metrics and classifications are calculated by local code
before any advisory interpretation. Process quality is separate from financial
outcome.

# ADR-046 --- Structured Retrieval Before Semantic Memory

**Status:** Accepted

Typed filters, explicit UTC cutoffs, stable ordering, pagination, query
fingerprints, and deterministic normalized distance are validated first.
Embeddings and semantic vector search remain future.

# ADR-047 --- Explicit Backup and Recovery

**Status:** Accepted

Backups require explicit destinations, SQLite-consistent copying, checksums,
verification, and retention. Startup corruption enters recovery-read-only mode
and is never silently repaired.

# ADR-048 --- Hard Deletion Is Prohibited

**Status:** Accepted

Milestone 8 configuration rejects hard deletion and the repository exposes no
delete method or historical update method.

# ADR-049 --- AI Journal Access Is Read-Only

**Status:** Accepted

AI may query sanitized cutoff-bounded evidence through a read-only facade and
may append a separate analysis only through an authorized boundary. It cannot
amend, rewrite, delete, or mutate upstream systems.

**Affected Milestones:** 8 and later evidence/review work.

## ADR-050 --- Operations Center Is a Read-Only Projection

**Status:** Accepted

The dashboard consumes immutable sanitized records through query-only ports. No
control-plane or mutation dependency is reachable from API or frontend code.

## ADR-051 --- Journal-First Monitoring

**Status:** Accepted

Durable journal evidence is authoritative for historical views. Ephemeral health
may enter only through typed read-only ports and remains `UNKNOWN` when absent.

## ADR-052 --- Loopback-Only Deployment

**Status:** Accepted

The disabled-by-default server binds to loopback only. Remote unauthenticated
access is rejected until a separately reviewed authentication and TLS milestone.

## ADR-053 --- Typed Sanitized WebSocket Events

**Status:** Accepted

WebSockets are server-to-client notifications containing immutable projections.
They are not a command bus and never carry raw broker responses or secrets.

## ADR-054 --- Replay Is Separate from Operations

**Status:** Accepted

Replay uses explicit UTC cutoffs and stable journal order. It cannot call live
state or operational code and is visibly marked as having no authority.

## ADR-055 --- Deterministic Why-No-Trade Reconstruction

**Status:** Accepted

Reasons and gate states come from source records. Optional AI summaries are
separate and advisory.

## ADR-056 --- Frontend Does Not Recalculate Authority

**Status:** Accepted

Risk, quantity, exposure, P&L, and costs are computed by backend deterministic
services. The frontend formats and visualizes those values only.

## ADR-057 --- No Milestone 9 Control Plane

**Status:** Accepted

Milestone 9 adds no order submission, close/amend, risk/strategy/portfolio
mutation, halt clearing, journal rewriting, AI action, live host, or live trading.

# Adding Future ADRs

Every significant architectural change should add a new ADR using this
template:

## ADR-XXX --- Title

**Status:** Proposed \| Accepted \| Superseded \| Deprecated

### Context

### Decision

### Rationale

### Trade-offs

### Affected Milestones

### Related Documents

------------------------------------------------------------------------

# Governance

Review this document after every milestone.

Record all accepted architectural decisions before marking the milestone
complete.
# Milestone 7.5 Decisions

- **Accepted:** route by validated context instead of weakening one universal strategy.
- **Accepted:** capital preservation is an explicit successful routing outcome.
- **Accepted:** structured timestamped events precede any AI news interpretation.
- **Accepted:** research-only status is technically blocked from Risk and execution.
- **Accepted:** sessions use UTC plus IANA zones for DST correctness.
- **Accepted:** scheduling is keyed by completed-bar boundaries, not sleep cadence.
- **Accepted:** promotion is a fingerprinted, leakage-controlled, separately reviewed act.
- **Rejected:** AI strategy selection, raw-news execution, forced trades, and online retuning.

## ADR: Explicit Operational Calendar Sources

- **Accepted:** automated Demo commands require explicit structured economic and
  holiday files with freshness and coverage metadata.
- **Accepted:** the runner owns read-only IG retrieval; the provider consumes typed
  observations and never constructs a hidden client.
- **Accepted:** source identifiers, timestamps, and fingerprints are part of context identity.
- **Rejected:** implicit empty calendars, web scraping in execution, AI event authority,
  unfinished bars, and default-normal context.
