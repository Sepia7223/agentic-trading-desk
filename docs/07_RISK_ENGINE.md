---
current_validated_milestone: 4 (Milestone 5 planned)
depends_on:
- 00_ENGINEERING_BLUEPRINT.md
- 01_SYSTEM_ARCHITECTURE.md
- 04_STRATEGY_ENGINE.md
- 06_BACKTESTING.md
document: 07_RISK_ENGINE
owner: Agentic Trading Desk Project
review_required_after_every_milestone: true
status: Living Document
title: Risk Engine Specification
version: 1.0.0
---

# Purpose

This document defines the deterministic Risk Engine that governs whether
a trade candidate may proceed toward execution.

The Risk Engine is the final approval authority before the Execution
Engine.

No trade may bypass this subsystem.

# Current State

## Validated

-   Strict immutable candidate, account-state, market-state, configuration,
    decision, gate, and approved-intent models.
-   Explicit UTC evaluation timestamp with no hidden wall-clock access.
-   Decimal-only risk budgets, per-unit risk, quantity, money, ratio, and
    projected exposure calculations.
-   Candidate and market freshness, tradeability, bid/ask, spread, holding,
    entry/stop, account completeness, daily-loss, drawdown, consecutive-loss,
    position-count, quantity, and exposure gates.
-   Stable status and reason-code contracts for every rejection.
-   Canonical SHA-256 configuration, input, and decision fingerprints.
-   Immutable approved intents that are invalid at or after expiry.

## Planned

Paper Portfolio accounting is planned for Milestone 5. Broker order execution,
position mutation, live trading, and runtime AI remain unavailable.

# Engineering Philosophy

The Risk Engine is deterministic.

Risk management is **never delegated to AI**.

Every decision must be reproducible and independently testable.

# Responsibilities

The Risk Engine shall:

-   Evaluate every trade candidate.
-   Validate account constraints.
-   Validate portfolio constraints.
-   Validate market availability.
-   Reject unsafe trades.
-   Produce deterministic approval decisions.
-   Determine the maximum permitted long quantity.
-   Reject every unknown or incomplete required state.

# Inputs

-   Trade candidate
-   Strategy output
-   Account state
-   Portfolio state
-   Market state
-   Risk configuration

Account and market state are supplied by the caller. The Risk Engine never
fetches, repairs, or infers them.

# Outputs

-   APPROVED
-   REJECTED
-   EXPIRED
-   KILL_SWITCHED
-   INVALID_INPUT

Every rejection must include structured reasons.

# Validated Gate Order

1.  Input integrity.
2.  Kill switch.
3.  Strategy/risk configuration fingerprints.
4.  Candidate freshness.
5.  Market and account snapshot freshness.
6.  Market eligibility and quote consistency.
7.  Known-flat holding state.
8.  Long entry and stop relationship.
9.  Complete account state.
10. Daily loss, drawdown, and consecutive losses.
11. Portfolio and instrument position counts.
12. Risk budget and raw size.
13. Quantity constraints and round-down.
14. Projected gross, instrument, and asset-class exposure.
15. Final risk recalculation.

The kill switch always prevents approval. Unknown holding, account, market,
dealing-rule, quote, P&L, exposure, or count state rejects.

Failure of any mandatory gate produces a non-approved typed status with at
least one stable reason code.

# Deterministic Sizing

```text
risk_budget = account_equity * risk_per_trade_fraction
risk_per_unit = abs(entry_reference - stop_reference) * value_per_price_unit
raw_quantity = risk_budget / risk_per_unit
approved_quantity = floor(constrained_quantity / increment) * increment
```

The constrained quantity is the minimum of raw size, configured maximum,
available-capital capacity, and projected gross/instrument/asset-class exposure
capacity. It must also satisfy the broker minimum deal size and compatible
configured/market increments. Quantity always rounds down. Final risk and
notional exposure are recalculated after rounding.

Available capital is conservatively treated as a notional ceiling because no
instrument-specific margin model exists yet.

# Loss And Exposure Policies

Realized-only mode compares realized daily loss with its configured fraction.
Total-loss mode additionally compares realized plus unrealized loss with the
total-loss fraction. Equality reaches the limit and rejects. Drawdown and
consecutive-loss equality also reject.

Exposure checks use projected post-trade gross, instrument, and asset-class
notional against fractions of account equity. Current exposure alone is never
sufficient for approval.

# Decision And Journal Contract

Every evaluation produces an immutable `RiskDecision` with IDs, timestamps,
status, proposed and approved quantities, risk budget, final risk, notional,
gate results, stable reason codes, snapshot IDs, fingerprints, policy, and
expiry. An approval also contains an immutable `ApprovedTradeIntent`; it is not
an order and is invalid at or after expiry.

# Explicit Prohibitions

The Risk Engine must never:

-   Generate trading signals
-   Authenticate with IG
-   Execute orders
-   Override broker responses
-   Allow AI to bypass deterministic rules
-   Fetch account or market state
-   Load environment credentials
-   Import HTTP or broker clients
-   Persist directly to SQLite

# AI Interaction

AI may:

-   Explain a rejection
-   Summarize risk
-   Suggest research

AI may not:

-   Change limits
-   Approve trades
-   Override the Risk Engine

# Documentation Governance

After every milestone affecting risk management:

-   Update validated capabilities.
-   Record new limits.
-   Record approval gates.
-   Record assumptions and limitations.
-   Synchronize this document with the implementation.

A risk milestone is not complete until implementation, tests, and
documentation agree.
