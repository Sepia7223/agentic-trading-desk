---
title: Strategy Engine Specification
document: 04_STRATEGY_ENGINE
version: 1.0.0
status: Living Document
owner: Agentic Trading Desk Project
current_validated_milestone: "3 (Milestone 3.5 planned)"
review_required_after_every_milestone: true
---

# Purpose

The Strategy Engine converts validated market data into deterministic trade candidates. It does not execute trades, size positions, manage equity, or access broker credentials.

# Current Validated Implementation

- deterministic baseline strategy;
- local-linear Kalman filter for latent level and slope;
- three-state Gaussian HMM for latent regime estimation;
- deterministic regime mapping and confidence checks;
- deterministic signal gates;
- canonical SHA-256 configuration fingerprints;
- outputs: `LONG_CANDIDATE`, `WATCH`, and `NO_TRADE`;
- variants: `BASELINE_ONLY`, `BASELINE_KALMAN`, `BASELINE_HMM`, and `BASELINE_KALMAN_HMM`.

# Inputs

- validated historical bars;
- market metadata and tradeable state;
- strict immutable strategy configuration;
- current holding state;
- optional macro state, represented as `UNKNOWN` when unavailable rather than silently scored as zero.

# Decision Pipeline

1. Validate history, timestamps, market state, spread, configuration, and holding state.
2. Build features using only information available at the decision cutoff.
3. Evaluate the deterministic baseline.
4. Estimate filtered level, normalized slope, and numerical validity with the Kalman model.
5. Fit and evaluate the HMM chronologically.
6. Map raw states to semantic regimes and reject ambiguous mapping.
7. Apply mandatory gates.
8. Return a typed strategy decision with reasons and configuration fingerprint.

Any invalid prerequisite, numerical failure, ambiguous regime, stale data, or unsupported state fails closed.

# Key Controls

- Kalman minimum history: 30 observations.
- HMM requires sufficient usable observations after feature warm-up and effective observations per state.
- Full pipeline defaults must retain a conservative raw-bar requirement.
- Endpoint posterior values are evaluated at the chronological cutoff.
- HMM state mapping evaluates all state assignments and requires a deterministic ambiguity margin.
- Normalized slope is slope divided by the absolute filtered level.
- Spread is evaluated in basis points from bid and ask around the midpoint.
- Same-bar entry is prohibited; execution belongs to the next valid bar in backtesting.
- Holding state `None` fails closed, `False` may evaluate entry, and `True` cannot produce a duplicate long entry.

# Trade Alignment

A `LONG_CANDIDATE` requires every mandatory gate to pass, including valid data, acceptable spread, baseline alignment, positive trend, acceptable regime and confidence, and a holding state that permits entry.

`WATCH` means conditions are developing but not fully aligned. `NO_TRADE` means the opportunity is rejected or insufficiently supported.

# Prohibitions

The Strategy Engine must never place orders, determine final position size, override risk limits, import broker clients, read secrets, tune itself from future outcomes, or permit AI-generated text to change its decision.

# Planned Evaluation

Milestone 3.5 will compare all strategy variants under identical chronological data, cost assumptions, and splits. It will include simple external benchmark controls without presuming those benchmarks are profitable.

# Governance

Any new model, feature, gate, output, or parameter requires tests, leakage review, mathematical documentation, roadmap updates, and an ADR when architectural behavior changes.
