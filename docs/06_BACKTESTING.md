---
current_validated_milestone: 4 (Milestone 5 planned)
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

## Validated

-   Local CSV and Parquet ingestion with content hashing and strict typed
    validation.
-   Non-overlapping `TRAIN`, `VALIDATION`, and `TEST` periods.
-   Expanding or bounded rolling walk-forward model fitting through each
    evaluation cutoff.
-   Bid/ask fills, deterministic slippage, commission, funding, and stop
    premium accounting.
-   Four strategy variants, benchmarks, metrics, typed simulated journals,
    and reproducible fingerprints.
-   Validation-only variant comparison and an explicit frozen-selection
    release boundary for final testing.

## Planned

Portfolio risk, broker execution, order routing, account-based sizing,
and live trading are not implemented.

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

# Validated Workflow

1.  Load validated historical market data.
2.  Validate dataset integrity.
3.  Split data into train, validation, and test.
4.  Fit models using only permitted history.
5.  Generate signals.
6.  Simulate execution with bid/ask prices.
7.  Apply costs and slippage.
8.  Produce metrics and reports.

# Validated Metrics

Performance: - Net return - Drawdown - Profit factor - Win rate - Sharpe
ratio - Sortino ratio - Exposure - Turnover

Research: - Variant comparison - Regime performance - Rejection
reasons - Benchmark comparison

# Chronology And Final-Test Release

A signal generated from completed bar `t` may fill only on a later eligible
bar. Under `NEXT_CLOSE`, a position becomes active after that later bar's
close; its earlier high and low cannot trigger a stop or target. Protective
evaluation starts on the following eligible chronological bar.

Variant comparison reads `VALIDATION` only. Selection produces an immutable,
tamper-evident artifact containing the selected variant, configuration,
fingerprints, dataset identity, split boundaries, validation metrics,
rationale, and explicit final-test authorization. Final-test evaluation
accepts only that artifact, checks its identity and boundaries, and evaluates
only the frozen variant. Final-test results cannot be fed back into selection.

# End-Of-Data Policy

An open position may be force-liquidated only at the most recent valid,
tradeable exit quote that occurs after activation. The fill is labeled
`FORCED_END_OF_DATA_LIQUIDATION`. If no eligible quote exists, the position is
recorded as unresolved with `NO_VALID_EXIT_QUOTE`; no fill or realized P&L is
fabricated, and metrics report the unresolved count separately.

# Safety Rules

The backtester must never:

-   Place broker orders.
-   Require IG authentication for local datasets.
-   Modify historical data.
-   Hide failed assumptions.

# Documentation Governance

After every milestone, update execution assumptions, benchmark methodology,
leakage protections, release boundaries, and known limitations here.

A backtesting milestone is not complete until this document matches the
validated implementation.
