---
architecture_review_required: true
current_validated_milestone: 3 (Milestone 3.5 planned)
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

## Planned

-   Milestone 3.5 -- Leakage-Controlled Backtesting
-   Milestone 4 -- Risk Engine
-   Milestone 5 -- Paper Portfolio
-   Milestone 6 -- AI Analyst
-   Milestone 7 -- Demo Execution

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

Must never: - evaluate strategies - calculate risk - generate signals

The current Broker Layer has no order, working-order, position-mutation,
account-switching, production-host, or live-trading operation.

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

Planned.

Responsibilities:

-   position sizing
-   exposure limits
-   kill switch
-   portfolio constraints

Risk decisions are authoritative.

## Execution Engine

Planned.

Responsible only for translating approved trades into broker operations.

## Monitoring Layer

Records:

-   logs
-   metrics
-   journals
-   reports

## AI Analyst

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
