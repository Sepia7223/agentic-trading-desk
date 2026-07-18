---
current_validated_milestone: 9
depends_on:
- 00_ENGINEERING_BLUEPRINT.md
- 01_SYSTEM_ARCHITECTURE.md
- 04_STRATEGY_ENGINE.md
- 07_RISK_ENGINE.md
document: 08_AI_ARCHITECTURE
owner: Agentic Trading Desk Project
review_required_after_every_milestone: true
status: Living Document
title: AI Architecture & Governance
version: 1.0.0
---

## Milestone 9 AI Review Center

Existing sanitized AI analysis records may be displayed read-only with the
label `AI authority: ADVISORY ONLY`. The UI cannot send recommendations into
strategy, risk, execution, or portfolio state. Provider configuration and
credentials are not dashboard dependencies. AI-generated operational actions
remain prohibited.

# Purpose

This document defines how AI participates in the Agentic Trading Desk.

AI is an advisory subsystem. It enhances research, explanations, and
operational efficiency but is not the authority for trading or risk
decisions.

# Current State

Validated: - Provider-neutral AI Analyst protocol. - Disabled-by-default local
analysis. - Deterministic sanitization and prompt policy. - Strict structured
responses. - Append-only analysis records. - Structured historical retrieval.
- Signal and risk explanation, trade review, portfolio summary, historical
comparison, anomaly review, research hypotheses, and periodic report modes.

Planned: - Optional isolated network provider adapter. - Durable journal
database. - Semantic retrieval for qualitative records. - Multi-agent
collaboration.

# Core Principles

-   Deterministic systems before AI.
-   AI augments human decision-making.
-   AI must be explainable.
-   AI outputs are advisory unless explicitly approved by a future
    milestone.
-   AI never bypasses architectural boundaries.

# Responsibilities

AI may:

-   Explain strategy decisions.
-   Summarize market context.
-   Review completed trades.
-   Identify recurring patterns.
-   Generate documentation.
-   Assist development.
-   Suggest future research.
-   Highlight anomalies for human review.

# Explicit Prohibitions

AI must never:

-   Place broker orders.
-   Override the Risk Engine.
-   Change configuration automatically.
-   Access secrets or credentials.
-   Modify historical records.
-   Skip validation gates.
-   Approve trades independently.
-   Create or confirm execution requests.
-   Trigger or retry broker submission.
-   Resolve reconciliation or mutate Demo positions.

# Interaction Model

The AI receives outputs from validated subsystems:

Market Data → Strategy Engine → Risk Engine → Monitoring → AI Analysis

AI does not alter upstream decisions.

Milestone 7 execution records may be explained after the deterministic workflow
finishes. The AI package does not import the execution adapter and cannot access
credentials, confirmation controls, idempotency state, or mutation methods.

# Validated AI Roles

## AI Analyst

Explains signals and market conditions.

## AI Research Assistant

Evaluates hypotheses and summarizes experiments.

## AI Reviewer

Reviews completed trades and identifies strengths and weaknesses.

# Provider and Sanitization Boundary

Provider access is abstract and disabled by default. The current implementation
has no OpenAI SDK or live provider adapter. Only sanitized structured data may
cross the port. Credentials, authorization data, raw broker responses, full
account identifiers, local paths, machine metadata, unsafe questions, future
records, and oversized requests fail before invocation.

Prompts are deterministic and versioned. Provider prose is inherently not
guaranteed reproducible, so every response is schema-validated, source-linked,
policy-checked, and fingerprinted without claiming deterministic generation.
Raw provider responses are not stored.

# Failure Isolation

Disabled, rejected, timed-out, malformed, or failed AI analysis returns a safe
typed status. Strategy output, Risk Decisions, approved intents, Paper Portfolio
state, and source journal history remain unchanged and continue independently.

## Future Multi-Agent System

Potential specialist agents:

-   Market
-   Strategy
-   Risk
-   Portfolio
-   Research
-   Operations
-   Review

Each agent will have defined interfaces and permissions.

# Governance

Every AI feature must:

-   Have a documented objective.
-   Preserve deterministic architecture.
-   Include automated tests where applicable.
-   Update project documentation.
-   Respect subsystem boundaries.

# Documentation Governance

After every AI-related milestone:

-   Update validated capabilities.
-   Record new AI responsibilities.
-   Record prohibited behaviors.
-   Update architectural diagrams.

No AI milestone is complete until implementation, tests, and
documentation remain aligned.

## Automated Demo Exclusion

No AI provider participates in automated Demo evaluation, candidate mapping,
risk approval, request creation, submission, confirmation, reconciliation, halt
management, or state recovery. AI may review sanitized immutable records only
after the deterministic lifecycle completes.

## Milestone 8 Journal Access

AI may receive the validated `ReadOnlyJournal` facade for sanitized,
cutoff-bounded records, lineage, deterministic summaries, and historical
comparisons. It has no append, amendment, update, delete, backup, broker, or
execution method through that facade. A separately authorized writer may append
a new immutable `AI_ANALYSIS` record, but AI cannot rewrite source evidence.
Raw provider responses remain prohibited. Embeddings, semantic vector search,
autonomous learning, and AI-deployed strategy or risk changes remain future.
# Milestone 7.5 AI Prohibition

AI cannot classify deterministic eligibility, select among strategies, assign trade
direction from news, alter context thresholds, promote a research strategy, or
override event and capital-preservation policy. A future AI provider may summarize
already sanitized structured news for human review only.

Economic-event eligibility is sourced from validated structured local records, not
from AI classification or sentiment. AI cannot fill missing calendar coverage,
declare a normal holiday state, or convert unavailable context into an eligible route.

## Milestone 10 AI Boundary

AI may review immutable completed lifecycle evidence after the fact. It cannot trigger
or confirm an exit, select quantity, alter precedence, change stop/target, clear a
persistent halt, submit/retry a close, reconcile broker state, or mutate source
records. Deterministic lifecycle completion does not depend on an AI provider.
