---
title: Glossary
document: 12_GLOSSARY
version: 1.1.0
status: Living Document
owner: Agentic Trading Desk Project
current_validated_milestone: "2 (Milestone 3 planned)"
review_required_after_every_milestone: true
---

# Purpose

This glossary defines the terminology used throughout the project so human and AI contributors use consistent language.

## Agentic Trading Desk

The complete safety-first quantitative trading platform.

## Broker Layer

The isolated subsystem responsible for approved communication with IG.com.

## Strategy Engine

The deterministic subsystem that converts validated market data into trade candidates.

## Risk Engine

The planned deterministic authority that approves or rejects a candidate and calculates final permitted size.

## Execution Engine

The planned subsystem that translates a valid Risk Engine approval into broker operations. It is not currently implemented.

## AI Analyst

A planned advisory subsystem that explains, reviews, retrieves evidence, and proposes research. It cannot approve or execute trades.

## LONG_CANDIDATE

A deterministic recommendation that a long entry is eligible for risk review. It is not an order.

## WATCH

Conditions are developing but mandatory strategy gates are not fully aligned.

## NO_TRADE

The strategy rejects the opportunity or lacks valid information or confidence.

## Kalman Filter

A state-space estimator planned for Milestone 3 to infer latent market level and slope from noisy observations.

## Hidden Markov Model (HMM)

A probabilistic model planned for Milestone 3 to estimate an unobserved market regime from chronological features.

## Regime

A statistical description of the market environment, such as bullish/low-volatility, transitional, or bearish/high-volatility.

## Configuration Fingerprint

A planned deterministic SHA-256 hash of canonical strategy or risk configuration used for reproducibility and audit linkage.

## Walk-Forward Testing

Chronological evaluation in which each decision uses only information available at its historical cutoff.

## Future-Data Leakage

Any use of information that was unavailable when a historical decision would have been made.

## Next Valid Bar

The first later bar that satisfies explicit execution requirements. A signal generated on one bar cannot fill on the same bar.

## Fail Closed

Rejecting or stopping activity when required state is missing, invalid, stale, contradictory, or uncertain.

## Demo Environment

The IG simulation environment required before controlled live consideration.

## Trade Journal

The planned append-only evidence store for signals, risk decisions, executions, trades, outcomes, and reviews.

## Historical Memory

Structured and semantic retrieval over prior journal evidence. It is advisory and cannot automatically change strategy or risk behavior.

## Maximum Favorable Excursion (MFE)

The greatest unrealized favorable movement observed during a trade.

## Maximum Adverse Excursion (MAE)

The greatest unrealized adverse movement observed during a trade.

## Process Quality

A classification of whether the system followed its approved rules, independent of whether the trade made or lost money.

## Kill Switch

A deterministic control that blocks new trading activity when safety conditions require it.

# Governance

Update this glossary whenever a validated or planned architectural concept introduces terminology that contributors must interpret consistently.
