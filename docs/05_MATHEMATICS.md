---
title: Mathematics & Quantitative Models
document: 05_MATHEMATICS
version: 1.0.0
status: Living Document
owner: Agentic Trading Desk Project
current_validated_milestone: "3 (Milestone 3.5 planned)"
review_required_after_every_milestone: true
---

# Purpose

This document defines the mathematical foundation of the Agentic Trading Desk and the standards for introducing quantitative models.

# Quantitative Governance

Every model must be deterministic for identical inputs and configuration, documented, testable, numerically guarded, evaluated chronologically, and rejected when assumptions are violated. A more complex model must demonstrate measurable value over a simpler control.

# Deterministic Baseline

The baseline is the permanent control strategy. It combines explicit trend, momentum, and optional macro information through deterministic rules. It provides a benchmark against which Kalman, HMM, and future additions are evaluated.

# Kalman Local-Linear Trend Model

The latent state contains level and slope:

```text
x_t = [level_t, slope_t]^T
```

A local-linear transition advances level by the previous slope while allowing controlled process noise. Observed market prices are noisy measurements of latent level.

The implementation exposes filtered level, slope, normalized slope, and numerical diagnostics. Normalized slope is:

```text
normalized_slope = slope / abs(filtered_level)
```

Invalid, non-finite, or insufficiently supported states fail closed.

# Three-State Gaussian HMM

The HMM estimates an unobserved regime from chronological features such as return, volatility, drawdown, and trend-related information.

Raw numerical state labels are meaningless. The implementation evaluates all six assignments for three states, maps them to semantic regimes using deterministic criteria, and rejects ambiguous mappings when the best and second-best assignments are insufficiently separated.

The current conceptual regimes are bullish/low-volatility, transitional, and bearish/high-volatility. Exact labels and mapping rules remain configuration-controlled and testable.

# Probability and Confidence

Regime decisions use posterior probabilities available at the evaluation cutoff. Confidence thresholds are deterministic gates, not subjective AI judgments.

# Spread and Execution Mathematics

Spread in basis points is calculated from bid, ask, and midpoint:

```text
mid = (ask + bid) / 2
spread_bps = 10_000 * (ask - bid) / mid
```

Backtesting must distinguish signal price from executable bid/ask fills and must apply next-valid-bar assumptions, slippage, commission, and funding where relevant.

# Leakage Controls

- features at time `t` use no observation after `t`;
- model fitting is chronological;
- test periods remain untouched during selection;
- same-bar execution is prohibited;
- parameter tuning is isolated from final evaluation;
- historical similarity review may not use the current trade's future outcome.

# Metrics

Milestone 3.5 should report net and gross return, volatility, Sharpe, Sortino, maximum drawdown, Calmar or return-to-drawdown ratio, profit factor, win rate, average win/loss, exposure, turnover, trade count, holding period, and cost decomposition.

No single metric proves robustness. Results must be interpreted across periods, instruments, regimes, costs, and parameter sensitivity.

# Deferred Models

GARCH, Bayesian models, portfolio optimization, Kelly sizing, reinforcement learning, and adaptive online parameter changes are not implemented. Each requires a separate design, evidence, tests, and governance review.

# Governance

Whenever a milestone changes mathematical models, update assumptions, equations, parameter definitions, limitations, validation methods, and leakage controls in this document.
