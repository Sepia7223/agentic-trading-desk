---
current_validated_milestone: 6 (Deployment planned for Milestone 12)
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

# Purpose

This document defines how the Agentic Trading Desk will be deployed,
operated, monitored, and maintained from development through production.

Deployment is the final stage of the engineering lifecycle. No
production deployment may occur until all preceding milestones have been
validated.

# Current State

Validated: - Local development environment. - Demo-only broker
integration. - Read-only broker operations.

Planned: - Dedicated 24/7 machine. - Docker deployment. - Monitoring. -
Automated restart. - Backup strategy. - Secure remote administration.

The Milestone 5 paper ledger currently uses deterministic in-memory storage and
explicit JSON event exports for local CLI workflows. SQLite, migrations,
automatic restart recovery, and unattended operation remain planned. Paper
commands do not load broker credentials or connect to IG.

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
