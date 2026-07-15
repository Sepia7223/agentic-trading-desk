---
title: Deterministic Risk Engine
document: 07_RISK_ENGINE
version: 1.0.0
status: Planned Specification
owner: Agentic Trading Desk Project
current_validated_milestone: "3 (Milestone 3.5 planned)"
review_required_after_every_milestone: true
---

# Purpose

This document specifies the planned deterministic Risk Engine. Risk is the final authority that decides whether a strategy candidate may proceed toward execution.

# Status

The Risk Engine is planned for Milestone 4 and is not currently implemented.

# Responsibilities

- validate account and portfolio state;
- calculate position size using deterministic rules;
- enforce per-trade, daily, instrument, sector, currency, and portfolio exposure limits;
- reject stale, incomplete, contradictory, or unknown state;
- enforce stop-distance and dealing-rule constraints;
- apply drawdown and loss-streak controls;
- maintain kill switches;
- emit an immutable approval or rejection record with reasons.

# Authority Boundary

Strategy may propose a candidate but cannot approve it. AI may explain or critique a risk decision but cannot modify it. Execution may accept only a valid, current, unexpired Risk Engine approval.

# Fail-Closed Conditions

No trade is permitted when account equity, available funds, open positions, market state, spread, dealing rules, portfolio exposure, current risk configuration, or required timestamps are missing or invalid.

# Planned Controls

- maximum risk per trade;
- maximum total open risk;
- maximum daily loss;
- maximum rolling drawdown;
- maximum instrument and correlated exposure;
- minimum reward-to-risk requirements where applicable;
- duplicate-position prevention;
- cooldowns after repeated losses or execution faults;
- emergency global kill switch;
- environment-specific limits for simulation, demo, and future live trading.

# Position Sizing

Position sizing must use explicit financial values and `Decimal` arithmetic where broker-facing precision matters. It must account for stop distance, contract size, currency conversion, minimum deal size, and configured caps. A model or language model must never choose final size.

# Outputs

Each decision should include a risk-decision ID, linked candidate ID, approval status, proposed size, effective limits, passed gates, failed gates, deterministic reasons, configuration fingerprint, and expiry timestamp.

# Testing

Tests must cover boundary values, missing state, stale approvals, numerical precision, exposure aggregation, drawdown controls, kill switches, duplicate requests, and invariants preventing AI or strategy bypass.

# Governance

Risk parameter or authority changes require tests, ADR review, documentation updates, and explicit milestone approval. Risk controls must never be weakened silently to improve backtest or paper-trading results.
