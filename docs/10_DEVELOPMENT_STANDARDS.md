---
title: Development Standards
document: 10_DEVELOPMENT_STANDARDS
version: 1.1.0
status: Living Document
owner: Agentic Trading Desk Project
current_validated_milestone: "2 (Milestone 3 planned)"
review_required_after_every_milestone: true
---

# Purpose

This document defines mandatory engineering standards for every human and AI contributor.

# Required Reading Before Architectural Work

1. `docs/00_ENGINEERING_BLUEPRINT.md`
2. `docs/01_SYSTEM_ARCHITECTURE.md`
3. `docs/02_ROADMAP.md`
4. The subsystem-specific document relevant to the task
5. `docs/10_DEVELOPMENT_STANDARDS.md`
6. `docs/11_ARCHITECTURAL_DECISIONS.md`
7. `AGENTS.md`

# Pre-Work Procedure

- identify the repository, current branch, and base commit;
- inspect `git status` and avoid overwriting unrelated work;
- read relevant implementation and tests before editing;
- state the intended scope and protected boundaries;
- never inspect `.env` or request credentials;
- do not add execution or live capabilities unless the active milestone explicitly authorizes them.

# Python Standards

- Python 3.12 or newer;
- `src/` layout and explicit package boundaries;
- complete type hints on public interfaces;
- strict, frozen Pydantic models where appropriate;
- `Decimal` for broker-facing financial values and precision-sensitive calculations;
- timezone-aware timestamps except documented broker fields that contain only a time-of-day;
- immutable configuration and canonical fingerprints;
- `SecretStr` for sensitive values;
- `httpx` confined to broker adapter code;
- no raw dictionary leakage across domain boundaries;
- no hidden global state or silent exception suppression;
- deterministic random seeds for model fitting and tests.

# Safety Standards

Code must fail closed on unknown broker, market, position, portfolio, model, journal, or risk state. Strategy cannot call Broker. AI cannot call Broker or override Risk. No execution endpoint may be introduced before an explicitly reviewed milestone.

# Quantitative Standards

- no future-data leakage;
- no same-bar fills;
- chronological fitting and evaluation;
- untouched final test data;
- explicit costs and assumptions;
- benchmark and ablation comparisons;
- reproducible configurations;
- honest reporting of negative and inconclusive results.

# Testing Standards

Each behavioral change requires tests covering the successful path, invalid inputs, failure paths, boundary values, determinism, security boundaries, and regressions. Safety checks should include scans for mutation endpoints, production hosts, secret-like values, and forbidden imports where applicable.

Required verification:

```bash
python -m ruff format --check .
python -m ruff check .
python -m mypy
python -m pytest
git diff --check
```

# Git Standards

Use focused branches such as `feature/...`, `fix/...`, or `docs/...`. Do not make direct unreviewed changes to `main`. Keep commits scoped, do not stage credentials or generated artifacts, inspect the diff before commit, and use a pull request for review.

# Documentation Standards

Every milestone must update affected specifications, roadmap status, ADRs, assumptions, limitations, interfaces, and acceptance criteria. Planned functionality must never be described as implemented.

> A milestone is not complete until implementation, tests, architecture, and affected documentation are aligned.

# Prohibited Practices

- committing or displaying secrets;
- weakening tests or safety gates to obtain a pass;
- tuning on final test data;
- automatic strategy mutation from AI output;
- untyped broker payloads escaping the adapter;
- undocumented architecture changes;
- claims of profitability without reproducible evidence and realistic costs.

# Review Checklist

Before completion, confirm scope, types, tests, security, determinism, leakage controls, documentation, roadmap, ADR impact, absence of secrets, and absence of unintended runtime behavior changes.
