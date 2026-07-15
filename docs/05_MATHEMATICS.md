---
current_validated_milestone: 3.5 (Milestone 4 planned)
depends_on:
- 00_ENGINEERING_BLUEPRINT.md
- 01_SYSTEM_ARCHITECTURE.md
- 04_STRATEGY_ENGINE.md
document: 05_MATHEMATICS
owner: Agentic Trading Desk Project
review_required_after_every_milestone: true
status: Living Document
title: Mathematics & Quantitative Models
version: 1.0.0
---

# Purpose

This document defines the mathematical foundation of the Agentic Trading
Desk.

It explains the quantitative models that are implemented, the
assumptions behind them, and the standards for introducing future
mathematical techniques.

This document is the authoritative reference for every statistical and
mathematical component used by the Strategy Engine.

# Current Validated Models

Validated through Milestone 3:

-   Deterministic baseline strategy
-   Kalman Filter
-   Three-state Gaussian Hidden Markov Model (HMM)
-   Deterministic signal gates
-   Configuration fingerprinting

# Engineering Principles

Every mathematical model must:

-   Improve measurable decision quality.
-   Be deterministic for identical inputs and configuration.
-   Be testable.
-   Be documented.
-   Fail closed when assumptions are violated.
-   Avoid future-data leakage.

# Baseline Strategy

Purpose:

Provide a deterministic reference model against which all future
improvements are measured.

The baseline is the control system for all future research.

No new model may replace it without evidence from controlled testing.

# Kalman Filter

Purpose:

Estimate latent market trend while reducing observation noise.

Current implementation:

-   Local linear trend model
-   State:
    -   level
    -   slope

Responsibilities:

-   Estimate filtered trend.
-   Estimate normalized slope.
-   Reject invalid numerical states.

The Kalman Filter is an analytical component only and never generates
orders.

# Hidden Markov Model

Purpose:

Estimate the latent market regime.

Current implementation:

-   Three hidden states
-   Gaussian emissions
-   Deterministic state mapping

Example semantic regimes:

-   BULL_LOW_VOL
-   TRANSITIONAL
-   BEAR_HIGH_VOL

Raw state numbers have no semantic meaning until mapped.

# Feature Engineering

Current validated feature families include:

-   Returns
-   Volatility
-   Drawdown
-   Kalman-derived features
-   Regime features

Additional features require validation before inclusion.

# Leakage Prevention

Every model must operate only on information available at the decision
time.

Requirements:

-   No future observations.
-   Chronological fitting.
-   Walk-forward evaluation.
-   No test-set tuning.
-   No same-bar execution assumptions.

# Future Models

Not yet implemented:

-   GARCH
-   Bayesian models
-   Regime-switching volatility
-   Kelly sizing
-   Portfolio optimization
-   Reinforcement learning

Future additions require:

-   design approval
-   implementation
-   validation
-   documentation updates

# Documentation Governance

Whenever a milestone changes the mathematical models:

-   Update this document.
-   Record assumptions.
-   Record limitations.
-   Record new parameters.
-   Record validation methodology.

No mathematical milestone is complete until this document reflects the
validated implementation.
