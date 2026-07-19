# Milestone 12 — Validated Multi-Regime Strategy Portfolio

## Status

Corrective implementation required. Existing software framework is useful but the milestone is not complete until governed historical validation and accepted lineage requirements are satisfied.

## Objective

Deliver a deterministic portfolio of independently governed strategy families that can be evaluated under explicit market regimes without weakening Risk, execution, lifecycle, or operational controls.

Required families:

- accepted baseline trend strategy;
- trend pullback;
- volatility breakout;
- range mean reversion.

## Prerequisites

- Base the implementation on the final accepted Milestone 11.5 SHA.
- Preserve all IG Demo operational hardening from Milestone 11.5.
- Milestone 11.5 may remain `PARTIALLY_CERTIFIED`; missing natural trade evidence is not permission to force a trade.

## Strategy governance states

Only these lifecycle states are allowed:

- `RESEARCH_ONLY`
- `BACKTEST_VALIDATED`
- `DEMO_EXPLORATION_ENABLED`
- `DISABLED`

Promotion must be explicit, evidence-backed, fingerprinted, and approved by a named human authority. Automated promotion is prohibited.

## Deterministic strategy contract

Each strategy evaluator must:

- consume immutable cutoff-safe market data and market context;
- return a deterministic evaluation result;
- identify strategy version and configuration fingerprint;
- return no broker request and no final position quantity;
- never access credentials, HTTP clients, Risk services, execution adapters, dashboards, or AI authority;
- never mutate runtime parameters;
- produce identical results for identical inputs.

## Historical dataset governance

Create an approved dataset manifest recording:

- source and retrieval timestamp;
- instruments and timeframes;
- inclusive start and exclusive end timestamps;
- timezone and completed-bar convention;
- bar counts, gaps, duplicate policy, and invalid-bar policy;
- bid, ask, midpoint, spread, and cost assumptions;
- development, walk-forward, and untouched final-test boundaries;
- immutable dataset fingerprint.

Synthetic fixtures may test software mechanics but cannot satisfy strategy-promotion gates.

## Validation pipeline

For every new strategy run:

1. development analysis;
2. chronological walk-forward validation;
3. cost stress at 1.00x, 1.25x, 1.50x, and 2.00x;
4. execution degradation scenarios;
5. parameter-neighborhood robustness;
6. timeframe and instrument robustness;
7. period and regime robustness;
8. missing-bar and volatility-shock robustness;
9. untouched final test;
10. portfolio contribution ablations;
11. named human promotion decision.

Viewing final-test results locks the strategy version. Any later rule or parameter change requires a new version and a new untouched final-test segment.

## Required metrics and gates

Predetermine gates for:

- minimum closed trades;
- net expectancy after costs;
- profit factor;
- maximum drawdown;
- risk-adjusted return;
- walk-forward consistency;
- final-test performance;
- cost-stress survival;
- parameter stability;
- concentration and portfolio contribution.

Failed strategies remain `RESEARCH_ONLY` or become `DISABLED`. Milestone completion does not require every family to pass, but each family requires a real governed decision. At least one new family must progress beyond `RESEARCH_ONLY` for a genuinely multi-strategy executable portfolio.

## Backtest correctness requirements

Before using results for promotion:

- wire the existing intrabar-ambiguity resolution into the engine;
- wire configured profit-target logic into the engine;
- prove the tested backtest path is the path actually executed;
- wire macro scoring explicitly or declare it excluded from the frozen strategy version;
- ensure staleness gates operate in backtests when required;
- fail closed on ambiguous execution sequencing.

## Portfolio ablations

Compare at minimum:

- baseline trend only;
- trend plus pullback;
- trend plus breakout;
- trend plus range mean reversion;
- all validated strategies;
- pre-correlation versus post-correlation results;
- pre-Risk versus Risk-filtered results.

Report net return, volatility, drawdown, trade count, cost sensitivity, correlation, concentration, and marginal contribution.

## Circuit breakers and invalidation

- Circuit breakers are per-strategy and entry-only.
- Breakers persist across restart and require named manual recovery.
- Breakers cannot disable protective monitoring or lifecycle exits.
- Strategy invalidation may emit evidence to lifecycle but cannot call the close adapter.

## Operations Center

Provide GET-only views for:

- strategy validation matrix;
- performance comparison;
- strategy-regime eligibility;
- portfolio contribution;
- circuit-breaker state;
- validation artifact fingerprints and promotion authority.

No dashboard mutation route is permitted.

## Authority boundaries

Risk remains final approval and quantity authority. Execution remains sole broker mutation authority. Lifecycle remains sole close-decision authority. Strategies cannot bypass any of them.

## Prohibitions

- no Live host or Live execution;
- no forced trades;
- no automatic strategy promotion;
- no AI selection or parameter optimization;
- no ML or reinforcement learning;
- no short-entry expansion unless separately specified;
- no hidden threshold reduction;
- no tuning after final-test exposure;
- no credentials or raw sensitive broker responses in artifacts.

## Required tests

- deterministic evaluator tests;
- cutoff and no-lookahead tests;
- actual invocation tests for ambiguity and profit-target logic;
- lifecycle-state transition tests;
- no-auto-promotion tests;
- artifact fingerprint and tamper tests;
- breaker persistence and recovery tests;
- router eligibility tests;
- authority dependency scans;
- Operations Center GET-only tests;
- backend and frontend CI.

## Definition of Done

Milestone 12 is complete only when:

- implementation is based on accepted Milestone 11.5 lineage;
- all proposed families receive governed historical decisions;
- at least one new family advances beyond research-only status on evidence;
- only named human-approved strategies become Demo-enabled;
- backtest mechanics match the declared strategy rules;
- artifacts are complete, immutable, and fingerprinted;
- Risk, execution, and lifecycle authority remain unchanged;
- backend and frontend CI pass at the reviewed head SHA;
- an independent review returns `ACCEPTED`.
