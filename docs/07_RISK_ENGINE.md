---
current_validated_milestone: 3 (Risk Engine planned for Milestone 4)
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

Validated: - Risk boundaries defined in architecture only.

Planned for Milestone 4: - Position sizing - Exposure limits - Daily
loss limits - Portfolio constraints - Kill switch - Duplicate trade
protection - Session validation - Maximum concurrent positions

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

# Inputs

-   Trade candidate
-   Strategy output
-   Account state
-   Portfolio state
-   Market state
-   Risk configuration

# Outputs

-   APPROVED
-   REJECTED

Every rejection must include structured reasons.

# Planned Validation Gates

Typical approval gates include:

-   Account enabled
-   Demo/live mode allowed
-   Market tradeable
-   Session open
-   Exposure within limits
-   Position size valid
-   Daily loss limit not exceeded
-   Portfolio concentration acceptable
-   Duplicate trade prevention
-   Kill switch inactive

Failure of any mandatory gate results in REJECTED.

# Explicit Prohibitions

The Risk Engine must never:

-   Generate trading signals
-   Authenticate with IG
-   Execute orders
-   Override broker responses
-   Allow AI to bypass deterministic rules

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
