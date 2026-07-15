---
title: Project Roadmap
document: 02_ROADMAP
version: 1.1.0
status: Living Document
owner: Agentic Trading Desk Project
current_validated_milestone: "2 (Milestone 3 planned)"
review_required_after_every_milestone: true
---

# Purpose

This roadmap tracks validated, planned, and future milestones for the Agentic Trading Desk.

# Definition of Done

A milestone is complete only when implementation is complete, required tests pass, architecture is reviewed, affected documentation is updated, assumptions and limitations are recorded, and the roadmap reflects the validated state.

# Milestones

| Milestone | Scope | Status |
|---|---|---|
| M0 | Planning and safety constitution | Complete |
| M1 | Python foundation and deterministic baseline | Complete |
| M2 | IG OAuth v3 Demo read-only integration | Complete |
| M3 | Regime-aware strategy engine | Planned |
| M3.5 | Leakage-controlled backtesting | Planned |
| M4 | Deterministic risk engine | Planned |
| M5 | Paper portfolio | Planned |
| M5.5 | Trade intelligence and historical memory | Planned |
| M6 | AI analyst in advisory mode | Planned |
| M7 | Controlled IG Demo execution | Planned |
| M8 | Operational trade journal and reporting expansion | Future |
| M9 | Monitoring dashboard | Future |
| M10 | Knowledge and research workflows | Future |
| M11 | Multi-agent research architecture | Future |
| M12 | Production deployment and operations | Future |
| M13 | Controlled live trading | Future |

# Next Active Milestone: M3

Milestone 3 adds deterministic regime-aware analysis to the validated baseline. Its planned scope includes a local-linear Kalman trend model, a three-state Gaussian HMM, chronological feature construction, semantic regime mapping, mandatory fail-closed gates, and reproducible configuration fingerprints. Its outputs remain analysis-only and cannot contain order or position-sizing instructions.

# Following Milestone: M3.5

Milestone 3.5 builds the evidence layer used to decide whether any strategy deserves further development.

Required capabilities:

- chronological and walk-forward evaluation;
- explicit train, validation, and untouched test periods;
- no future-data leakage or same-bar fills;
- next-valid-bar execution;
- bid/ask, spread, slippage, commission, and funding assumptions;
- deterministic reproducibility;
- benchmark comparison and strategy ablation;
- simulated signal and trade records suitable for later journaling;
- metrics including net return, drawdown, Sharpe, Sortino, profit factor, turnover, exposure, and trade count.

External controls should include a simple trend-following benchmark and an appropriately scoped mean-reversion benchmark. They are controls, not assumed profitable strategies.

# Sequence Rule

The project must not skip directly to AI or execution. Backtesting precedes deterministic risk; deterministic risk precedes paper portfolio; journaling and historical memory precede AI-assisted pre-session review; demo execution precedes any live capability.

# Documentation Governance

Review this file after every milestone. Move features from Planned to Validated only after code, tests, and review support the claim.
