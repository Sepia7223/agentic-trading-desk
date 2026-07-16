---
architecture_review_required: true
current_validated_milestone: 7
depends_on:
- 00_ENGINEERING_BLUEPRINT.md
document: 01_SYSTEM_ARCHITECTURE
owner: Agentic Trading Desk Project
repository: agentic-trading-desk
review_required_after_every_milestone: true
status: Living Document
title: System Architecture
version: 1.0.0
---

# 1. Purpose

This document defines the logical architecture of the Agentic Trading
Desk and serves as the authoritative engineering reference for how every
subsystem interacts.

## Documentation Governance

This is a **living document**.

After every completed milestone:

-   Review this document.
-   Update validated capabilities.
-   Update interfaces if they changed.
-   Record architectural decisions.
-   Record new assumptions or limitations.
-   Update diagrams and subsystem responsibilities.
-   Do not mark a milestone complete until this document reflects the
    validated implementation.

------------------------------------------------------------------------

# 2. Current Project State

## Validated

-   Milestone 0 -- Planning
-   Milestone 1 -- Foundation
-   Milestone 2 -- IG OAuth v3 Demo Read-Only Integration
-   Milestone 3 -- Regime-Aware Strategy Engine
-   Milestone 3.5 -- Leakage-Controlled Backtesting
-   Milestone 4 -- Deterministic Risk Engine
-   Milestone 5 -- Paper Portfolio
-   Milestone 6 -- AI Analyst
-   Milestone 7 -- Controlled IG Demo Execution

## Planned

-   Milestone 8 -- Durable Trade Journal

------------------------------------------------------------------------

# 3. High-Level Design Goals

The architecture is designed to:

-   Separate responsibilities into independent modules.
-   Prevent subsystem bypass.
-   Keep deterministic logic independent of AI.
-   Isolate broker integration.
-   Support testing and reproducibility.
-   Allow future expansion without redesign.

------------------------------------------------------------------------

# 4. Core Architecture Rule

> No subsystem may bypass another subsystem.

Every trade request must move through the approved lifecycle.

Forbidden examples:

-   Strategy Engine → Broker
-   AI → Broker
-   Dashboard → Broker
-   AI → Risk Override

Required flow:

Market Data

↓

Validation

↓

Feature Engineering

↓

Strategy Engine

↓

Risk Engine

↓

Execution Engine

↓

Broker Adapter

↓

IG.com

↓

Monitoring

↓

AI Review

If any mandatory stage fails, the workflow terminates.

------------------------------------------------------------------------

# 5. Subsystems

## Workflow Controller

Coordinates workflows only.

Must never: - place trades - calculate signals - authenticate with IG

## Broker Layer

Current validated capabilities:

-   OAuth v3
-   Exact Demo gateway: `https://demo-api.ig.com/gateway/deal`
-   Read-only
-   Accounts
-   Positions
-   Market search
-   Market details version 3
-   Historical prices
-   Private in-memory token lifecycle and fail-closed session cleanup
-   Dedicated controlled execution adapter for one Demo market-position opening
-   Broker confirmation lookup and read-only position reconciliation

Must never: - evaluate strategies - calculate risk - generate signals

The read-only adapter remains mutation-free. The separate execution adapter
allows only `POST /positions/otc` version 2 and the matching confirmation lookup.
It has no closure, amendment, working-order, account-switching, production-host,
or live-trading operation.

## Market Data Layer

Normalizes broker responses into internal domain models.

## Data Validation Layer

Validates:

-   timestamps
-   bid/ask
-   duplicates
-   missing values
-   tradeable status
-   warm-up history

Invalid data fails closed.

## Feature Engineering

Current validated features:

-   returns
-   volatility
-   drawdown
-   Kalman inputs
-   HMM inputs

## Strategy Engine

Current validated implementation:

-   baseline strategy
-   Kalman filter
-   Hidden Markov Model
-   deterministic signal gates

Outputs:

-   LONG_CANDIDATE
-   WATCH
-   NO_TRADE

Must never:

-   execute trades
-   size positions
-   access broker APIs

## Risk Engine

Validated in Milestone 4 as a deterministic local decision boundary.

Responsibilities:

-   approve or reject strategy candidates
-   calculate maximum permitted Decimal quantity
-   enforce candidate, account, and market freshness
-   enforce stop, daily-loss, drawdown, position-count, and projected exposure limits
-   apply an overriding kill switch
-   produce immutable decision records and expiring approved intents

Account and market state are injected explicitly. Unknown or incomplete state
rejects. Risk decisions are authoritative and cannot be overridden by AI. The
subsystem has no broker, HTTP, credential, storage, or execution dependency.

## Paper Portfolio

Validated in Milestone 5. It consumes approved intents for local simulation,
maintains the append-only paper ledger, and projects AccountRiskState without
bypassing or recalculating the Risk Engine's decision.

## Execution Engine

Validated in Milestone 7. It consumes only intact approved intents, refreshes
broker account/market/position state, re-runs the Risk Engine, and permits
quantity to stay equal or decrease. It requires explicit enablement and a bound
operator confirmation, reserves idempotency before one submission attempt,
requires broker confirmation before acceptance, and reconciles the resulting
position without automatic correction. Ambiguous results are never retried and
remain reconciliation-required.

## Monitoring Layer

Records:

-   logs
-   metrics
-   journals
-   reports

## AI Analyst

Validated in Milestone 6 as a provider-neutral advisory boundary. It consumes
only sanitized immutable records, emits strict source-linked analysis, and may
append AI analysis records. It cannot import broker or mutation engines,
approve risk, select quantity, mutate portfolio state, or execute. Provider
access is disabled by default and provider failure cannot block deterministic
systems.

May:

-   explain
-   summarize
-   review
-   critique
-   research

May not:

-   execute trades
-   override risk
-   change configuration
-   access credentials

------------------------------------------------------------------------

# 6. IG.com Integration Objectives

The platform is engineered around IG.com.

Objectives:

-   robust OAuth lifecycle
-   deterministic read-only access
-   normalized market models
-   safe transition to demo execution
-   no architectural redesign when moving from demo to controlled live
    trading

------------------------------------------------------------------------

# 7. Trade Lifecycle

A trade is eligible only when every mandatory gate aligns.

Example:

1.  Market data valid
2.  Instrument tradeable
3.  Spread acceptable
4.  Warm-up complete
5.  Strategy signal valid
6.  Regime acceptable
7.  Risk approved
8.  Execution permitted

Failure at any step results in NO_TRADE.

------------------------------------------------------------------------

# 8. Architecture Governance

Every milestone must update this document if it changes:

-   subsystem responsibilities
-   interfaces
-   trade lifecycle
-   execution flow
-   AI permissions
-   data flow

A milestone is not complete until implementation, tests, and
documentation are aligned.

------------------------------------------------------------------------

# 9. Guiding Principle

The architecture favors correctness, safety, modularity, and
reproducibility over rapid feature growth.

Every subsystem should be independently understandable, independently
testable, and independently replaceable.

## Bounded Automated Demo Runner

The runner composes read-only IG data, the causal Strategy Engine, the Risk
Engine, execution preflight, the existing one-attempt mutation adapter,
confirmation, and reconciliation. Fingerprinted local state carries daily
counts, cooldown, account identity, idempotency, journal links, and a latched
halt. No Strategy, Risk, AI, Paper Portfolio, or journal component receives a
broker mutation dependency.
