# IG Demo Operational Certification

## Scope

Milestone 11.5 validates the accepted Opportunity Engine against the canonical IG
Demo gateway without changing strategy thresholds or bypassing context, ranking,
Risk, execution, reconciliation, or lifecycle controls. Live remains technically
unavailable. A candidate, entry, or exit is evidence only when it occurs naturally.

Committed files under `artifacts/ig_demo_certification/templates/` are sanitized
schemas. Account-specific runtime evidence belongs under the ignored
`.trading-desk/ig-demo-certification/` directory or the ignored artifact runtime
directory. Never commit account identifiers, credentials, tokens, raw headers, or
raw broker responses.

## Certification Run

The July 18, 2026 Demo run established the following real operational evidence:

- The exact Demo gateway authenticated with OAuth v3 and selected one preferred USD
  CFD account. Its identifier was masked in output.
- The broker reported actual starting balance and equity of USD 20,000. These were
  observed account values, not a configured replacement.
- All six governed markets returned valid market details. IG's USD/JPY response
  exposed one unambiguously usable currency with `isDefault=false`; parsing now
  accepts only that sole-code case and still rejects ambiguous currency lists.
- Read-only scans evaluated the governed timeframes without Risk submission or
  broker mutation. A cycle-scoped details cache prevents redundant market-detail
  requests.
- Historical-price v3 requests now set both `max` and `pageSize`; IG otherwise
  returned its default page size of 20, which was insufficient for the strategy.
- A bounded three-cycle observer ran for approximately 10 minutes and released its
  exclusive process lock. Persistent state survived a process restart.
- The campaign was initialized from real account values, rejected a duplicate start,
  and reloaded successfully in a separate process.

## Incidents And Corrections

The first scan failed closed on the sole unmarked JPY currency. A later scan received
`error.public-api.exceeded-api-key-allowance`; it was not retried. Investigation found
redundant market-detail calls and the v3 page-size default. Both were corrected with
focused regression tests. The first observer also revealed that the scheduler could
construct weekend FOREX cutoffs. The scheduler now suppresses Friday 21:00 UTC through
Sunday 21:00 UTC and has boundary tests. State produced before that correction is
retained only as incident evidence and is not reused as clean certification state.

## Decision Rule

The current operational decision is `PARTIALLY_CERTIFIED`. Real read-only access,
bounded observation, restart persistence, and real campaign initialization passed.
No naturally eligible candidate appeared while the governed markets were closed or
in `EDITS_ONLY`, so no Risk-approved entry, broker confirmation, reconciliation,
position lifecycle, automatic close, or real-position restart can be certified.
Those items remain open operational requirements. They must not be simulated or
forced to change the decision.

## Milestone 11.5-B

Full certification requires an open-market run using `demo-exploration
certify-lifecycle`. The command requires the Opportunity Engine, Demo Exploration,
controlled execution, and operational-certification switches independently. It
rejects the temporary weekend calendar sources and an empty economic calendar.

The certification ledger permits one submitted entry in total, including ambiguous
submissions, and preserves that limit across process restart and UTC day boundaries.
Once consumed, new entries remain halted while position discovery, reconciliation,
lifecycle monitoring, and an eligible automatic close continue. Full certification
requires real evidence for the natural candidate, positive net expected value,
exposure and correlation clearance, Risk approval, one write-ahead broker submission,
confirmation, reconciliation, position rediscovery after restart, automatic close,
realized P&L/costs, campaign update, journal lineage, and Operations Center projection.

Each instrument/timeframe performs one bounded historical bootstrap. Later cycles
request only the newest two bars and merge them into an in-memory, timestamp-unique
window. A malformed incremental page is not merged. This keeps the long-running
certification monitor within the broker's historical-price allowance without
persisting raw market responses.

An accepted confirmation is not sufficient to create managed-position authority.
The trade ledger records `CONFIRMED` only after entry reconciliation is
`RECONCILED`. The lifecycle monitor then accepts exactly one matching ledger-backed
position and ignores untracked or ambiguous duplicate positions. Approved intent,
execution request, preflight, submission, confirmation, entry reconciliation,
position monitoring, close submission, close confirmation, close reconciliation,
position closure, and post-trade review are mirrored into the append-only SQLite
journal consumed by the Operations Center.

The first operational process uses `--exit-after-position-observed`. It exits
gracefully only after the reconciled, ledger-backed position has completed a
lifecycle observation and releases the process lock in `finally`. Restarting the
same command without that switch must rediscover the position from broker and ledger
state, keep the global entry latch active, and continue only lifecycle monitoring.

The empty weekend calendar snapshots used during read-only observation validate file
shape only. They are not authoritative economic-calendar evidence and must never be
used to authorize execution.
