---
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
current_validated_milestone: "5"
implementation_status: Partially validated; durable journal storage remains planned
review_required_after_every_milestone: true
---

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

## Planned

The following are not yet implemented:

- persistent trade journal database;
- automated signal journaling;
- post-trade review workflow;
- semantic trade search;
- AI-generated review reports;
- pre-session historical similarity review;
- chart and screenshot storage;
- historical lesson retrieval.

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
contain an immutable expiring approved intent. Neither record is a broker order,
and persistent journal storage remains planned.

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
- protected from silent editing.

Corrections must create an amendment record rather than silently replacing historical facts.

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
are not broker orders and are not yet stored in a persistent journal database.

## Milestone 5

The Paper Portfolio should use the journal as its permanent audit trail.

## Milestone 5.5

Implement the Trade Intelligence and Historical Memory Engine:

- automated journaling;
- post-trade review;
- historical similarity search;
- daily, weekly, and monthly reports;
- structured lesson retrieval.

## Milestone 6

The AI Analyst consumes journal and memory data in advisory mode.

## Milestone 7+

Demo and future live execution use the same journal interfaces.

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
