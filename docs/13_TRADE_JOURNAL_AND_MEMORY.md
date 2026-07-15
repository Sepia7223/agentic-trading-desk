---
title: Trade Journal, Review & Memory
document: 13_TRADE_JOURNAL_AND_MEMORY
version: 1.0.0
status: Planned Specification
owner: Agentic Trading Desk Project
current_validated_milestone: "2 (Milestone 3 planned)"
implementation_status: Planned
review_required_after_every_milestone: true
---

# Purpose

This document defines automated trade journaling, post-trade review, historical trade retrieval, and AI-assisted trade memory.

Every evaluated opportunity, rejected signal, simulated trade, Demo trade, and future live trade should become a permanent, reviewable, and searchable record. The system must be able to answer: **Have we seen similar conditions before, and what happened?**

Historical memory is advisory. It must never mutate strategy or risk configuration automatically.

# Current State

## Validated

Validated foundations include deterministic baseline outputs, read-only IG market data, and normalized broker-domain models. Regime-aware strategy outputs and configuration fingerprints are planned for Milestone 3.

## Planned

Persistent journals, automated post-trade review, semantic search, pre-session historical review, chart storage, and AI review reports are planned and not implemented.

# Approved Architecture

```text
Market Data
→ Validation
→ Strategy Engine
→ Risk Engine
→ Execution or Simulation
→ Trade Journal
→ Review Engine
→ Historical Memory
→ AI Analyst
```

The journal cannot become a hidden decision engine or bypass deterministic validation, risk, or execution policy.

# Record Types

## Signal Record

Stores signal ID, instrument and EPIC, evaluation and data-cutoff timestamps, strategy variant, configuration fingerprint, baseline values, Kalman outputs, HMM probabilities and mapped regime, gate results, final action, and rejection reasons.

## Risk Decision Record

Stores risk-decision ID, candidate ID, approval or rejection, proposed size, exposure and daily-risk state, kill-switch state, passed and failed gates, reasons, configuration fingerprint, and expiry.

## Execution Record

Stores execution ID, candidate and risk-decision links, environment, intended action, sanitized request summary, sanitized broker response, deal reference when applicable, acceptance status, and timestamps. Credentials, tokens, and raw authorization data are forbidden.

## Trade Record

Stores trade ID, linked signal/risk/execution IDs, instrument, direction, entry and exit timestamps and prices, quantity, gross and net P&L, spread, slippage, commission, funding, holding period, exit reason, environment, strategy variant, and configuration fingerprint.

## Post-Trade Review Record

Stores MFE, MAE, realized return, intra-trade drawdown, regime at entry and exit, process-rule compliance, risk-rule compliance, execution quality, failure modes, similar historical cases, AI review, human review, and lessons.

# Automated Review Workflow

After every closed trade:

1. finalize the immutable trade record;
2. calculate performance and cost metrics;
3. compare expected and actual execution;
4. classify process quality independently from financial outcome;
5. retrieve similar historical trades;
6. generate a structured review;
7. persist the review and amendments;
8. include the evidence in later daily, weekly, and monthly summaries.

# Pre-Session Historical Review

Before future automated trading begins, the program may review recent trades and comparable cases by instrument, strategy variant, HMM regime, Kalman slope, spread, volatility, session, holding state, and rejection reason.

The review may summarize historical sample size, win rate, net return, holding time, costs, common failure patterns, and uncertainty. It cannot change thresholds, limits, sizing, permissions, or configuration.

# Similarity Search

Structured filters and numerical distance take priority for trading evidence. Semantic embeddings may support qualitative notes, AI explanations, human comments, and lesson retrieval. Every result must preserve links to original records and timestamps.

# Data Integrity

Records should be append-only where practical, timestamped, versioned, linked by immutable IDs, and reproducible from configuration fingerprints. Corrections create amendment records instead of silently rewriting historical facts. Losing trades and failed signals may never be deleted to improve statistics.

# Storage

Initial implementation should use SQLite behind a typed repository and migration layer with encrypted backups. A future deployment may use PostgreSQL, object storage for charts, and vector search, while preserving the same domain interfaces.

# Review Cadence

- **Per trade:** outcome, process, execution, costs, MFE/MAE, and similar cases.
- **Daily:** opportunities, candidates, rejections, trades, P&L, open exposure, rule violations, and errors.
- **Weekly:** performance by instrument, variant, and regime; cost analysis; recurring failures; outliers.
- **Monthly:** net performance, drawdown, risk-adjusted metrics, strategy stability, execution quality, drift indicators, and controlled research recommendations.

# Classification

Process quality:

- `VALID_PROCESS`
- `RULE_VIOLATION`
- `EXECUTION_ERROR`
- `DATA_ERROR`
- `RISK_ERROR`
- `UNKNOWN`

Financial outcome:

- `WIN`
- `LOSS`
- `BREAKEVEN`

A profitable trade can be bad process. A losing trade can be valid process.

# Milestone Placement

- M3.5 backtests begin producing immutable simulated signal and trade records.
- M5 Paper Portfolio uses the journal as its audit trail.
- M5.5 implements Trade Intelligence and Historical Memory.
- M6 AI consumes journal evidence in read-only advisory mode.
- M7 and later execution use the same journal interfaces.

# Acceptance Criteria

The milestone is complete only when every signal and rejection can be reconstructed, each trade links to its decision chain, gross and net performance and costs are preserved, reviews are generated, similar cases can be retrieved, AI access is read-only, amendments are auditable, tests verify integrity, and no configuration changes automatically.

# Explicit Prohibitions

The subsystem may never expose secrets, rewrite history, remove unfavorable evidence, change risk or strategy parameters, execute trades, claim causation from weak correlations, or use future outcomes during pre-trade analysis.
