---
current_validated_milestone: 11
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
  M7.5 Context & Router          Complete
  M8 Trade Journal               Complete
  M9 Dashboard                   Complete
  M10 Knowledge & Memory         ⏳ Planned
  M11 Multi-Agent Architecture   ⏳ Planned
  M12 Production Deployment      ⏳ Planned
  M13 Controlled Live Trading    ⏳ Planned

# Guiding Rules

-   Safety dependencies are sequential. A fractional milestone may land later in
    repository history when it is based on every completed dependency and the
    ordering is documented explicitly.
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

# Validated Milestone 7.5

Milestone 7.5 was implemented on top of the completed Milestone 8 lineage. This
repository-history ordering does not bypass a safety dependency. Validated:
completed-bar scheduling, UTC/DST sessions, observable liquidity, causal volatility,
structured event windows, deterministic registry/router, explicit capital
preservation, research isolation, and context-aware historical reporting. Research
only: range mean reversion, volatility breakout, and post-news continuation. Any
promotion remains future work and requires separate review.

# Validated Milestone 8

The durable local Trade Journal wraps validated immutable source records in a
versioned envelope and persists them to SQLite with transactions, foreign keys,
WAL, deterministic Decimal-safe serialization, source linkage, and a global
SHA-256 fingerprint chain. Amendments preserve originals; hard deletion and
source-record updates are unavailable. Restart verification, recovery-read-only
mode, deterministic post-trade and UTC periodic reviews, cutoff-aware queries,
normalized-distance comparison, consistent backups, and sanitized JSONL, CSV,
and Markdown exports are validated. AI access is read-only.

# Validated Milestone 9

The loopback-only Operations Center provides a GET-only FastAPI API, sanitized
WebSocket events, and a React/TypeScript dashboard over immutable journal and
typed runtime projections. System, context, router, deterministic why-no-trade,
risk, execution, position, trade, performance, alert, journal, replay, search,
and redacted configuration views are validated. WebSocket events refresh
authoritative REST projections; execution stages and no-trade decisions are
joined through immutable lineage; open Paper and Demo positions use current or
reconciled evidence; performance includes drawdown, costs, exposure, turnover,
and available context breakdowns; and bounded sanitized exports return JSONL,
CSV, or Markdown attachments. It has no operational authority.

# Next Active Milestone

Milestone 11 is software-validated on the Milestone 10 lineage. Semantic vector search, autonomous
learning or parameter changes, cloud persistence, live trading, unbounded
automation, closure, working orders, account switching, short execution, and AI
execution authority remain future and unavailable.

Operational context wiring for Milestone 7.5 is software-validated with deterministic
and mocked read-only inputs. Real IG Demo execution validation remains incomplete until
a naturally eligible order is submitted once, accepted, and reconciled; no forced
candidate is permitted to close that validation item.

# Milestone 10 - Software Validated

Validated with deterministic and mocked transport: Demo position monitoring; stop,
target, strategy, maximum-holding, and defensive risk exits; full long-position close;
single-attempt submission; confirmation; reconciliation; persistent halt/idempotency;
append-only evidence; read-only lifecycle views; and deterministic review records.
A separately authorized real IG Demo close remains operational validation, not a
prerequisite that automated tests may manufacture. Production/live, shorts, partial
close, amendments, working orders, account switching, automatic retry, and AI or
dashboard exit authority remain future/prohibited.

# Milestone 11 - Software Validated

Validated with deterministic and mocked inputs: six allowlisted FOREX instruments;
5-minute, 15-minute, and 1-hour completed-bar evaluation; immutable cost-adjusted
candidates; operational read-only evidence provider; persistent completed-bar
scheduling and fair bounded catch-up; authoritative exposure; strategy validation
states; duplicate/correlation suppression; deterministic ranking; persistent
cycle/evaluation idempotency; exclusive process locking; durable submitted-order
limits and campaign safety halts; Risk-only approval/sizing; controlled-execution and
lifecycle composition; runtime schema-v4 journal evidence; inactivity diagnostics;
and GET-only Operations Center projections. Demo Exploration and campaign operation
remain disabled by default. Real multi-instrument IG Demo scanning, order execution,
and closing remain operationally unvalidated and must never be manufactured or forced.
