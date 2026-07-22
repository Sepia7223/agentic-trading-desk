# Milestone 17 — Full IG Demo Operational Certification

## Objective

Certify the complete deterministic trading desk against the real IG Demo environment through naturally occurring, bounded, end-to-end operational evidence.

## Prerequisites

- Milestones 12 through 16 accepted.
- At least one strategy explicitly `DEMO_EXPLORATION_ENABLED`.
- Portfolio, Risk, execution, lifecycle, reconciliation, persistence, and Operations Center controls enabled only through their documented authorization sequence.
- No unresolved state corruption, ambiguity halt, or campaign safety halt.

## Required certification evidence

Observe and record, without manufacturing opportunities:

1. environment and secret preflight;
2. authentication and preferred account discovery;
3. authoritative balance, currency, position, and working-order state;
4. completed-bar scheduling across governed instruments and timeframes;
5. market context, strategy routing, opportunity scoring, and portfolio decision;
6. accepted candidate submitted to Risk;
7. Risk approval and final quantity decision;
8. one controlled IG Demo order submission;
9. confirmation and broker reconciliation;
10. durable journal, campaign, portfolio, and execution state;
11. restart while the confirmed position remains active;
12. lifecycle monitoring after restart;
13. natural or policy-governed full close;
14. close confirmation and reconciliation;
15. realized P&L and attribution reconciliation;
16. Operations Center visibility throughout the lifecycle;
17. final restart with no duplicate mutation.

## Certification rules

- No forced trade or synthetic candidate.
- No threshold, spread, expected-value, regime, Risk, portfolio, or timing gate may be weakened to obtain evidence.
- No mutation may be retried after an ambiguous outcome.
- Markets being closed or no candidate appearing is a legitimate reason to continue certification later; it is not a defect.
- Live remains unavailable.
- Only bounded Demo quantity approved by Risk may be submitted.

## Evidence package

Create sanitized immutable evidence containing:

- environment and configuration fingerprints;
- campaign identity and masked account reference;
- scheduler observations;
- candidate, strategy, portfolio, and Risk decisions;
- execution request hash and confirmation reference in sanitized form;
- reconciliation outcomes;
- position observations and lifecycle decisions;
- restart checkpoints;
- attribution reconciliation;
- incidents and operator actions;
- Operations Center screenshots or machine-readable projections without secrets;
- final certification verdict.

## Verdicts

- `CERTIFIED`: all required evidence completed.
- `PARTIALLY_CERTIFIED`: software and read-only operations passed but natural trade lifecycle evidence remains unavailable.
- `FAILED`: a safety, consistency, reconciliation, or authority defect occurred.

## Definition of Done

A natural bounded Demo trade completes the full entry, restart, monitoring, close, reconciliation, attribution, and restart lifecycle with no authority violation, no duplicate mutation, complete sanitized evidence, and independent certification verdict `CERTIFIED`.
