---
current_validated_milestone: 11
depends_on:
- 00_ENGINEERING_BLUEPRINT.md
- 01_SYSTEM_ARCHITECTURE.md
- 02_ROADMAP.md
document: 10_DEVELOPMENT_STANDARDS
owner: Agentic Trading Desk Project
review_required_after_every_milestone: true
status: Living Document
title: Development Standards
version: 1.0.0
---

# Purpose

## Milestone 9 Operations Standards

Monitoring domain logic remains independent from FastAPI and React. API routes
are versioned, GET-only, bounded, sanitized, and tested for 405 mutation
rejection. WebSocket events are typed immutable projections, never commands.
Frontend gates require Prettier, ESLint, TypeScript, Vitest, build, and included
Playwright tests in addition to all Python quality gates.

This document defines the engineering standards for every human and AI
contributor.

The goal is consistency, maintainability, safety, and reproducibility.

# Engineering Principles

-   Safety before speed.
-   Deterministic behavior before cleverness.
-   Simplicity before unnecessary complexity.
-   Documentation is part of the implementation.
-   Every change must be testable.

# Coding Standards

-   Python 3.12+
-   Strong type hints throughout.
-   Immutable models where practical.
-   Small, focused modules.
-   Explicit exceptions.
-   No hidden global state.
-   No silent failures.
-   `Decimal` for financial prices, quantities, money, ratios, and fractions.
-   Explicit caller-supplied UTC evaluation timestamps for deterministic decisions.
-   Canonical sorted serialization for reproducibility fingerprints.
-   Append-only monotonic event sequences for simulated portfolio state.
-   Liquidation-side bid marking for open long positions.
-   Atomic validation-before-commit for multi-record portfolio transitions.
-   Deterministic sanitization and versioned prompts before any AI provider boundary.
-   Strict structured AI responses with source links, advisory acknowledgment,
    canonical fingerprints, and operational-language policy validation.
-   Provider failures must be isolated from deterministic workflows.
-   Broker mutation must use the dedicated execution port and exact Demo allowlist.
-   Reserve immutable idempotency state before one submission attempt.
-   Re-run deterministic risk against fresh state immediately before submission.
-   Treat ambiguous submission as potentially executed and never retry automatically.
-   Require confirmation before acceptance and reconciliation before completion.

# Testing Standards

Every feature should include:

-   Unit tests.
-   Regression tests where applicable.
-   Deterministic test data.
-   Failure-path tests.
-   Safety-boundary tests.
-   Exact boundary tests at, below, and above financial limits.

All required quality gates must pass before merge:

-   ruff format
-   ruff lint
-   mypy
-   pytest
-   git diff --check

# Git Workflow

Branch naming examples:

-   feature/`<name>`{=html}
-   fix/`<name>`{=html}
-   docs/`<name>`{=html}
-   refactor/`<name>`{=html}

Commits should describe one logical change.

Do not mix unrelated changes.

# Documentation Standards

Every milestone must:

-   Update affected documentation.
-   Record architectural changes.
-   Record assumptions and limitations.
-   Update the roadmap if milestone status changes.

Documentation is part of the Definition of Done.

# AI Contribution Rules

Every AI contributor must:

-   Read the Engineering Blueprint.
-   Respect the System Architecture.
-   Preserve subsystem boundaries.
-   Keep deterministic behavior.
-   Expand tests when adding features.

AI must never:

-   Bypass architectural rules.
-   Introduce execution capabilities early.
-   Remove safety checks.
-   Ignore documentation updates.

# Review Checklist

Before completing work:

-   Implementation complete.
-   Tests pass.
-   Documentation updated.
-   Architecture reviewed.
-   Roadmap reviewed.
-   No secrets committed.
-   No unintended regressions.

# Documentation Governance

This document shall be reviewed whenever development standards or
engineering workflow change.

## Automated Demo Change Standard

Changes to automated Demo policy require tests for explicit authorization,
exact-host enforcement, quantity non-increase, stop preservation, order/day
limits, cooldown, loss/drawdown halts, one-attempt behavior, confirmation,
reconciliation, persistent idempotency, concurrent-run rejection, and secret
sanitization. A safe no-signal result must never be converted into a forced
trade for testing.

## Durable Journal Change Standard

Journal changes require tests for immutable configuration, schema and migration
transactions, restart persistence, chain and payload integrity, parents,
duplicate identity, atomic rollback, amendments, UTC review boundaries, cutoff
enforcement, deterministic similarity, backup verification, export redaction,
and absence of broker or credential dependencies. Never add update or hard
delete SQL for historical evidence. Migration failures roll back; corruption is
reported and never silently repaired. Source models are wrapped, not copied into
divergent journal-specific contracts.
# Milestone 7.5 Development Rules

Context, router, and scheduler code must remain deterministic, immutable, typed, and
cutoff-safe. Test DST transition weeks, event release/revision visibility, duplicate
bar suppression, restart behavior, metadata fingerprints, research isolation, and
capital preservation. No context package may import broker mutation, credentials,
AI authority, Risk approval, or execution submission code.

Operational provider tests must cover completed-boundary edges, future invariance,
quote validity/freshness, calendar freshness/coverage, holidays, event windows, source
fingerprints, router suppression, and runner behavior before Risk and submission.
Tests use local fixtures and mocked read-only transports only.

## Milestone 10 Verification Standard

Lifecycle changes require configuration, snapshot, precedence, preflight, mapping,
submission, confirmation, reconciliation, persistence, scheduler, journal, operations,
security, and mocked end-to-end tests. Tests must prove one-attempt behavior, no close
retry, persistent halt, full-close-only `SELL` mapping, GET-only dashboard authority,
and absence of live, short, amendment, AI, or journal-to-broker paths.

## Milestone 11 Standards

Opportunity modules must remain Decimal-based, immutable, strict, deterministic, and
free of broker/HTTP/credential dependencies. Tests cover the universe, configuration,
models, cost/EV scoring, suppression, ranking, persistence, orchestration, journal,
campaign, operations APIs, frontend, and static safety scans. All new Operations routes
must be GET-only and all mutation ambiguity remains one-attempt/no-retry.

## Milestone 12 Verification Standard

Strategy changes require candidate and rejection boundary tests, future-append and
higher-timeframe leakage tests, deterministic fingerprints, chronological windows,
locked final-test enforcement, costs, execution stress, portfolio ablations,
promotion-integrity tests, breaker restart tests, lifecycle-invalidation tests,
GET-only API/frontend checks, and static authority scans. Never tune against final-test
output or describe synthetic fixtures as promotion evidence. Material math,
configuration, regime, stop, target, or instrument changes require a new version.
