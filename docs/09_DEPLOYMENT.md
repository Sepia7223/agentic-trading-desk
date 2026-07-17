---
current_validated_milestone: 9 (Production deployment planned for Milestone 12)
depends_on:
- 00_ENGINEERING_BLUEPRINT.md
- 01_SYSTEM_ARCHITECTURE.md
- 07_RISK_ENGINE.md
- 08_AI_ARCHITECTURE.md
document: 09_DEPLOYMENT
owner: Agentic Trading Desk Project
review_required_after_every_milestone: true
status: Living Document
title: Deployment & Operations
version: 1.0.0
---

## Validated Local Operations Deployment

Milestone 9 supports local-only startup:

```powershell
python -m trading_desk.cli operations run --host 127.0.0.1 --port 8000 --journal <path>
```

The feature is disabled by default and configuration rejects non-loopback
hosts, including `0.0.0.0`. Remote authentication, TLS, cloud hosting,
containers, production broker access, and general production deployment remain
planned for later milestones.

# Purpose

This document defines how the Agentic Trading Desk will be deployed,
operated, monitored, and maintained from development through production.

Deployment is the final stage of the engineering lifecycle. No
production deployment may occur until all preceding milestones have been
validated.

# Current State

Validated: - Local development environment. - Demo-only broker
integration. - Read-only broker operations. - Disabled-by-default controlled
Demo opening with manual confirmation or hard-limited automated Demo policy.

Planned: - Dedicated 24/7 machine. - Docker deployment. - Monitoring. -
Automated restart. - Backup strategy. - Secure remote administration.

The Milestone 5 paper ledger currently uses deterministic in-memory storage and
explicit JSON event exports for local CLI workflows. SQLite, migrations,
automatic restart recovery, and production unattended operation remain planned. Paper
commands do not load broker credentials or connect to IG.

Milestone 7 does not create a daemon or deployment service. A real Demo order
requires an operator-invoked CLI command, controlled mode, explicit dual
enablement for automated mode, fresh typed state, and local credentials. The
automated suite uses mock transport; real operational validation remains
pending until an eligible Demo signal confirms and reconciles. Production
deployment and live-host configuration are prohibited.

# Deployment Principles

-   Safety before availability.
-   Repeatable deployments.
-   Immutable configuration where practical.
-   Secrets stored outside source control.
-   Environment-specific configuration.
-   Complete observability.

# Target Environments

## Development

Purpose: - Feature implementation. - Unit testing. - Integration
testing.

## Research

Purpose: - Backtesting. - Strategy experiments. - Model evaluation.

## Demo Trading

Purpose: - End-to-end validation using the IG Demo environment.

## Production

Purpose: - Controlled live trading after all approval milestones.

# Operational Requirements

The production platform should provide:

-   Automatic startup after reboot.
-   Health monitoring.
-   Log collection.
-   Time synchronization.
-   Scheduled backups.
-   Graceful shutdown.
-   Resource monitoring.
-   Alerting for critical failures.

# Security

-   Never commit secrets.
-   Principle of least privilege.
-   Separate demo and live credentials.
-   Encrypted remote access.
-   Regular dependency updates.

# Disaster Recovery

Planned capabilities:

-   Configuration backup.
-   Strategy configuration versioning.
-   Log retention.
-   Recovery documentation.
-   Rollback procedures.

# Documentation Governance

After every deployment-related milestone:

-   Update deployment procedures.
-   Record infrastructure changes.
-   Update security assumptions.
-   Record operational lessons learned.

Deployment documentation must always match the validated operational
environment.

## Demo Soak Operation

The bounded soak command is an operator-launched process, not a production
daemon. It runs at most 24 cycles with intervals of at least one hour and at
most one Demo order per day. Each cycle opens and clears its OAuth session.
Fingerprint-validated state lives under ignored `.trading-desk/` storage and
uses an exclusive lock; stale locks and integrity failures require human review.
No automatic restart, halt clearing, live deployment, or secret persistence is
provided.

## Milestone 8 Local Journal Operation

SQLite journal, backup, and export paths are always operator supplied; the
application does not create implicit home or working-directory storage. Startup
enforces schema version 2, allowed migrations, foreign keys, WAL where
appropriate, and integrity verification. Invalid evidence enters
recovery-read-only mode and is not silently repaired. Backups use SQLite's
consistent backup API, explicit existing destinations, checksums, verification,
and bounded retention. Cloud persistence, automatic scheduling, remote backup,
multi-user operation, and distributed streaming remain future.
# Milestone 7.5 Scheduler Operations

The scheduler is a bounded planner with explicit local state. It derives action and
completed-bar identities from UTC timestamps, deduplicates persisted action IDs, and
does not treat sleep timing as market identity. Runtime storage paths remain explicit.
Deployment must preserve one-writer state ownership, journal integrity, Demo-only
configuration, and fail-closed execution halts.

Automated Demo deployment must mount operator-maintained economic and holiday JSON
files outside tracked source and pass both paths explicitly. Each file must have a
source ID, UTC snapshot time, and coverage interval. Missing, malformed, stale, or
out-of-coverage files prevent command startup before credentials or network access.
