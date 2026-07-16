---
current_validated_milestone: 7
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
