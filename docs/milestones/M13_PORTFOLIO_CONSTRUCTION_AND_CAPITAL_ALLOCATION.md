# Milestone 13 — Portfolio Construction and Capital Allocation Engine

## Objective

Move from independent validated strategies to deterministic portfolio-level capital allocation while preserving Risk as final quantity authority and Execution as sole broker mutation authority.

## Pipeline

```text
Market Data
→ Market Context
→ Strategy Router
→ Strategy Evaluation
→ Opportunity Engine
→ Portfolio Construction Engine
→ Capital Allocation Engine
→ Risk Engine
→ Controlled Execution
→ Lifecycle
```

## Portfolio responsibilities

The portfolio layer may:

- accept, reject, or defer candidates;
- rank simultaneous candidates deterministically;
- apply strategy budgets and portfolio constraints;
- propose capital and quantity;
- calculate correlation, concentration, and currency exposure;
- persist decisions and restart-safe state;
- publish read-only portfolio projections.

The portfolio layer may not:

- activate or promote strategies;
- change strategy signals;
- bypass Risk;
- approve final quantity;
- submit, retry, amend, or close broker orders;
- modify lifecycle decisions;
- enable Live trading;
- introduce AI allocation.

## Input contract

A portfolio candidate must include:

- candidate and opportunity identifiers;
- strategy identifier and immutable version;
- instrument, epic, direction, and timeframe;
- evaluation and completed-bar timestamps;
- expected value and confidence components;
- entry, stop, and target assumptions where applicable;
- strategy and evidence fingerprints;
- market regime and correlation group;
- proposed risk distance;
- existing exposure snapshot identifier.

Inputs are immutable and cutoff-safe.

## Portfolio state provider

Create a provider that supplies an authoritative snapshot of:

- account equity and available capital;
- confirmed positions;
- pending or ambiguous submissions;
- per-strategy allocations;
- instrument and correlation-group exposure;
- currency exposure;
- daily realized and unrealized P&L;
- campaign drawdown and halt state;
- recent closes and cooldowns;
- portfolio configuration fingerprint.

Unknown or stale state fails closed for new entries while protective monitoring continues.

## Portfolio decision model

Every evaluated candidate receives a durable decision containing:

- `ACCEPT`, `REJECT`, or `DEFER`;
- deterministic rank;
- proposed capital;
- proposed quantity;
- applied sizing policy;
- binding constraints and reason codes;
- correlation and concentration values;
- input, state, and configuration fingerprints;
- decision timestamp;
- idempotency key.

## Deterministic ranking

Ranking must use an explicit immutable ordering, such as:

1. eligibility and positive net expected value;
2. risk-adjusted opportunity score;
3. regime fit;
4. portfolio diversification benefit;
5. lower concentration penalty;
6. completed-bar timestamp;
7. stable strategy, instrument, and candidate identifiers.

No randomized tie-breaking is permitted.

## Strategy budgets

Support immutable per-strategy configuration for:

- maximum allocated capital;
- maximum risk fraction;
- maximum concurrent positions;
- maximum daily accepted entries;
- maximum instrument and correlation-group concentration;
- enabled sizing policies.

Budgets constrain allocation but do not promote a strategy or override Risk.

## Portfolio-wide constraints

Enforce at least:

- maximum total proposed risk;
- maximum concurrent positions;
- maximum instrument exposure;
- maximum strategy exposure;
- maximum correlation-group exposure;
- maximum currency long and short exposure;
- maximum daily capital deployment;
- campaign halt and drawdown controls;
- pending and ambiguous submission reservations;
- recent-close cooldowns.

## Sizing policies

Implement deterministic policies:

- fixed capital;
- fixed fractional equity risk;
- volatility targeting.

Kelly sizing is research-only. It may produce analysis but cannot feed Demo execution.

Every policy returns a proposal. Risk recalculates and owns the final approved quantity.

## Correlation engine

Provide rolling deterministic correlation using completed, aligned returns with:

- explicit lookback and minimum overlap;
- missing-data policy;
- immutable timeframe and return definition;
- stable handling of insufficient evidence;
- correlation matrix fingerprint;
- conservative fallback when correlation is unknown.

Apply explicit rejection, deferral, or penalty thresholds. Do not silently alter scores.

## Batch evaluation

Candidates from the same scheduling boundary must be evaluated as one deterministic batch against one authoritative state snapshot. Reservations created by earlier ranked candidates must affect later candidates in the same batch.

Repeated evaluation of the same batch must not duplicate reservations or decisions.

## Deferred candidates

A deferred candidate:

- is not sent to Risk or Execution;
- records a reason and expiry boundary;
- may be reconsidered only under an explicit policy with fresh authoritative state;
- cannot survive beyond its signal-validity boundary;
- cannot be automatically converted into an accepted order after restart.

## Persistence and restart safety

Persist:

- portfolio decisions;
- reservations;
- batch identities;
- configuration fingerprints;
- correlation evidence;
- last authoritative state snapshot;
- recovery and reconciliation status.

Restart must reconstruct reservations from confirmed, pending, and ambiguous activity without duplicate Risk submissions.

## Journal and attribution

Journal every portfolio decision and later connect it to:

- Risk decision;
- execution attempt and confirmation;
- lifecycle result;
- realized P&L;
- strategy and portfolio attribution.

Rejected and deferred opportunities remain visible for diagnostic analysis.

## Operations Center

Add GET-only views for:

- portfolio health;
- current allocations and reservations;
- strategy budgets and utilization;
- exposure by instrument, currency, and correlation group;
- candidate ranking and binding constraints;
- accepted, rejected, and deferred decisions;
- configuration and state freshness;
- attribution summaries.

No mutation route is permitted.

## CLI

Provide read-only commands to:

- inspect portfolio configuration;
- evaluate a fixture or current read-only candidate batch;
- display exposure and reservations;
- verify persistence and fingerprints;
- explain an allocation decision.

CLI commands cannot submit orders unless they enter the existing separately authorized controlled-execution composition.

## Required tests

- deterministic ranking and tie-breaks;
- strategy budget enforcement;
- portfolio constraint enforcement;
- fixed, fractional, and volatility sizing;
- Kelly isolation from execution;
- correlation alignment and insufficient-data behavior;
- currency exposure calculations;
- simultaneous batch reservations;
- defer expiry and reconsideration;
- restart and idempotency;
- pending and ambiguous submission reservations;
- Risk final-quantity authority;
- no broker dependencies in portfolio modules;
- journal and Operations Center projections;
- backend and frontend CI.

## Prohibitions

- no Live support;
- no AI, ML, or RL allocation;
- no automatic strategy promotion;
- no Risk bypass;
- no broker calls from portfolio code;
- no lifecycle mutation;
- no martingale or loss-chasing allocation;
- no random decisions;
- no runtime parameter optimization;
- no forced trades.

## Definition of Done

- deterministic allocation and ranking are complete;
- strategy budgets and portfolio constraints are enforced;
- correlation and currency exposure are conservative and auditable;
- simultaneous batches are restart-safe and idempotent;
- Risk remains final quantity authority;
- Execution remains sole broker authority;
- all decisions are journaled and visible through GET-only operations views;
- full backend and frontend validation passes;
- documentation and PR evidence are complete;
- independent review returns `ACCEPTED`.
