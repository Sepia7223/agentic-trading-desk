---
current_validated_milestone: 7
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

## Paper Portfolio

The local-only deterministic consumer of approved Risk Engine intents. It
simulates position lifecycle and accounting without broker connectivity or
execution authority.

## Portfolio Event Ledger

A monotonic append-only, SHA-256 fingerprint-chained sequence that is the source
of truth for reproducible paper portfolio state.

## Unresolved Position

A simulated position for which no eligible tradeable exit quote exists. It
remains unrealized and is never converted into fabricated realized P&L.

## Execution Engine

The subsystem responsible for translating approved trades into broker
operations. Not yet implemented.

## AI Analyst

The provider-neutral, disabled-by-default advisory subsystem that explains,
reviews, compares, and proposes research from sanitized deterministic records.
It does not approve, size, execute, mutate, or override.

## Sanitized Context

A strict bounded representation that excludes credentials, authorization data,
raw broker responses, full account identifiers, local paths, and unnecessary
metadata before provider invocation.

## AI Analysis Record

An immutable append-only record linking a structured advisory response to its
sanitized input fingerprint, source IDs, provider metadata, policy version, and
configuration fingerprint.

## Structured Historical Retrieval

Deterministic filtering by explicit attributes and time cutoff. It is the
primary evidence mechanism and prevents future-record leakage.

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

## Controlled Execution

An explicitly enabled, operator-confirmed IG Demo workflow that consumes an
intact approved intent and permits one long market-position opening.

## Execution Preflight

The deterministic gate set that validates approval integrity, fresh state,
risk revalidation, quantity, drift, confirmation, counts, and idempotency before
transport.

## Operator Confirmation

An expiring fingerprinted authorization tied to one exact execution request. It
cannot authorize a different quantity, instrument, direction, or request.

## Ambiguous Submission

A submission whose broker outcome is not safely known. It is treated as
potentially executed, is not retried, and requires reconciliation.

## Position Reconciliation

The read-only comparison of a confirmed broker deal with the resulting Demo
position, including instrument, direction, quantity, entry, stop, and target.

## Execution Idempotency

Replay protection ensuring an approved intent and execution request can be
submitted at most once, including across restored persisted state.

## Production

The controlled live trading environment planned for future milestones.

## AUTOMATED_DEMO

A disabled-by-default controlled-execution mode requiring dual explicit CLI
switches and the canonical IG Demo gateway. It permits at most one eligible
long market-position opening per cycle and day under immutable risk limits.

## Automated Halt

A fingerprinted persistent state that prevents further submission after an
ambiguous response, broker error, integrity failure, risk-limit breach, or
reconciliation failure. It is never cleared automatically.

## MANUAL_CONFIRMED

The default controlled-execution mode. One exact unexpired operator
confirmation is required for each execution request.

# Documentation Governance

Update this glossary whenever new technical terms, models, or
architectural concepts become part of the validated implementation.
