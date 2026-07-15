---
title: AI Architecture and Governance
document: 08_AI_ARCHITECTURE
version: 1.0.0
status: Planned Specification
owner: Agentic Trading Desk Project
current_validated_milestone: "3 (Milestone 3.5 planned)"
review_required_after_every_milestone: true
---

# Purpose

This document defines the planned role, interfaces, and safety boundaries of AI within the Agentic Trading Desk.

# Status

Runtime AI analysis is not currently implemented. The repository uses Codex as a development tool, while a future OpenAI API integration is planned for advisory analysis after deterministic backtesting, risk, paper portfolio, and trade-memory foundations exist.

# Permitted AI Roles

The AI Analyst may:

- explain deterministic strategy and risk outputs;
- summarize market and portfolio context from sanitized data;
- review historical signals and trades;
- retrieve and compare similar past cases;
- generate daily, weekly, and monthly review narratives;
- identify recurring process or execution problems;
- propose research hypotheses and test plans;
- flag anomalies for human review.

# Prohibited AI Roles

The AI Analyst may not:

- access IG credentials, API keys, passwords, OAuth values, or raw authorization headers;
- call IG or any broker adapter;
- place, modify, close, or confirm orders;
- approve risk or choose final position size;
- override deterministic gates or kill switches;
- change production configuration automatically;
- hide losing trades or rewrite journal history;
- train or tune the strategy using future outcomes;
- promote a research hypothesis directly into trading behavior.

# Approved Data Flow

```text
Validated Market/Strategy/Risk/Journal Data
→ Sanitization and Policy Enforcement
→ Read-Only AI Context
→ Structured Advisory Output
→ Human or Controlled Research Workflow
```

AI output is never an execution authorization.

# Structured Output

AI responses should use typed schemas containing fields such as summary, evidence, uncertainties, historical comparisons, anomalies, research hypotheses, and advisory status. Free-form prose must not be interpreted as a broker instruction.

# Historical Memory

Before future trading sessions, AI may review recent activity and retrieve comparable historical trades by instrument, strategy variant, regime, volatility, spread, time window, and process classification. Such review remains advisory and may not alter protected thresholds, sizing, or permissions.

# Data Minimization

Only the minimum sanitized context required for analysis may be sent to an AI provider. Secrets, raw broker payloads, unnecessary account identifiers, and sensitive operational data remain local.

# Research Promotion Process

An AI-proposed improvement must be translated into an explicit deterministic hypothesis, implemented on a research branch, backtested chronologically, reviewed for leakage and costs, validated on untouched data, documented, and approved before it can affect any strategy or risk configuration.

# Multi-Agent Future

Future specialist agents may support market research, quantitative review, risk critique, execution diagnostics, and journal analysis. They remain behind the same policy boundary and cannot form a path around deterministic authority.

# Governance

Any change to AI permissions, provider data, prompts, schemas, or integration points requires security review, tests, ADR updates, and documentation changes before milestone completion.
