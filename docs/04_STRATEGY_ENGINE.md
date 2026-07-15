---
current_validated_milestone: 3.5 (Milestone 4 planned)
depends_on:
- 00_ENGINEERING_BLUEPRINT.md
- 01_SYSTEM_ARCHITECTURE.md
- 02_ROADMAP.md
- 03_IG_INTEGRATION.md
document: 04_STRATEGY_ENGINE
owner: Agentic Trading Desk Project
review_required_after_every_milestone: true
status: Living Document
title: Strategy Engine Specification
version: 1.0.0
---

# Purpose

This document defines how the Strategy Engine converts validated market
data into deterministic trade candidates.

The Strategy Engine **does not execute trades**. It evaluates market
conditions and produces a recommendation that is later reviewed by the
Risk Engine.

# Current Validated Implementation

Validated through Milestone 3:

-   Baseline deterministic strategy
-   Kalman Filter trend estimation
-   Three-state Hidden Markov Model (HMM)
-   Deterministic signal gates
-   Configuration fingerprinting
-   Long-only mandatory gates and fail-closed model behavior
-   Explicit cutoff evaluation with `NEXT_VALID_BAR` timing metadata
-   Normalized spread gating in basis points
-   Outputs:
    -   LONG_CANDIDATE
    -   WATCH
    -   NO_TRADE

# Responsibilities

The Strategy Engine shall:

-   Consume validated market data only.
-   Produce deterministic outputs.
-   Remain reproducible.
-   Reject insufficient or invalid data.
-   Never access IG authentication or execution.

# Inputs

-   Validated historical bars
-   Market metadata
-   Strategy configuration
-   Feature vectors
-   Current holding state
-   Regime information

# Processing Pipeline

1.  Validate prerequisites.
2.  Build features.
3.  Evaluate baseline strategy.
4.  Estimate trend using Kalman Filter.
5.  Classify regime using HMM.
6.  Apply deterministic signal gates.
7.  Produce a trade candidate.

Failure at any stage returns NO_TRADE.

The strategy has no broker, HTTP, OAuth, credential, position-sizing,
risk-approval, or execution interface. Unknown holding state always fails
closed to `NO_TRADE`.

# Trade Alignment Rules

A LONG_CANDIDATE requires every mandatory gate to pass.

Typical gates include:

-   Sufficient history
-   Tradeable instrument
-   Acceptable spread
-   Bullish baseline
-   Positive Kalman trend
-   Acceptable HMM regime
-   Regime confidence threshold
-   Holding state permits entry

No single indicator is sufficient to create a trade.

# Outputs

## LONG_CANDIDATE

A deterministic long-entry opportunity. This is **not** an order.

## WATCH

Conditions are developing but mandatory gates are not fully aligned.

## NO_TRADE

The strategy rejects the opportunity or lacks sufficient confidence.

# Explicit Prohibitions

The Strategy Engine must never:

-   Place orders
-   Size positions
-   Manage account equity
-   Override risk controls
-   Access OAuth tokens
-   Access HTTP clients
-   Read broker credentials

# Validated Backtesting Integration

Milestone 3.5: - Leakage-controlled backtesting - Strategy ablation -
Benchmark comparison - Validation-only comparison - Frozen final-test release

# Planned Enhancements

Future milestones: - Additional validated models - Portfolio-aware
signals - Multi-timeframe confirmation

# Documentation Governance

After every milestone affecting strategy behavior:

-   Update validated capabilities.
-   Record new gates and assumptions.
-   Update mathematical references.
-   Keep planned features separate from implemented functionality.

A strategy milestone is not complete until this document matches the
validated implementation.
