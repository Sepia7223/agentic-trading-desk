---
title: Architecture Decision Records
document: 11_ARCHITECTURAL_DECISIONS
version: 1.1.0
status: Living Document
owner: Agentic Trading Desk Project
current_validated_milestone: "2 (Milestone 3 planned)"
review_required_after_every_milestone: true
---

# Purpose

This document records significant architectural decisions, their rationale, trade-offs, status, and affected milestones.

# ADR-001 — IG.com as Initial Broker

**Status:** Accepted

Use IG.com as the initial broker because it provides a documented API and Demo environment. The trade-off is a broker-specific adapter that must remain isolated behind provider-neutral ports.

# ADR-002 — Demo Before Live

**Status:** Accepted

All broker development and execution validation must progress through the IG Demo environment before any controlled live capability is considered.

# ADR-003 — Deterministic Systems Before AI

**Status:** Accepted

Deterministic code produces strategy and risk decisions. AI is an advisory research and review layer and cannot approve or execute trades.

# ADR-004 — Read-Only Before Execution

**Status:** Accepted

The initial broker integration supports authentication and read-only market/account operations only. Execution requires a separate milestone, ports, policies, tests, and review.

# ADR-005 — No Subsystem Bypass

**Status:** Accepted

Strategy, AI, dashboards, journals, and workflow controllers cannot call the broker directly or bypass the deterministic Risk Engine.

# ADR-006 — Regime-Aware Strategy

**Status:** Accepted

Use a deterministic baseline enhanced by a local-linear Kalman filter and a three-state Gaussian HMM. Their incremental value must be measured through ablation and out-of-sample testing.

This decision defines the planned Milestone 3 architecture; it does not claim that the regime-aware implementation is present in the Milestone 2 codebase.

# ADR-007 — Leakage-Controlled Backtesting Before Risk and Execution

**Status:** Accepted

Milestone 3.5 must establish chronological walk-forward evaluation, next-valid-bar fills, realistic costs, benchmarks, and untouched final testing before the platform advances.

# ADR-008 — Documentation Is a Deliverable

**Status:** Accepted

A milestone is not complete until implementation, tests, architecture, roadmap, and affected documentation agree.

# ADR-009 — Append-Only Trade Evidence and Historical Memory

**Status:** Accepted as planned architecture

Signals, risk decisions, executions, trades, reviews, and amendments should form an immutable or append-only audit trail. Historical retrieval and AI analysis remain read-only and cannot change strategy or risk configuration automatically.

# ADR-010 — Process Quality Is Separate From Financial Outcome

**Status:** Accepted as planned architecture

A profitable trade may still violate process, and a losing trade may still follow valid process. Journal classification must preserve both dimensions independently.

# Future ADR Template

## ADR-XXX — Title

**Status:** Proposed | Accepted | Superseded | Deprecated

### Context

### Decision

### Rationale

### Trade-offs

### Affected Milestones

### Related Documents

# Governance

Review this document after every milestone and before any significant change to broker authority, strategy models, risk controls, execution, AI permissions, storage, or deployment.
