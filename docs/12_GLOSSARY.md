---
current_validated_milestone: 4 (Milestone 5 planned)
depends_on:
- 00_ENGINEERING_BLUEPRINT.md
- 01_SYSTEM_ARCHITECTURE.md
document: 12_GLOSSARY
owner: Agentic Trading Desk Project
review_required_after_every_milestone: true
status: Living Document
title: Glossary
version: 1.0.0
---

# Purpose

This glossary defines the terminology used throughout the project to
ensure humans and AI contributors use consistent language.

# Core Terms

## Agentic Trading Desk

The complete quantitative trading platform being developed.

## Broker Layer

The subsystem responsible for all communication with IG.com.

## Strategy Engine

The deterministic subsystem that converts validated market data into
trade candidates.

## Risk Engine

The deterministic sole approval and maximum-quantity authority that evaluates
a trade candidate against injected account, market, and configuration state.

## Account Risk State

An immutable caller-supplied snapshot of equity, capital, P&L, drawdown,
exposure, position counts, consecutive losses, and kill-switch state. Missing
or incomplete state rejects.

## Market Risk State

An immutable caller-supplied quote and dealing-rule snapshot used for freshness,
spread, stop, size, increment, and value-per-price-unit gates.

## Approved Trade Intent

An immutable expiring record of a Risk Engine approval and maximum permitted
quantity. It is not a broker order and cannot execute a trade.

## Risk Decision

An immutable journal-compatible approval or rejection record containing typed
gates, stable reason codes, Decimal sizing results, snapshot IDs, and canonical
fingerprints.

## Execution Engine

The subsystem responsible for translating approved trades into broker
operations. Not yet implemented.

## AI Analyst

An advisory subsystem that explains, reviews, and researches. It does
not approve or execute trades.

## LONG_CANDIDATE

A deterministic recommendation that a long entry is eligible for risk
review.

## WATCH

Conditions are developing but not fully aligned.

## NO_TRADE

The strategy rejects the opportunity or insufficient conditions exist.

## Kalman Filter

A state-space model used to estimate the underlying market trend.

## Hidden Markov Model (HMM)

A probabilistic model used to estimate latent market regimes.

## Regime

A statistical description of the current market environment.

## Configuration Fingerprint

A deterministic hash representing the active strategy configuration.

## Walk-Forward Testing

Chronological evaluation where only historical information available at
each decision point is used.

## Future-Data Leakage

Using information that would not have been available at the time of a
historical decision.

## Frozen Selection

A tamper-evident validation decision that fixes one strategy variant,
configuration, dataset identity, and split definition before the final test
period can be evaluated.

## Unresolved Position

A simulated open position for which no valid, tradeable exit quote exists at
the end of the dataset. It is reported without a fabricated fill or realized
profit or loss.

## Fail Closed

Rejecting invalid or uncertain conditions rather than proceeding.

## Demo Environment

The IG.com simulation environment used before live trading.

## Production

The controlled live trading environment planned for future milestones.

# Documentation Governance

Update this glossary whenever new technical terms, models, or
architectural concepts become part of the validated implementation.
