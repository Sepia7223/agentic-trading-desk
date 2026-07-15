---
title: Deployment and Operations
document: 09_DEPLOYMENT
version: 1.0.0
status: Planned Specification
owner: Agentic Trading Desk Project
current_validated_milestone: "2 (Milestone 3 planned)"
review_required_after_every_milestone: true
---

# Purpose

This document defines the planned deployment, operations, security, observability, and recovery standards for the Agentic Trading Desk.

# Status

Production deployment, autonomous operation, and live trading are not implemented. Current validated behavior is local, Demo-only, read-only broker integration plus deterministic baseline calculations.

# Environment Progression

1. Local development with synthetic and fixture data.
2. Local IG Demo read-only smoke testing.
3. Deterministic historical backtesting.
4. Paper portfolio operation.
5. Controlled IG Demo execution.
6. Long-running Demo observation and incident review.
7. Separately approved controlled live deployment.

No stage may be skipped.

# Deployment Principles

- immutable and versioned application releases;
- environment-specific configuration;
- secrets supplied outside source control;
- least-privilege credentials;
- explicit Demo/live separation;
- health checks and fail-closed startup;
- deterministic configuration fingerprints;
- structured logs without secrets;
- durable journals and backups;
- reproducible rollback.

# Runtime Safety

Startup must reject missing or contradictory environment, mode, broker, risk, or storage configuration. A long-running process must stop new trading activity when data is stale, broker state is uncertain, the journal cannot persist required records, risk state is unavailable, reconciliation fails, or a kill switch is active.

# Secrets

`.env` and equivalent local secret stores remain untracked. Production secrets should use an operating-system or managed secret store. Credentials must not enter Docker images, CI artifacts, logs, prompts, journals, dashboards, screenshots, or crash reports.

# Observability

Planned metrics include data freshness, strategy evaluation counts, candidate and rejection counts, risk decisions, execution attempts, broker latency, reconciliation status, open exposure, realized and unrealized P&L, journal persistence, AI request status, and kill-switch state.

# Recovery and Reconciliation

Recovery must begin from broker and journal truth rather than assuming local memory is correct. Before resuming future execution, the platform must reconcile accounts, positions, pending orders, recent confirmations, journal state, and risk exposure.

# Backups

Trade journals, configuration history, reports, and audit records require encrypted, tested backups. Restoration procedures must be exercised before live operation is considered.

# Controlled Live Trading

Live trading requires a dedicated milestone, separate credentials, restrictive capital limits, human approval, operational monitoring, reconciliation, tested shutdown procedures, and evidence from prolonged Demo operation. Live support must not be enabled by changing only a URL.

# Governance

Deployment changes require threat review, runbook updates, rollback plans, validation evidence, and documentation alignment.
