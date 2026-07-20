---
current_validated_milestone: 11
document: 00_ENGINEERING_BLUEPRINT
owner: Agentic Trading Desk Project
repository: agentic-trading-desk
review_required_after_every_milestone: true
status: Living Document
title: Engineering Blueprint
version: 1.0.0
---

# 00_ENGINEERING_BLUEPRINT

## Validated in Milestone 9

The Operations Center is a local read-only projection tier after the durable
journal. It observes sanitized immutable evidence and cannot call broker,
strategy, risk, portfolio, execution, or journal mutation surfaces. FastAPI,
WebSockets, and React provide supervision only; loopback binding is mandatory.

Planned and future control-plane, remote-access, and production deployment work
is not part of Milestone 9. Live trading and AI operational authority remain
prohibited.

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

-   Integrates cleanly with the IG.com API.
-   Uses deterministic mathematical models as the primary decision
    engine.
-   Uses AI as a research, review, and analysis layer.
-   Operates safely in the Demo environment before any live deployment.
-   Evolves through measurable milestones.
-   Produces transparent, reproducible trading decisions.

The platform should eventually operate continuously on a dedicated
machine while remaining observable, testable, and safe.

------------------------------------------------------------------------

# Mission

Engineer a system that can:

1.  Gather market data from IG.
2.  Validate and normalize market data.
3.  Detect market regimes.
4.  Generate deterministic trade candidates.
5.  Evaluate risk.
6.  Simulate strategies.
7.  Execute only when every required safety condition is satisfied.
8.  Record every decision for review and improvement.

------------------------------------------------------------------------

# Primary Goal

Every trade must be opened and closed because **all required conditions
align**, not because a single indicator produced a signal.

The platform must never rely on one model, one indicator, or one AI
response.

Instead, multiple independent components must agree before a trade
becomes eligible.

------------------------------------------------------------------------

# Decision Hierarchy

Trade lifecycle:

Market Data → Data Validation → Feature Engineering → Strategy Engine →
Regime Detection → Signal Engine → Risk Engine → Execution Decision →
Broker Adapter → Monitoring → Trade Journal

Failure at any stage prevents execution.

For Milestone 5, "execution" means local simulation only. The validated path is
Risk Engine approved intent -> Paper Portfolio -> append-only journal events ->
updated AccountRiskState. The Paper Portfolio has no broker or AI dependency,
cannot increase approved quantity, and values long positions at bid.

------------------------------------------------------------------------

# System Architecture

The platform is divided into independent modules.

## Broker Layer

Responsibilities:

-   OAuth authentication
-   Session management
-   Account retrieval
-   Market search
-   Market details
-   Historical prices
-   Position retrieval

Constraints:

-   Demo first
-   Read-only until execution milestone
-   Fail closed
-   Secret redaction
-   Strict endpoint allowlist

The broker layer must never contain trading logic.

------------------------------------------------------------------------

## Strategy Layer

Responsible for transforming market data into deterministic trade
candidates.

Current models include:

-   Existing baseline strategy
-   Kalman filter
-   Hidden Markov Model
-   Signal gating

Future models may include additional statistical techniques only after
validation.

------------------------------------------------------------------------

## Risk Layer

The validated deterministic Risk Engine is the sole authority for whether a
candidate may proceed and for the maximum permitted quantity.

Current responsibilities:

-   Position sizing
-   Exposure limits
-   Daily loss limits
-   Drawdown and position-count limits
-   Kill switch
-   Candidate, account, and market freshness
-   Market eligibility and dealing-rule validation

Account and market state are injected explicitly. Unknown state rejects. The
engine uses Decimal sizing, projected exposure, immutable decision records, and
expiring approved intents. It has no broker, HTTP, credential, AI, or execution
dependency.

No trade may bypass the risk engine.

------------------------------------------------------------------------

## Execution Layer

Execution is intentionally isolated.

Responsibilities:

-   Translate approved decisions into broker requests.
-   Confirm acknowledgements.
-   Record fills.
-   Detect failures.
-   Retry only where safe.

Execution does not decide whether to trade.

------------------------------------------------------------------------

## AI Layer

AI is an advisory subsystem.

Milestone 6 validates a disabled-by-default, provider-neutral AI Analyst. Only
deterministically sanitized structured records may cross its provider boundary.
Structured responses are policy-validated and appended without changing source
history. Provider failure is isolated from every deterministic workflow.

AI may:

-   Explain signals.
-   Summarize news.
-   Critique strategies.
-   Suggest research directions.
-   Detect inconsistencies.
-   Produce reports.

AI must not:

-   Override deterministic signals.
-   Override risk controls.
-   Place orders directly.
-   Change configuration automatically.
-   Modify historical results.

------------------------------------------------------------------------

# IG.com Integration Goals

The platform is designed around IG.com.

Objectives:

-   Stable OAuth authentication.
-   Clean session lifecycle.
-   Accurate market normalization.
-   Deterministic read-only data retrieval.
-   Safe transition to demo execution.
-   Eventually support controlled live execution without architectural
    redesign.

Broker integration should remain isolated so future brokers can be added
through adapters without changing the strategy engine.

------------------------------------------------------------------------

# Trade Alignment Model

A trade becomes eligible only when every required layer agrees.

Example pipeline:

1.  Market data valid.
2.  Instrument tradeable.
3.  Spread acceptable.
4.  Strategy warm-up complete.
5.  Baseline trend bullish.
6.  Kalman trend positive.
7.  HMM regime acceptable.
8.  Regime confidence above threshold.
9.  Risk checks pass.
10. Market session open.
11. Holding state allows entry.
12. Execution policy permits order creation.

If any mandatory gate fails:

Result = NO_TRADE.

------------------------------------------------------------------------

# AI Goals During Development

Every AI working on this repository should optimize for:

1.  Correctness before speed.
2.  Simplicity before complexity.
3.  Safety before profitability.
4.  Evidence before assumptions.
5.  Maintainability before shortcuts.

AI contributors should:

-   preserve modular architecture;
-   avoid introducing hidden state;
-   keep deterministic behavior;
-   expand test coverage with new functionality;
-   document architectural decisions;
-   preserve reproducibility.

They should not:

-   weaken safety checks;
-   remove validation;
-   bypass milestones;
-   add execution prematurely;
-   merge unrelated concerns.

------------------------------------------------------------------------

# Milestones

## M0

Planning and architecture.

## M1

Project foundation.

## M2

IG OAuth v3 demo read-only integration.

## M3

Deterministic strategy engine.

## M3.5

Leakage-controlled backtesting.

## M4

Risk engine.

## M5

Paper portfolio.

## M6

AI analyst.

## M7

Controlled IG Demo execution. The validated implementation is disabled by
default, long-only, risk-revalidated, one-attempt, and reconciled. Manual mode
is operator-confirmed; a separate bounded automated Demo mode requires dual
switches, strict limits, and persistent halt state. It does not include live
trading, closure, amendments, working orders, account switching, unbounded
automation, or AI authority.

## M8

Trade journal.

## M9

Monitoring dashboard.

## M10

Knowledge and memory.

## M11

Multi-agent architecture.

## M12

Production deployment.

## M13

Controlled live trading.

Each milestone must have documented objectives, acceptance criteria, and
regression tests before the next milestone begins.

------------------------------------------------------------------------

# Definition of Success

The system is successful when it:

-   makes reproducible decisions;
-   survives realistic costs and testing;
-   integrates reliably with IG.com;
-   protects capital through deterministic risk controls;
-   provides transparent reasoning for every trade;
-   allows AI to enhance analysis without replacing governance.

Profitability alone is not sufficient; engineering quality, safety, and
repeatability are equally important.

------------------------------------------------------------------------

# Documentation Governance

## Documentation is Part of Every Milestone

Project documentation is considered a core deliverable, not an optional
task. A milestone is **not complete** until its implementation,
automated tests, and documentation are all aligned.

### Definition of Done

A milestone is complete only when all of the following are true:

-   The implementation is complete.
-   Automated tests pass.
-   The implementation has been reviewed.
-   The architecture remains consistent.
-   Relevant documentation has been updated.
-   Future milestone references have been adjusted where necessary.
-   Known limitations and assumptions are documented.

If any of these conditions are not satisfied, the milestone remains **in
progress**.

## Mandatory Documentation Review

Immediately after every completed milestone:

1.  Review every affected document under `docs/`.
2.  Update any sections that describe the implemented functionality.
3.  Move completed features from "Planned" to "Validated
    Implementation".
4.  Update milestone status and roadmap.
5.  Record any architectural decisions introduced during the milestone.
6.  Record new constraints, assumptions, or limitations.
7.  Update diagrams and data flows if interfaces changed.
8.  Verify that the documentation accurately reflects the current
    codebase.

Documentation must never describe a feature as implemented unless it has
been completed and validated.

## Documentation Before Development

Before beginning a new milestone:

-   Review the relevant documentation.
-   Confirm the implementation plan aligns with the Engineering
    Blueprint.
-   Update the design documents if the approved architecture changes.
-   Do not begin implementation until the design and objectives are
    clearly documented.

This ensures the documentation remains the project's authoritative
engineering reference rather than a historical record created after
implementation.

## Bounded Automated Demo Observation

`MANUAL_CONFIRMED` remains the default controlled-execution mode. The separate
`AUTOMATED_DEMO` mode is disabled by default and needs dual explicit switches,
the exact Demo gateway, deterministic strategy and Risk approval, minimum
broker size, a protective stop, persistent idempotency, and a clear halt state.
One submission attempt is allowed. Live hosts, shorts, closure, amendment,
working orders, account switching, AI authority, and retry after ambiguity are
structurally unavailable. Real broker validation must not be claimed until a
naturally eligible Demo order confirms and reconciles.

## Validated Durable Evidence Boundary

Milestone 8 adds an explicit-path SQLite evidence store after the validated
Strategy, Risk, Paper, Demo Execution, and AI boundaries. Source models remain
authoritative and immutable; the journal wraps them in linked, versioned,
fingerprint-chained envelopes. Transactional batches, migrations, startup
integrity checks, amendments, deterministic reviews, cutoff-aware retrieval,
backups, and sanitized exports are validated. The journal cannot call a broker,
approve or execute a trade, or mutate upstream state. Semantic memory,
autonomous learning, cloud persistence, and live-memory feedback remain future.
# Milestone 7.5 - Market Context And Strategy Routing

**Validated:** deterministic session, liquidity, volatility, event, context,
registry, routing, capital-preservation, completed-bar scheduling, and
context-grouped reporting are implemented. Only the existing trend/regime
strategy is validated. **Research:** range, breakout, and post-news strategies
are isolated as `RESEARCH_ONLY`. **Future/prohibited:** AI selection, automatic
promotion, forced trades, and live trading remain unavailable.

## Validated in Milestone 10

The deterministic Demo lifecycle now extends confirmed-position evidence through
monitoring, exit evaluation, exact preflight, one close attempt, confirmation,
reconciliation, durable journaling, read-only operations projection, and post-trade
review. Authority remains isolated in the lifecycle engine. Live, short, partial,
amendment, retry, AI-exit, and dashboard-exit capabilities remain prohibited.

## Milestone 11 Validated Boundary

The deterministic Opportunity Engine scans six allowlisted FOREX markets across
completed 5-minute, 15-minute, and 1-hour bars. It estimates non-zero costs, computes
net expected value, suppresses duplicate/correlated exposure, and ranks at most three
candidates for Risk. It has no broker authority. Demo Exploration and the reporting
campaign are disabled by default and Live remains technically unavailable.

## Milestone 12 Controlled Portfolio Boundary

**Implemented:** independent deterministic evaluators cover trend, pullback, breakout,
and stable-range hypotheses through one typed contract. **Software-validated:** cutoff
enforcement, long-only results, lifecycle governance, artifact integrity, stress
models, breaker persistence, and read-only projections. **Not promotion-validated:**
the three new families lack an approved historical dataset and remain
`RESEARCH_ONLY`. Coverage expands without weakening Risk, execution, lifecycle, or
capital-preservation authority.
