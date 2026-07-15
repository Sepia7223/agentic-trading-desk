---
current_validated_milestone: 3 (Milestone 3.5 planned)
depends_on:
- 00_ENGINEERING_BLUEPRINT.md
- 01_SYSTEM_ARCHITECTURE.md
- 04_STRATEGY_ENGINE.md
- 05_MATHEMATICS.md
document: 06_BACKTESTING
owner: Agentic Trading Desk Project
review_required_after_every_milestone: true
status: Living Document
title: Backtesting Methodology
version: 1.0.0
---

# Purpose

This document defines how every strategy is evaluated before it is
allowed to progress toward execution.

Backtesting exists to measure evidence, not to prove profitability.

# Current State

Implemented: - Architecture planned.

Not yet implemented: - Leakage-controlled backtesting engine -
Walk-forward evaluation - Bid/ask execution simulation - Variant
comparison

# Objectives

The backtesting framework shall:

-   Prevent future-data leakage.
-   Evaluate strategies chronologically.
-   Simulate realistic execution costs.
-   Compare strategy variants fairly.
-   Produce reproducible results.

# Core Principles

-   No look-ahead bias.
-   No same-bar execution.
-   No tuning on the final test set.
-   Deterministic configuration.
-   Complete audit trail.

# Planned Workflow

1.  Load validated historical market data.
2.  Validate dataset integrity.
3.  Split data into train, validation, and test.
4.  Fit models using only permitted history.
5.  Generate signals.
6.  Simulate execution with bid/ask prices.
7.  Apply costs and slippage.
8.  Produce metrics and reports.

# Planned Metrics

Performance: - Net return - Drawdown - Profit factor - Win rate - Sharpe
ratio - Sortino ratio - Exposure - Turnover

Research: - Variant comparison - Regime performance - Rejection
reasons - Benchmark comparison

# Safety Rules

The backtester must never:

-   Place broker orders.
-   Require IG authentication for local datasets.
-   Modify historical data.
-   Hide failed assumptions.

# Documentation Governance

After Milestone 3.5:

-   Move implemented features into the validated section.
-   Record execution assumptions.
-   Record benchmark methodology.
-   Record leakage protections.
-   Update this document whenever the evaluation process changes.

A backtesting milestone is not complete until this document matches the
validated implementation.
