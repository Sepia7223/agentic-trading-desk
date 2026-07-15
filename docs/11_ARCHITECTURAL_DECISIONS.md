---
current_validated_milestone: 3.5 (Milestone 4 planned)
depends_on:
- 00_ENGINEERING_BLUEPRINT.md
- 01_SYSTEM_ARCHITECTURE.md
document: 11_ARCHITECTURAL_DECISIONS
owner: Agentic Trading Desk Project
review_required_after_every_milestone: true
status: Living Document
title: Architecture Decision Records
version: 1.0.0
---

# Purpose

This document records the significant architectural decisions made
throughout the project.

Every major decision should explain:

-   Context
-   Decision
-   Rationale
-   Trade-offs
-   Status
-   Affected milestones

This provides long-term engineering history for both human and AI
contributors.

------------------------------------------------------------------------

# ADR-001 --- IG.com as Initial Broker

**Status:** Accepted

## Context

The project required a broker with a documented API and a demo
environment.

## Decision

Use IG.com as the initial broker.

## Rationale

-   Mature API
-   Demo environment
-   OAuth v3 support
-   Clear separation between demo and live

## Trade-offs

Broker-specific adapter required.

Affected milestones:

-   M2+
-   Future execution milestones

------------------------------------------------------------------------

# ADR-002 --- Demo Before Live

**Status:** Accepted

## Decision

All development progresses through the IG Demo environment before any
live trading capability is introduced.

## Rationale

Reduces operational risk and allows safe validation.

------------------------------------------------------------------------

# ADR-003 --- Deterministic Before AI

**Status:** Accepted

## Decision

The deterministic strategy engine is the source of trade candidates. AI
provides analysis only.

## Rationale

Improves reproducibility, auditability, and safety.

------------------------------------------------------------------------

# ADR-004 --- Read-Only Before Execution

**Status:** Accepted

## Decision

Broker integration begins with read-only operations.

## Rationale

Validates connectivity and data quality before introducing execution
risk.

------------------------------------------------------------------------

# ADR-005 --- Modular Architecture

**Status:** Accepted

## Decision

Subsystems communicate through defined interfaces and may not bypass one
another.

## Rationale

Supports testing, maintainability, and future expansion.

------------------------------------------------------------------------

# ADR-006 --- Regime-Aware Strategy

**Status:** Accepted

## Decision

Use a deterministic baseline enhanced by a Kalman Filter and a
three-state Hidden Markov Model.

## Rationale

Combines trend estimation with statistical regime identification while
remaining explainable.

------------------------------------------------------------------------

# ADR-007 --- Documentation as a Deliverable

**Status:** Accepted

## Decision

A milestone is not complete until implementation, tests, and
documentation are aligned.

## Rationale

Prevents documentation drift and creates a durable engineering knowledge
base.

------------------------------------------------------------------------

# ADR-008 --- Frozen Final-Test Release

**Status:** Accepted

## Context

Allowing research comparison to inspect the final `TEST` period makes that
period available for iterative strategy selection.

## Decision

Variant comparison is restricted to `VALIDATION`. Releasing `TEST` requires a
tamper-evident frozen-selection artifact created from validation evidence. The
artifact fixes the variant, strategy and backtest configuration, dataset
identity, chronological splits, validation evidence, and authorization state.
Final testing evaluates only that frozen selection, and its results cannot be
accepted by the selection API.

## Rationale

This enforces the research/final-release boundary in code rather than relying
on researcher discipline or a bypassable Boolean option.

------------------------------------------------------------------------

# ADR-009 --- Fail-Closed End-Of-Data Positions

**Status:** Accepted

## Decision

End-of-data liquidation may use only the latest valid, tradeable exit quote
after position activation. If none exists, the backtest records an unresolved
position and does not fabricate a fill or realized P&L.

## Rationale

Non-tradeable or chronologically invalid prices are not executable evidence.
Explicit unresolved state preserves auditability and keeps metrics honest.

------------------------------------------------------------------------

# Adding Future ADRs

Every significant architectural change should add a new ADR using this
template:

## ADR-XXX --- Title

**Status:** Proposed \| Accepted \| Superseded \| Deprecated

### Context

### Decision

### Rationale

### Trade-offs

### Affected Milestones

### Related Documents

------------------------------------------------------------------------

# Governance

Review this document after every milestone.

Record all accepted architectural decisions before marking the milestone
complete.
