---
current_validated_milestone: 7
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
  M5 Paper Portfolio             Complete
  M6 AI Analyst                  Complete
  M7 Demo Execution              Complete
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

# Validated Milestone 5

## M5 Paper Portfolio

The local-only Paper Portfolio consumes intact, unexpired approved intents,
simulates long position lifecycle events, uses liquidation-side marks, prevents
approval replay, and reconciles Decimal cash, P&L, exposure, and equity from a
fingerprint-chained append-only ledger. It projects deterministic AccountRiskState
snapshots for the next Risk Engine evaluation. Missing valid quotes leave
positions unresolved rather than fabricating realized P&L.

# Validated Milestone 6

The provider-neutral AI Analyst explains, reviews, compares, and proposes
research from sanitized deterministic records. Analysis and network providers
default to disabled. Requests, prompts, responses, and append-only analysis
records are strict and fingerprinted. AI cannot approve, size, execute, mutate,
or override, and provider failure cannot block deterministic workflows.

# Validated Milestone 7

Controlled IG Demo execution is implemented behind a dedicated mutation port.
It opens only one explicitly enabled, operator-confirmed long market position,
revalidates the Risk Engine against fresh state, never increases quantity,
attempts submission once, requires broker confirmation, reconciles read-only
positions, and writes linked append-only records. Automated validation uses
mock transport. A disabled-by-default `AUTOMATED_DEMO` observation mode adds
dual enable switches, one-order daily/cycle limits, cooldown, strict loss,
drawdown, exposure and quantity limits, persistent halt/idempotency state, and
no-retry reconciliation. Real operational validation remains pending until a
naturally eligible signal completes the Demo lifecycle.

# Next Active Milestone

Milestone 8, durable Trade Journal integration, remains planned. Live trading,
unbounded automation, closure, amendment, working orders, account switching,
short execution, and AI execution authority remain unavailable.
