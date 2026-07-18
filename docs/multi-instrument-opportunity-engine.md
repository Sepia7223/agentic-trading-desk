# Multi-Instrument Opportunity Engine

## Status and authority

Milestone 11 is operationally wired and software-validated with deterministic and
mocked broker inputs. The engine is disabled by default, DEMO-only, long-only, and has
no independent broker mutation authority. Real IG Demo scanning, campaign trading, and
closing were not performed for this correction.

## Governed flow

The operational path is:

```text
IG read-only details/prices -> completed-bar scheduler -> Candidate Context
-> Strategy Router -> CandidateEvidence -> costs/EV/score -> exposure filters
-> deterministic ranking -> exploration preflight -> Risk -> controlled Demo execution
-> confirmation/reconciliation -> lifecycle -> journal/campaign -> Operations Center
```

`OperationalOpportunityEvidenceProvider` owns only the read-only portion through
`CandidateEvidence`. It preserves data, context, router, strategy, and configuration
fingerprints and rejects missing history/details/calendars, stale or unfinished bars,
uncertain context, and research-only strategies. The execution composition lives in
the execution package. Only Risk can approve and size, controlled IG Demo execution
can open, and lifecycle can close.

## Universe and cadence

The immutable initial universe is EUR/USD, GBP/USD, USD/JPY, AUD/USD, USD/CAD, and
EUR/JPY, using configured IG epics. Supported entry evaluation timeframes are 5 minutes,
15 minutes, and 1 hour. Every evaluation uses a completed UTC bar. The persistent key
is:

```text
SHA256(instrument_id, timeframe, completed_bar_timestamp, strategy_fingerprint)
```

Unknown instruments, arbitrary epics, unfinished bars, stale evidence, duplicate
cycles, and repeated completed-bar evaluations fail closed.

The persistent scheduler calculates the latest completed boundary, handles holidays
and closed sessions, records skipped bars, performs bounded catch-up, and rotates its
starting point when an evaluation cap prevents a full cycle. Lifecycle checks use a
separate interval and continue when no entry bar is due.

## Strategy states

`trend-regime-v1` is both `BACKTEST_VALIDATED` and
`DEMO_EXPLORATION_ENABLED`. Trend pullback, volatility breakout, and range mean
reversion are `RESEARCH_ONLY`. A strategy must have both executable states and no
`DISABLED` state before it can reach Risk.

## Costs and expected value

For probabilities `p_win + p_loss = 1`:

```text
gross EV = p_win * average_gain - p_loss * average_loss
net EV = gross EV - spread - slippage - commission - funding
         - uncertainty penalty - liquidity surcharge - event surcharge
```

Observable spread must be fresh and strictly positive. Spread, slippage, uncertainty,
liquidity, and event costs are non-zero when applicable. Commission and funding remain
zero until authoritative values are available in price units; mixing account-currency
costs with price movement is prohibited. Net EV at or below the configured minimum
rejects.

## Score and ranking

The Decimal score is bounded from 0 to 100 and combines net EV, confidence, regime
compatibility, reward/risk, liquidity, volatility suitability, session quality, data
quality, event safety, cost efficiency, and uncertainty. Default labels are STRONG at
85, STANDARD at 70, EXPLORATORY at 55, and REJECTED below 55.

Ranking first requires eligibility and positive net EV, then sorts by score, net EV,
data quality, lower cost, and stable candidate ID. At most three candidates reach Risk
per cycle. Duplicate fingerprints, same-bar/timeframe overlap, existing positions,
cooldowns, and occupied correlation groups suppress candidates with stable reasons.

Authoritative open positions are fetched before filtering. Exposure includes epics,
directions, quantities, occupied correlation groups, base/quote currencies, position
count, and durable recent-close cooldowns. If exposure is unavailable, new entries
stop before Risk while lifecycle monitoring remains active.

## Demo Exploration and campaign

Demo Exploration defaults disabled and requires explicit configuration plus a CLI
enable signal. STRONG, STANDARD, and EXPLORATORY candidates recommend risk multipliers
of 1.00, 0.50, and 0.25. Recommendations can only reduce the request presented to
Risk; they never authorize quantity or raise limits.

Campaign state is durable JSON and starts from the preferred IG Demo account's actual
balance and equity. The 20,000 value is only a reporting reference. A 100% return
target and 100/250 closed-trade targets are reporting/diagnostic objectives. Daily,
weekly, campaign drawdown, consecutive-loss, execution-incident, and
reconciliation-incident thresholds persistently halt new entries. Monitoring,
reconciliation, and governed exits continue during an entry halt.

The append-only trade ledger uses UTC trading dates. The daily limit counts submitted
orders, including ambiguous submissions, so restart or an uncertain broker response
cannot reopen capacity. It also records confirmations, rejections, closes, strategy,
instrument, candidate ID, and execution ID. The established controlled-execution
limit of one submitted order per day remains stricter than the Opportunity campaign's
configurable ceiling and cannot be raised by the Opportunity layer.

## Persistence and evidence

Cycle state uses an exclusive lock, tested stale-lock recovery, atomic replacement,
fair-scheduling cursor, and fingerprinted JSON. Journal schema v4 records the actual
runtime cycle, universe, evaluation, candidate, cost, score, suppression, ranking,
Risk, preflight, execution approval, diagnostic, campaign, and halt outcomes. Records
are append-only, fingerprinted, schema-versioned, sanitized, and projected into the
GET-only Operations Center views.

## Known limitations

- Only the existing trend-regime family is executable.
- Real multi-market IG Demo cadence and holiday/event source certification still
  require a separately authorized operational run.
- Correlation groups are static policy labels, not a fitted covariance model.
- Cost estimates are deterministic assumptions; commission/funding need an
  authoritative unit conversion and all estimates require realized-cost comparison.
- No real IG Demo order or lifecycle event was produced in this milestone.
