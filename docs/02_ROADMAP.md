---
current_validated_milestone: 4 (Milestone 5 planned)
depends_on:
- 00_ENGINEERING_BLUEPRINT.md
- 01_SYSTEM_ARCHITECTURE.md
document: 02_ROADMAP
owner: Agentic Trading Desk Project
review_required_after_every_milestone: true
status: Living Document
title: Project Roadmap
version: 1.0.0
---

# Purpose

This roadmap is the implementation plan for the Agentic Trading Desk. It
tracks validated milestones, planned milestones, objectives, and
completion criteria.

## Definition of Done

A milestone is complete only when: - Implementation is complete. - Tests
pass. - Documentation is updated. - Architecture is reviewed. - The
roadmap reflects the new validated state.

# Status

  Milestone                      Status
  ------------------------------ -------------
  M0 Planning                    ✅ Complete
  M1 Foundation                  ✅ Complete
  M2 IG Read-Only Integration    ✅ Complete
  M3 Strategy Engine             ✅ Complete
  M3.5 Backtesting               ✅ Complete
  M4 Risk Engine                 ✅ Complete
  M5 Paper Portfolio             ⏳ Planned
  M6 AI Analyst                  ⏳ Planned
  M7 Demo Execution              ⏳ Planned
  M8 Trade Journal               ⏳ Planned
  M9 Dashboard                   ⏳ Planned
  M10 Knowledge & Memory         ⏳ Planned
  M11 Multi-Agent Architecture   ⏳ Planned
  M12 Production Deployment      ⏳ Planned
  M13 Controlled Live Trading    ⏳ Planned

# Guiding Rules

-   Milestones are sequential.
-   No milestone bypasses earlier safety requirements.
-   Documentation must be reviewed after every completed milestone.
-   Completed work moves from Planned to Validated.
-   Future milestones must align with the Engineering Blueprint and
    System Architecture.

# Validated Milestone 3.5

Leakage-controlled backtesting now provides chronological walk-forward
evaluation, strict market-data validation, bid/ask fills, deterministic
costs, benchmarks, variant ablation, typed journals, and reproducible run
fingerprints. Research comparison is restricted to `VALIDATION`; a
tamper-evident frozen selection artifact is required to release the final
`TEST` split. Unresolved end-of-data positions are reported without
fabricating realized profit or loss.

# Validated Milestone 4

The deterministic local Risk Engine is the sole approval and quantity
authority for trade candidates. It uses injected account and market snapshots,
Decimal-only sizing, fail-closed freshness and state gates, daily-loss and
drawdown limits, projected exposure limits, position-count controls, a kill
switch, stable reason codes, and immutable expiring approved intents. It has no
broker, HTTP, credential, AI, or execution dependency.

# Next Active Milestone

## M5 Paper Portfolio

Paper Portfolio accounting remains planned. Milestone 4 decisions and approved
intents do not execute, mutate, or simulate broker positions.
