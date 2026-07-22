# Milestone 14 — Portfolio Analytics and Performance Attribution

## Objective

Create a deterministic, auditable analytics layer that explains portfolio outcomes across strategy, instrument, regime, timeframe, risk, execution, and lifecycle dimensions without gaining trading authority.

## Scope

Implement:

- realized and unrealized P&L attribution;
- strategy contribution and marginal contribution;
- instrument, currency, correlation-group, timeframe, and regime attribution;
- gross versus net performance decomposition;
- spread, slippage, financing, and execution-degradation attribution;
- drawdown, recovery, downside deviation, and exposure-adjusted returns;
- opportunity funnel analytics from discovered candidate through close;
- accepted-versus-rejected counterfactual reporting using frozen evidence only;
- Paper versus Demo comparison;
- campaign and rolling-window scorecards.

## Data lineage

Every metric must trace to immutable journal, portfolio, Risk, execution, reconciliation, and lifecycle records. Calculations must identify input ranges, timezone, currency conversion rules, configuration version, and fingerprint.

Analytics cannot rewrite source records. Corrections require append-only superseding records.

## Required measures

At minimum:

- gross and net P&L;
- win rate and payoff ratio;
- expectancy and profit factor;
- Sharpe-like and Sortino-like measures with declared conventions;
- maximum drawdown and recovery duration;
- turnover, exposure time, and capital utilization;
- cost drag and implementation shortfall;
- contribution by strategy and allocation decision;
- correlation and concentration contribution;
- Risk rejection and quantity-reduction effects;
- lifecycle exit-reason attribution;
- missed-opportunity and why-no-trade counts without hindsight mutation.

## Currency handling

Use an explicit reporting currency and timestamped conversion evidence. Unknown conversion data must produce unavailable metrics, not fabricated values.

## Operations Center

Add GET-only views for:

- portfolio scorecard;
- attribution waterfall;
- equity and drawdown series;
- strategy and regime comparison;
- cost and slippage analysis;
- opportunity funnel;
- Risk and portfolio decision impact;
- data completeness and lineage diagnostics.

## Authority boundaries

Analytics is read-only. It cannot change allocations, strategy states, Risk policy, execution, lifecycle, campaign state, or broker data.

## Required tests

- exact attribution reconciliation to authoritative P&L;
- currency conversion and missing-rate behavior;
- rolling-window boundaries;
- append-only correction handling;
- cost decomposition;
- deterministic aggregation ordering;
- empty and partial campaign behavior;
- restart and replay consistency;
- API and frontend projection tests.

## Definition of Done

All portfolio outcomes reconcile to authoritative records, metrics are deterministic and fingerprinted, missing evidence fails visibly, Operations Center views remain GET-only, and independent review returns `ACCEPTED`.
