---
title: Engineering Blueprint
document: 00_ENGINEERING_BLUEPRINT
version: 1.0.0
status: Living Document
owner: Agentic Trading Desk Project
current_validated_milestone: "3 (Milestone 3.5 planned)"
review_required_after_every_milestone: true
---

# Purpose

This document is the governing specification for the Agentic Trading Desk. Every architectural decision, milestone, code contribution, AI-assisted implementation, and trading capability must align with it.

The objective is to engineer a reliable, production-quality quantitative trading platform centered on IG.com, with deterministic decision making, rigorous testing, controlled risk, transparent records, and AI-assisted research.

# Vision

Build a modular platform that:

- integrates cleanly with the IG Demo API before any controlled live capability;
- uses deterministic mathematical models as the primary decision engine;
- uses AI only as an advisory research, explanation, and review layer;
- validates strategies through leakage-controlled historical testing;
- records every decision and trade for later review;
- fails closed whenever required data, state, or authorization is uncertain;
- evolves through explicit, reviewable milestones.

# Non-Negotiable Principles

1. Demo before live.
2. Read-only before execution.
3. Deterministic systems before AI.
4. Strategy produces candidates, not orders.
5. Risk approval is authoritative.
6. No subsystem bypass.
7. Unknown state means no trade.
8. Secrets never enter logs, models, reports, prompts, tests, or journals.
9. Identical inputs and configuration must produce reproducible results.
10. A milestone is incomplete until code, tests, architecture, and documentation agree.

# Approved Trade Flow

```text
Market Data
→ Validation
→ Feature Engineering
→ Strategy Engine
→ Risk Engine
→ Execution Engine
→ Broker Adapter
→ IG.com
→ Monitoring and Journal
→ AI Review
```

The AI Analyst cannot call the broker, approve risk, select position size, change protected configuration, or execute trades.

# Current Validated State

Validated through Milestone 3:

- safety-first Python foundation;
- immutable configuration boundaries;
- IG OAuth session v3 against the exact Demo gateway;
- strictly read-only accounts, positions, market search, market details, and historical prices;
- deterministic baseline strategy;
- local-linear Kalman trend estimation;
- three-state Gaussian HMM regime estimation;
- deterministic signal gates and configuration fingerprints.

Milestone 3.5, leakage-controlled backtesting, is planned. Execution, deterministic portfolio risk, AI runtime analysis, automated journaling, and live trading are not currently implemented.

# Long-Term Mission

The completed platform should gather and validate market data, identify regimes, generate deterministic candidates, evaluate portfolio risk, simulate and backtest honestly, execute only under explicit authorization, journal every decision, and use AI to review evidence without bypassing deterministic governance.

# Governance

All future work must preserve validated safety boundaries and clearly label capabilities as Validated, Planned, or Future. Architectural changes require an ADR and affected documentation updates before milestone completion.
