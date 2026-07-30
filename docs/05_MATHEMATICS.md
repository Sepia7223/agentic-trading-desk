---
current_validated_milestone: 11
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
# Milestone 7.5 Context Statistics

At cutoff `t`, true range is `max(H-L, |H-C_prev|, |L-C_prev|)`, ATR is its configured
rolling mean, and realized volatility is the population standard deviation of causal
simple returns. Percentile ranks use only values observed through `t`. Trend labels
interpret, but do not alter, the existing Kalman slope and HMM semantic regime.
Context and configuration identities are SHA-256 hashes of canonical sorted data.

## Milestone 11 Opportunity Mathematics

Gross expected value is `p_win * average_gain - p_loss * average_loss`. Net expected
value subtracts fresh spread, slippage, commission, funding, uncertainty, low-liquidity,
and event-risk costs. Decimal score components are bounded and weighted to exactly one.
Stable SHA-256 identities cover configuration, evidence, candidates, rankings, cycles,
diagnostics, campaign snapshots, and persisted state.

## Milestone 12 Portfolio Mathematics

All windows are inclusive of the completed evaluation bar unless explicitly called
`prior`; prior range and consolidation windows exclude that bar. Financial thresholds
and candidate prices use `Decimal`; source price arrays are converted from validated
finite positive observations before comparisons.

True range is `TR_t = max(H_t-L_t, |H_t-C_(t-1)|, |L_t-C_(t-1)|)` and ATR is the
arithmetic mean of the last configured true ranges. Linear trend slope is ordinary
least squares, `sum((i-i_bar)(C_i-C_bar)) / sum((i-i_bar)^2)`, normalized by ATR.

For pullbacks, retracement depth is `(recent_peak-recent_low)/ATR`, recovery is
`(current_close-recent_low)/(recent_peak-recent_low)`, and extension is
`(current_close-recent_peak)/ATR`. The stop is below pullback structure by an ATR
buffer; target is a fixed configured multiple of entry risk.

For breakouts, prior consolidation boundaries are `min(low)` and `max(high)` over the
prior window. Width, close breakout distance, and maximum chase are ATR-normalized.
Expansion is current completed-bar range divided by mean prior completed-bar range.
Intrabar touches do not confirm a breakout.

For ranges, equilibrium is `(upper+lower)/2`, location is
`(close-lower)/(upper-lower)`, and recovery is `(close-current_low)/range_width`.
Eligibility requires bounded normalized slope, no confirmed breakout, and configured
volatility. The long-only stop lies outside the lower boundary and target is
equilibrium. Zero width, invalid prices, NaN, infinity, and insufficient reward/risk
reject the signal.

Material definition changes require a new indicator-definition and strategy version.
