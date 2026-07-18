---
current_validated_milestone: 11
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

## Milestone 9 Historical Presentation

The dashboard visualizes backend-authoritative historical and performance
projections. JavaScript does not recalculate risk, fills, P&L, or costs. Replay
uses explicit cutoffs and chronological journal evidence, preventing future
records from appearing before the selected cutoff. New backtesting methodology
or model selection is outside Milestone 9.

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

## Milestone 8 Historical Evidence

Validated backtest records may be wrapped by the durable journal without
changing their dataset, split, configuration, chronology, fill, or outcome
fields. Journal query and review cutoffs prohibit future records, and journal
similarity is deterministic normalized-distance comparison rather than model
training. Journal summaries do not select variants or release final-test data.
Automatic parameter optimization and feedback from journal outcomes remain
future and prohibited.
# Milestone 7.5 Context-Aware Reporting

Validated reporting groups closed observations by strategy, session, overlap,
liquidity, volatility, trend, event state, weekday, spread bucket, instrument, and
timeframe. It reports count, return, drawdown, Sharpe, Sortino, profit factor, win
rate, payoff, exposure, turnover, costs, MFE, MAE, recent performance, and stability.
Records after the explicit cutoff are excluded and insufficient samples are marked.
These summaries cannot promote or dynamically retune a strategy.

## Milestone 10 Exit Consistency

Live Demo lifecycle evaluation uses bid-side liquidation for long positions and the
same adverse-first ambiguity principle used by backtesting and Paper Portfolio.
Paper fills remain simulation evidence and are never overwritten by Demo broker
results. Matching exits may produce a separate analytical comparison of time, price,
costs, P&L, holding period, and reason.

## Milestone 11 Promotion Rule

Multi-instrument activity does not validate a strategy. Every executable family must
retain completed-bar timing, chronological splits, final-test isolation, transaction
costs, Risk-adjusted results, and instrument/regime/timeframe attribution. Research-only
families cannot reach Risk until a separately reviewed backtest promotion changes their
fingerprinted validation policy.
