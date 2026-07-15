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

This document defines the logical architecture of the Agentic Trading Desk and serves as the authoritative engineering reference for how every subsystem interacts.

## Documentation Governance

This is a **living document**. After every completed milestone, review this document, update validated capabilities and interfaces, record architectural decisions and limitations, and keep diagrams and subsystem responsibilities aligned with the implementation.

# 2. Current Project State

## Validated

- Milestone 0 — Planning
- Milestone 1 — Foundation
- Milestone 2 — IG OAuth v3 Demo Read-Only Integration
- Milestone 3 — Regime-Aware Strategy Engine

## Planned

- Milestone 3.5 — Leakage-Controlled Backtesting
- Milestone 4 — Risk Engine
- Milestone 5 — Paper Portfolio
- Milestone 5.5 — Trade Intelligence and Historical Memory
- Milestone 6 — AI Analyst
- Milestone 7 — Demo Execution

# 3. Core Architecture Rule

> No subsystem may bypass another subsystem.

Forbidden flows include Strategy → Broker, AI → Broker, Dashboard → Broker, and AI → Risk Override.

Required flow:

```text
Market Data → Validation → Feature Engineering → Strategy Engine
→ Risk Engine → Execution Engine → Broker Adapter → IG.com
→ Monitoring → Journal/Memory → AI Review
```

If any mandatory stage fails, the workflow terminates safely.

# 4. Subsystems

## Workflow Controller

Coordinates workflows only. It must never place trades, calculate signals, or authenticate with IG.

## Broker Layer

Current validated capabilities: OAuth v3, exact IG Demo environment, read-only accounts, positions, market search, market details, and historical prices. It must never evaluate strategies, calculate risk, or generate signals.

## Market Data and Validation

Normalizes broker responses into typed domain models and validates timestamps, bid/ask data, duplicates, missing values, tradeable status, and warm-up history. Invalid data fails closed.

## Strategy Engine

Current validated implementation: deterministic baseline, Kalman filter, three-state HMM, deterministic gates, and outputs `LONG_CANDIDATE`, `WATCH`, or `NO_TRADE`. It never executes trades, sizes positions, or accesses broker APIs.

## Risk Engine

Planned deterministic authority for position sizing, exposure limits, portfolio constraints, and kill switches.

## Execution Engine

Planned. Translates only approved risk decisions into broker operations.

## Trade Journal and Memory

Planned. Stores immutable decision context, trade outcomes, reviews, and historical comparisons. It is advisory and cannot alter deterministic strategy or risk configuration automatically.

## AI Analyst

May explain, summarize, review, critique, retrieve historical evidence, and propose research. It may not execute trades, override risk, change approved configuration, or access credentials.

# 5. IG.com Integration Objectives

The platform is engineered around IG.com with robust OAuth lifecycle handling, deterministic read-only access, normalized market models, and a safe future transition to demo execution without redesigning strategy logic.

# 6. Trade Lifecycle

A trade is eligible only when every mandatory gate aligns: valid data, tradeable market, acceptable spread, completed warm-up, valid strategy signal, acceptable regime, deterministic risk approval, and explicit execution permission. Failure at any step results in no trade.

# 7. Architecture Governance

Every milestone must update this document when it changes subsystem responsibilities, interfaces, trade lifecycle, execution flow, AI permissions, or data flow. A milestone is not complete until implementation, tests, architecture, and documentation are aligned.
