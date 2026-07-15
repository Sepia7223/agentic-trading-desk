---
title: Leakage-Controlled Backtesting
document: 06_BACKTESTING
version: 1.0.0
status: Planned Specification
owner: Agentic Trading Desk Project
current_validated_milestone: "2 (Milestone 3 planned)"
review_required_after_every_milestone: true
---

# Purpose

This document specifies Milestone 3.5: a deterministic backtesting engine that evaluates strategy behavior using only information available at each historical decision point.

# Status

Backtesting is planned and must not be described as validated until implementation, tests, and review are complete.

# Core Requirements

- chronological processing only;
- explicit warm-up, train, validation, and untouched test periods;
- walk-forward fitting and evaluation;
- no future-data leakage;
- no same-bar execution;
- next-valid-bar entry and exit;
- bid/ask-aware fills;
- configurable spread, slippage, commission, and funding;
- deterministic seeds and reproducible configuration fingerprints;
- immutable simulated signals, orders, fills, trades, and review records;
- identical evaluation methodology across strategy variants.

# Strategy Matrix

The engine shall compare:

- `BASELINE_ONLY`;
- `BASELINE_KALMAN`;
- `BASELINE_HMM`;
- `BASELINE_KALMAN_HMM`;
- a simple Donchian/Turtle-style trend-following control;
- a separately named mean-reversion control where suitable for the tested instrument;
- a passive benchmark where economically meaningful.

External strategies are research controls, not assumed profitable systems.

# Execution Model

A decision generated at bar `t` may execute no earlier than the next valid executable bar. Long entries use ask-side assumptions and exits use bid-side assumptions. Missing quotes, closed markets, stale data, and invalid bars must delay or reject execution according to explicit policy.

# Cost Model

Costs must be itemized rather than hidden in net P&L:

- spread;
- slippage;
- commission;
- overnight funding;
- optional instrument-specific charges.

Every report must state the assumptions used.

# Evaluation Design

Walk-forward windows must preserve chronology. Parameter selection occurs only on training and validation data. The final test period remains untouched until the strategy and configuration are frozen.

The engine must support ablation analysis so the incremental value of Kalman and HMM components can be measured rather than inferred from total return alone.

# Required Metrics

- gross and net return;
- annualized return and volatility where applicable;
- Sharpe and Sortino ratios;
- maximum drawdown;
- return-to-drawdown ratio;
- win rate and profit factor;
- average win, average loss, and payoff ratio;
- trade count and turnover;
- market exposure;
- average and distribution of holding periods;
- spread, slippage, commission, and funding totals;
- performance by instrument, period, and regime.

# Acceptance Criteria

Milestone 3.5 is complete only when leakage-prevention tests pass, identical inputs reproduce identical outputs, all variants use the same assumptions, costs are explicit, untouched test performance is reported honestly, simulated records are journal-ready, and architecture and documentation are updated.

# Prohibitions

The backtester may not call IG execution endpoints, use future bars, tune on the final test period, omit losing trades, silently change cost assumptions, or present in-sample performance as production evidence.
