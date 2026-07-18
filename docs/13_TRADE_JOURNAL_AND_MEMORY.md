---
current_validated_milestone: 11
title: Trade Journal, Review & Memory
document: 13_TRADE_JOURNAL_AND_MEMORY
version: 1.0.0
status: Living Document
owner: Agentic Trading Desk Project
repository: agentic-trading-desk
depends_on:
  - 00_ENGINEERING_BLUEPRINT.md
  - 01_SYSTEM_ARCHITECTURE.md
  - 02_ROADMAP.md
  - 04_STRATEGY_ENGINE.md
  - 06_BACKTESTING.md
  - 07_RISK_ENGINE.md
  - 08_AI_ARCHITECTURE.md
current_validated_milestone: "9"
implementation_status: Durable append-only journal, deterministic review, retrieval, backup, and export validated
review_required_after_every_milestone: true
---

## Milestone 9 Journal-First Monitoring

The Operations Center receives `ReadOnlyJournal`, never the writable repository.
Views project append-only evidence into sanitized records, deterministic
why-no-trade explanations, performance summaries, lineage, bounded search, and
cutoff-safe replay. Replay, exports, and UI navigation cannot update, amend,
delete, repair, or append journal records. Runtime health not stored in the
journal is accepted only through typed read-only ports.

# Purpose

This document defines the architecture and objectives for automated trade journaling, post-trade review, historical trade retrieval, and AI-assisted trade memory.

The purpose of this subsystem is to ensure that every completed decision and trade becomes a permanent, reviewable, and searchable record.

The journal is not only an archive. It is the evidence base used to evaluate strategy quality, identify recurring failure patterns, compare current opportunities with historical examples, and support disciplined future research.

The journal and memory systems must never modify strategy behavior automatically.

# Core Objective

Every signal, rejected opportunity, simulated trade, demo trade, and future live trade should produce a complete audit record containing:

- what the system observed;
- what the strategy concluded;
- which gates passed or failed;
- what the Risk Engine decided;
- what execution occurred;
- what the final result was;
- what could be learned from the outcome.

The system must make it possible to answer:

> Have we seen similar conditions before, and what happened?

# Current State

## Validated

The current platform includes:

- deterministic strategy outputs;
- configuration fingerprints;
- read-only IG market data;
- normalized market models;
- reproducible strategy analysis;
- immutable simulated backtest signals, fills, completed trades, and equity records;
- explicit forced-liquidation and unresolved-position records;
- configuration, dataset, split, and run fingerprints.
- append-only paper intent acceptance and rejection events;
- simulated position, mark, funding, close, unresolved, and state-snapshot events;
- immutable closed paper trade records linked to strategy, risk, and portfolio fingerprints;
- a journal protocol that keeps the Paper Portfolio independent from storage and AI.
- append-only structured AI analysis records linked to immutable source IDs;
- deterministic structured historical retrieval with explicit time cutoffs;
- daily, weekly, monthly, signal, risk, trade, portfolio, anomaly, comparison,
  and research-hypothesis advisory modes.
- durable SQLite persistence with an explicit database path, schema version 2,
  migrations, transactions, foreign keys, WAL, and restart-safe readback;
- immutable sequence-ordered journal envelopes with source and parent IDs,
  deterministic Decimal-safe payloads, and SHA-256 fingerprint chaining;
- duplicate and missing-parent rejection, explicit deferred linkage, atomic
  batch rollback, integrity reports, and recovery-read-only startup behavior;
- amendments that preserve originals and prohibit hard deletion;
- deterministic post-trade reviews that separate process classification from
  financial outcome, plus UTC daily, weekly, and monthly summaries;
- structured cutoff-aware filtering, pagination, query fingerprints, lineage
  reconstruction, and normalized-distance historical comparison;
- SQLite-consistent checksummed backups with retention and sanitized bounded
  JSONL, CSV, and Markdown exports;
- a read-only journal facade for AI analysis with no upstream mutation methods.

## Planned

The following remain future and are not implemented:

- automatic wiring of every runtime source event into the durable writer;
- semantic vector or embedding search;
- autonomous strategy or risk modification;
- automatic deployment of AI hypotheses;
- live-trading memory feedback;
- production data warehouse, cloud persistence, distributed streaming, and
  multi-user access;
- chart and screenshot storage.

# Architectural Role

Approved data flow:

```text
Market Data
    ↓
Validation
    ↓
Strategy Engine
    ↓
Risk Engine
    ↓
Execution or Simulation
    ↓
Trade Journal
    ↓
Review Engine
    ↓
Historical Memory
    ↓
AI Analyst
```

The journal must not become a hidden decision engine.

Historical insights may influence future research and AI commentary, but they may not bypass strategy validation, backtesting, the Risk Engine, execution controls, or milestone review.

# Responsibilities

The subsystem shall:

- record every evaluated opportunity;
- record every trade candidate;
- record every rejection and rejection reason;
- record every simulated, demo, and future live trade;
- preserve the exact configuration that produced the decision;
- calculate post-trade performance statistics;
- support structured and semantic historical search;
- generate daily, weekly, and monthly review summaries;
- expose evidence to the AI Analyst in a controlled format;
- preserve an immutable audit trail.

# Journal Record Types

## Signal Record

Created whenever the Strategy Engine evaluates a market.

Includes:

- signal ID;
- EPIC;
- instrument name;
- evaluation timestamp;
- data cutoff timestamp;
- strategy variant;
- configuration fingerprint;
- market regime;
- Kalman outputs;
- HMM probabilities;
- baseline scores;
- gate outcomes;
- final action;
- rejection reasons.

## Risk Decision Record

Created when the Risk Engine evaluates a candidate.

Includes:

- risk decision ID;
- candidate ID;
- signal ID;
- approval, rejection, expiry, invalid-input, or kill-switch status;
- proposed and approved quantity;
- risk budget and final risk amount;
- final risk fraction and notional exposure;
- passed gates;
- failed gates;
- stable deterministic reason codes;
- daily-loss policy;
- account and market snapshot IDs;
- strategy, risk-configuration, and decision fingerprints;
- evaluation timestamp and candidate expiry.

Milestone 4 returns this immutable typed record directly. An approval may also
contain an immutable expiring approved intent. Neither record is a broker order.
Milestone 8 can wrap either source record without changing it.

## Execution Record

Created when simulation, demo, or live execution is attempted.

Includes:

- execution ID;
- candidate ID;
- environment;
- intended action;
- order request summary;
- broker response summary;
- deal reference where applicable;
- acceptance or rejection;
- timestamps;
- safe error information.

Secrets and raw authorization data must never be stored.

## Trade Record

Created for every opened and closed simulated, demo, or future live position.

Includes:

- trade ID;
- signal ID;
- risk decision ID;
- execution ID;
- instrument;
- direction;
- entry timestamp;
- entry price;
- exit timestamp;
- exit price;
- quantity;
- gross P&L;
- net P&L;
- spread cost;
- slippage cost;
- commission;
- funding;
- holding period;
- exit reason;
- environment;
- strategy variant;
- configuration fingerprint.

## Post-Trade Review Record

Created after the trade closes.

Includes:

- maximum favorable excursion;
- maximum adverse excursion;
- realized return;
- drawdown during trade;
- market regime at entry;
- market regime at exit;
- whether the strategy rules were followed;
- whether the Risk Engine rules were followed;
- whether execution matched expectations;
- observed failure modes;
- AI review;
- human review;
- lessons learned.

# Automated Review Workflow

After every closed trade, the program should:

1. finalize the trade record;
2. calculate performance metrics;
3. compare expected and actual execution;
4. evaluate whether all rules were followed;
5. classify the outcome;
6. retrieve similar historical trades;
7. generate a structured post-trade review;
8. store the review;
9. include the trade in later daily, weekly, and monthly summaries.

# Pre-Session Historical Review

Before a future automated trading session begins, the program should review relevant historical evidence.

The review may include:

- recent trades;
- trades in the same instrument;
- trades using the same strategy variant;
- trades in the same HMM regime;
- trades with similar Kalman slope;
- trades with similar spread and volatility;
- trades at similar times or sessions;
- trades with similar rejection reasons;
- recent recurring execution problems.

This historical review is advisory.

It must not automatically change strategy thresholds, risk limits, position sizing, execution permissions, or configuration.

# AI Responsibilities

The AI Analyst may:

- summarize completed trades;
- compare similar historical cases;
- identify recurring errors;
- explain why a trade succeeded or failed;
- produce daily, weekly, and monthly review reports;
- propose research hypotheses;
- highlight anomalies.

The AI Analyst must not:

- rewrite historical records;
- change deterministic strategy configuration;
- change risk limits;
- approve trades;
- execute trades;
- conceal losing trades;
- selectively exclude unfavorable evidence.

# Similarity Search

Historical similarity may use:

- exact structured filters;
- numerical distance;
- vector embeddings for qualitative notes;
- regime matching;
- strategy-variant matching;
- instrument and timeframe matching.

Structured numerical matching should take priority over semantic similarity for trading evidence.

# Data Integrity

Journal records must be:

- append-only where practical;
- timestamped;
- versioned;
- linked by immutable IDs;
- reproducible from stored fingerprints;
- protected from accidental or direct row editing by a fingerprint chain,
  persisted count/head anchors, and SQLite update/delete guards.

Corrections must create an amendment record rather than silently replacing historical facts.

These local controls are tamper-evident, not adversary-proof. A party able to rewrite
the database, schema, triggers, and anchors can forge a new internally consistent
history. Keyed signatures and an independently controlled WORM anchor remain future
requirements before treating the journal as hostile-party audit evidence.

# Storage Architecture

## Initial Storage

Recommended initial implementation:

- SQLite;
- typed repository layer;
- migration support;
- local encrypted backup.

## Future Storage

Possible future migration:

- PostgreSQL;
- object storage for screenshots and charts;
- vector database or PostgreSQL vector extension;
- analytics warehouse.

# Review Cadence

## Per Trade

Generated immediately after closure.

## Daily Review

Includes trades considered, trades taken, trades rejected, realized P&L, open exposure, rule violations, execution errors, and repeated rejection reasons.

## Weekly Review

Includes performance by instrument, strategy variant, regime, costs, recurring failure patterns, and notable outliers.

## Monthly Review

Includes net performance, drawdown, risk-adjusted metrics, strategy stability, execution quality, model drift indicators, and recommendations for controlled research.

# Trade Classification

Every completed trade should be classified separately by process and outcome.

## Process Quality

- VALID_PROCESS
- RULE_VIOLATION
- EXECUTION_ERROR
- DATA_ERROR
- RISK_ERROR
- UNKNOWN

## Financial Outcome

- WIN
- LOSS
- BREAKEVEN

A profitable trade may still be classified as a bad process.

A losing trade may still be classified as a valid process.

# Milestone Placement

## Milestone 3.5

Validated backtests produce immutable simulated signal, fill, trade, equity,
rejection, and unresolved-position records. A forced end-of-data liquidation is
distinguished from an unresolved position with no valid exit quote. Unresolved
positions have no fabricated fill or realized P&L. These local research records
are not broker orders and can now be wrapped in the Milestone 8 journal.

## Milestone 5

The Paper Portfolio emits append-only local journal-compatible events and trade
records. Milestone 8 provides durable wrapping and persistence without changing
the Paper Portfolio models or ledger.

## Historical Milestone 5.5 Proposal

The earlier proposal anticipated:

- automated journaling;
- post-trade review;
- historical similarity search;
- daily, weekly, and monthly reports;
- structured lesson retrieval.

## Milestone 6

Validated: the AI Analyst consumes sanitized journal-compatible records in
advisory mode, uses structured retrieval first, and appends immutable analysis
records. It cannot modify source history. Raw provider responses are not stored,
and Milestone 8 now provides the durable read-only evidence integration.

## Milestone 7

Validated: controlled Demo execution emits append-only request, preflight,
operator-confirmation, submission-attempt, broker-response, confirmation,
failure, and reconciliation records. Every record links the signal, candidate,
risk decision, approved intent, execution request, and safe broker references
where available. Payloads are represented by fingerprints; credentials, OAuth
values, authorization headers, and raw broker messages are never journaled.

Paper simulation and Demo execution records remain separate.

## Milestone 8

Validated: explicit-path SQLite schema version 2, migrations, transactional
append, source-parent linkage, fingerprint chains, restart integrity checks,
recovery-read-only mode, amendments, deterministic reviews, structured queries,
lineage, normalized-distance similarity, checksummed backups, sanitized exports,
and AI read-only access. Automatic wiring of every runtime producer, semantic
vector search, cloud persistence, and autonomous feedback remain future.

# Acceptance Criteria

The journal and memory milestone is complete only when:

- every signal can be reconstructed;
- every rejection is recorded;
- every trade is linked to its signal and risk decision;
- gross and net performance are preserved;
- costs are itemized;
- post-trade reviews are generated;
- similar historical trades can be retrieved;
- AI access is read-only;
- no strategy or risk configuration changes automatically;
- tests verify journal integrity;
- documentation is updated.

# Explicit Prohibitions

The subsystem must never:

- delete losing trades to improve statistics;
- rewrite historical outcomes;
- expose broker credentials;
- store OAuth tokens;
- change risk limits;
- change strategy parameters;
- execute trades;
- claim causation from weak correlations;
- use future trade outcomes during pre-trade analysis.

# Documentation Governance

After every milestone affecting journaling, review, memory, or AI learning:

- update validated capabilities;
- update data models;
- update retention rules;
- update review workflows;
- update AI permissions;
- record new architectural decisions;
- update the roadmap.

A milestone is not complete until implementation, tests, architecture, and this document agree.

# Guiding Principle

The system should not merely remember whether a trade won or lost.

It should preserve the full decision context, evaluate whether the process was correct, compare the trade with similar historical evidence, and turn completed activity into disciplined research without allowing historical memory to bypass deterministic strategy and risk governance.

# Automated Demo Cycle Records

Every bounded cycle records its evaluation timestamp, strategy outcome,
candidate or rejection, Risk Decision, preflight, order-limit state, halt state,
and execution result when present. The persisted snapshot includes the
hash-linked execution journal and idempotency keys. Ambiguous submission,
broker error, integrity failure, and reconciliation mismatch produce a durable
halt record. Credentials, OAuth values, headers, raw responses, and full account
identifiers are never journal fields.
# Milestone 7.5 Evidence Records

The completed Milestone 8 journal taxonomy now includes `SCHEDULER_CYCLE`,
`MARKET_CONTEXT`, `SESSION_CLASSIFICATION`, `EVENT_CONTEXT`, `ROUTER_DECISION`,
`STRATEGY_ELIGIBILITY`, `RESEARCH_STRATEGY_RESULT`, and
`CAPITAL_PRESERVATION_DECISION`. These are append-only evidence without trading
authority. Historical expectancy is cutoff-bounded deterministic memory and cannot
change strategy status, thresholds, Risk decisions, or execution policy.

Operational context source evidence consists of identifiers, UTC source timestamps,
and deterministic fingerprints for historical prices, current quote, economic
calendar, and holiday calendar. It contains no credentials or raw HTTP data. A later
journal integration may persist the resulting immutable snapshot and router decision;
the context provider itself has no journal-led trading authority.

## Validated in Milestone 10

Forward-only schema version 3 recognizes position snapshots, exit decisions,
preflights, close requests/submissions/confirmations/reconciliations, closure, blocked
and halted states, post-trade review, and Paper/Demo comparison. Lifecycle source
records retain their own hash chain and are wrapped in the global append-only journal
with parent linkage. The journal is evidence only and cannot call the close adapter.

## Milestone 11 Opportunity Evidence

Schema v4 records opportunity cycle start/completion/failure, universe loading,
instrument and strategy evaluation, candidate/cost/score outcomes, rejection and
suppression, ranking and selection, Risk submission/rejection, execution approval,
inactivity diagnostics, and Demo campaign state/halt events. Parent IDs preserve market
context, evidence, candidate, ranking, Risk, execution, and campaign lineage. Records
remain append-only, sanitized, replayable, and incapable of triggering execution.
