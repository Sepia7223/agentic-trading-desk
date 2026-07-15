# 00_ENGINEERING_BLUEPRINT

Version: 1.0 (Draft)

## Purpose

This document is the governing specification for the Agentic Trading
Desk. Every architectural decision, milestone, code contribution,
AI-assisted implementation, and trading capability must align with this
blueprint.

The objective is **not** to build a simple trading bot. The objective is
to engineer a reliable, production-quality quantitative trading platform
centered on IG.com as the execution broker, with deterministic decision
making, rigorous testing, and AI-assisted research.

------------------------------------------------------------------------

# Vision

Build a modular quantitative trading platform that:

- Integrates cleanly with the IG.com API.
- Uses deterministic mathematical models as the primary decision engine.
- Uses AI as a research, review, and analysis layer.
- Operates safely in the Demo environment before any live deployment.
- Evolves through measurable milestones.
- Produces transparent, reproducible trading decisions.

The platform should eventually operate continuously on a dedicated
machine while remaining observable, testable, and safe.

------------------------------------------------------------------------

# Mission

Engineer a system that can:

1. Gather market data from IG.
2. Validate and normalize market data.
3. Detect market regimes.
4. Generate deterministic trade candidates.
5. Evaluate risk.
6. Simulate strategies.
7. Execute only when every required safety condition is satisfied.
8. Record every decision for review and improvement.

------------------------------------------------------------------------

# Primary Goal

Every trade must be opened and closed because **all required conditions
align**, not because a single indicator produced a signal.

The platform must never rely on one model, one indicator, or one AI
response. Instead, multiple independent components must agree before a
trade becomes eligible.

------------------------------------------------------------------------

# Decision Hierarchy

Trade lifecycle:

Market Data → Data Validation → Feature Engineering → Strategy Engine →
Regime Detection → Signal Engine → Risk Engine → Execution Decision →
Broker Adapter → Monitoring → Trade Journal

Failure at any stage prevents execution.

------------------------------------------------------------------------

# System Architecture

The platform is divided into independent modules.

## Broker Layer

Responsibilities:

- OAuth authentication
- Session management
- Account retrieval
- Market search
- Market details
- Historical prices
- Position retrieval

Constraints:

- Demo first
- Read-only until execution milestone
- Fail closed
- Secret redaction
- Strict endpoint allowlist

The broker layer must never contain trading logic.

## Strategy Layer

Responsible for transforming market data into deterministic trade
candidates.

Current models include:

- Existing baseline strategy
- Kalman filter
- Hidden Markov Model
- Signal gating

Future models may include additional statistical techniques only after
validation.

## Risk Layer

The risk engine is the authority for whether a candidate trade may
proceed.

Future responsibilities:

- Position sizing
- Exposure limits
- Daily loss limits
- Portfolio limits
- Kill switch
- Duplicate protection
- Market availability
- Session validation

No trade may bypass the risk engine.

## Execution Layer

Execution is intentionally isolated. It translates approved decisions
into broker requests, confirms acknowledgements, records fills, detects
failures, and retries only where safe. Execution does not decide whether
to trade.

## AI Layer

AI is an advisory subsystem.

AI may explain signals, summarize news, critique strategies, suggest
research directions, detect inconsistencies, and produce reports.

AI must not override deterministic signals or risk controls, place orders
directly, change configuration automatically, or modify historical
results.

------------------------------------------------------------------------

# IG.com Integration Goals

The platform is designed around IG.com.

Objectives:

- Stable OAuth authentication.
- Clean session lifecycle.
- Accurate market normalization.
- Deterministic read-only data retrieval.
- Safe transition to demo execution.
- Eventually support controlled live execution without architectural redesign.

Broker integration should remain isolated so future brokers can be added
through adapters without changing the strategy engine.

------------------------------------------------------------------------

# Trade Alignment Model

A trade becomes eligible only when every required layer agrees.

Example pipeline:

1. Market data valid.
2. Instrument tradeable.
3. Spread acceptable.
4. Strategy warm-up complete.
5. Baseline trend bullish.
6. Kalman trend positive.
7. HMM regime acceptable.
8. Regime confidence above threshold.
9. Risk checks pass.
10. Market session open.
11. Holding state allows entry.
12. Execution policy permits order creation.

If any mandatory gate fails, the result is `NO_TRADE`.

------------------------------------------------------------------------

# AI Goals During Development

Every AI working on this repository should optimize for:

1. Correctness before speed.
2. Simplicity before complexity.
3. Safety before profitability.
4. Evidence before assumptions.
5. Maintainability before shortcuts.

AI contributors should preserve modular architecture, avoid hidden state,
keep deterministic behavior, expand tests, document architectural
decisions, and preserve reproducibility.

They must not weaken safety checks, remove validation, bypass milestones,
add execution prematurely, or merge unrelated concerns.

------------------------------------------------------------------------

# Milestones

- M0 — Planning and architecture
- M1 — Project foundation
- M2 — IG OAuth v3 demo read-only integration
- M3 — Deterministic strategy engine
- M3.5 — Leakage-controlled backtesting
- M4 — Risk engine
- M5 — Paper portfolio
- M5.5 — Trade intelligence and historical memory
- M6 — AI analyst
- M7 — Demo execution
- M8 — Trade journal operationalization
- M9 — Monitoring dashboard
- M10 — Knowledge and memory expansion
- M11 — Multi-agent architecture
- M12 — Production deployment
- M13 — Controlled live trading

Each milestone must have documented objectives, acceptance criteria, and
regression tests before the next milestone begins.

------------------------------------------------------------------------

# Definition of Success

The system is successful when it makes reproducible decisions, survives
realistic costs and testing, integrates reliably with IG.com, protects
capital through deterministic risk controls, provides transparent
reasoning for every trade, and allows AI to enhance analysis without
replacing governance.

Profitability alone is not sufficient; engineering quality, safety, and
repeatability are equally important.

------------------------------------------------------------------------

# Documentation Governance

Documentation is a core deliverable. A milestone is **not complete**
until implementation, automated tests, architecture, and documentation
are aligned.

Immediately after every milestone:

1. Review affected documents under `docs/`.
2. Update implemented functionality.
3. Move completed features from planned to validated.
4. Update the roadmap.
5. Record architectural decisions.
6. Record constraints, assumptions, and limitations.
7. Update diagrams and data flows.
8. Verify documentation against the codebase.

Documentation must never describe a feature as implemented unless it has
been completed and validated.
