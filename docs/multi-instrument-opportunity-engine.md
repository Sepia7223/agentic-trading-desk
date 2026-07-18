# Multi-Instrument Opportunity Engine

## Status and authority

Milestone 11 is software-validated with deterministic and mocked inputs. The engine is
disabled by default, DEMO-only, long-only, provider-neutral, and has no broker mutation
authority. Real IG Demo campaign trading was not performed.

## Governed flow

Completed-bar evidence flows through market/context validation, a strategy policy,
cost estimation, expected value, scoring, suppression, and bounded ranking. Selected
candidates become existing Risk Engine inputs. Only Risk can approve and size. Only
controlled IG Demo execution can open a position. Only lifecycle can close one.

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

Observable spread must be fresh and strictly positive. Missing costs never become
zero silently. Funding is included for expected holding periods crossing daily
boundaries. Net EV at or below the configured minimum rejects.

## Score and ranking

The Decimal score is bounded from 0 to 100 and combines net EV, confidence, regime
compatibility, reward/risk, liquidity, volatility suitability, session quality, data
quality, event safety, cost efficiency, and uncertainty. Default labels are STRONG at
85, STANDARD at 70, EXPLORATORY at 55, and REJECTED below 55.

Ranking first requires eligibility and positive net EV, then sorts by score, net EV,
data quality, lower cost, and stable candidate ID. At most three candidates reach Risk
per cycle. Duplicate fingerprints, same-bar/timeframe overlap, existing positions,
cooldowns, and occupied correlation groups suppress candidates with stable reasons.

## Demo Exploration and campaign

Demo Exploration defaults disabled and requires explicit configuration plus a CLI
enable signal. STRONG, STANDARD, and EXPLORATORY candidates recommend risk multipliers
of 1.00, 0.50, and 0.25. Recommendations can only reduce the request presented to
Risk; they never authorize quantity or raise limits.

The 30-day campaign starts from a reporting reference of 20,000. A 100% return target
and 100/250 closed-trade targets are reporting/diagnostic objectives. Daily, weekly,
campaign drawdown, consecutive-loss, execution-incident, reconciliation-incident, and
uptime thresholds can halt new entries. Monitoring and governed exits continue during
an entry halt.

## Persistence and evidence

Cycle state uses an exclusive lock, stale-lock recovery, atomic replacement, and
fingerprinted JSON. Journal schema v4 adds cycle, universe, evaluation, candidate,
cost, score, suppression, ranking, Risk, execution approval, diagnostic, and campaign
records. Records are append-only, fingerprinted, schema-versioned, and sanitized.

## Known limitations

- Only the existing trend-regime family is executable.
- The candidate evidence provider remains a protocol; real multi-market data cadence
  and holiday/event source certification require a separate operational run.
- Correlation groups are static policy labels, not a fitted covariance model.
- Cost estimates are deterministic assumptions and require realized-cost comparison.
- No real IG Demo order or lifecycle event was produced in this milestone.
