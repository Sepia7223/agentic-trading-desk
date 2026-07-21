# Paper-Trading Runbook — Equity Momentum V1

Operates the market-neutral momentum strategy in PAPER mode: real market data,
real pre-trade validation (news gate included), simulated execution. This is the
reviewer-required forward-testing phase. **No real orders exist anywhere in this
stack.**

## Daily operation

**Automated:** the Windows scheduled task `AgenticDesk-PaperTrade` runs
`scripts/run_paper_session.cmd` weekdays at 18:30 local (after the US close),
appending output to `data/paper/session.log`. Manage it with:

    schtasks /Query  /TN "AgenticDesk-PaperTrade" /FO LIST /V   # inspect
    schtasks /Run    /TN "AgenticDesk-PaperTrade"               # run now
    schtasks /Delete /TN "AgenticDesk-PaperTrade" /F            # remove

(The machine must be on at 18:30; a missed day is harmless — the next session
settles whatever is queued against the newest completed bars.)

**Manual** (equivalent):

    cd agentic-trading-desk-m12
    PYTHONPATH="src;scripts" python scripts/paper_trade.py

What one session does, in order:
1. **Health** — kill-switch files, incident lock, quote freshness.
2. **Settle** — yesterday's queued orders fill at today's open (adverse
   spread+slippage); armed 15% catastrophe stops run on today's high/low with
   gap-through pricing; protection failure ⇒ close + `INCIDENT_LOCK`.
3. **Mark** — equity at today's close; daily-loss/drawdown anchors roll;
   realized round-trips update the consecutive-loss counter.
4. **Decide** — 12-1 momentum, sector-neutral, buffered, on current S&P
   membership. **Gross is derived from the stress budget** (binding-scenario
   inversion, ≈0.375× at default shocks and the 0.75% budget), capped at 0.5×.
5. **Validate** — every entry passes the full pipeline: eligibility, signal,
   regime, risk, net edge after costs, execution quality, short-sale state,
   post-trade portfolio (incl. measured correlation clusters), stress, margin,
   order sanity, protection, **live news gate** (Yahoo headlines; unread ⇒ no
   trade). Exits bypass opportunity gates by policy — reducing risk is never
   blocked by the checks that gate adding risk (health and order sanity still
   apply). Throttle + restart-surviving idempotency keys guard against runaway
   or duplicate orders.
6. **Queue + persist** — approved protected orders queue for tomorrow's open;
   `data/paper/paper_state.json` and the append-only `journal.jsonl` record
   everything, including every rejection with its exact code.

## Controls a human operates (no tooling needed)

| Action | How |
|---|---|
| Stop everything | create file `data/paper/KILL_GLOBAL` |
| Stop this strategy | create file `data/paper/KILL_STRATEGY` |
| Resume | delete the kill file |
| Incident lock reset | delete `data/paper/INCIDENT_LOCK` **after reading the reason inside it** — human only, by design |

## Deployment decisions (recorded per the no-silent-change rule)

- `maximum_daily_trades = 200` and throttle caps 250: the generic 8/day starting
  control is for single-signal strategies; one portfolio rebalance is one
  DECISION with many orders. Risk is governed by the stress budget, not order
  count.
- `minimum_equity = $500`: paper account starts at $1,000; trading halts if
  equity ever falls below $500 (the never-blow-the-account backstop; ruin in
  paper would already have failed the drawdown shutdown long before this).
- Fractional shares permitted in paper. The implementability report already
  documents that a literal $1,000 real account cannot trade 60 names without
  fractional shorting; paper validates the STRATEGY while sizing realism for a
  real account is tracked separately.
- Paper short-borrow model: S&P large caps assumed general-collateral at
  0.5%/yr, locate always available. Real borrow data requires a live broker
  integration and is a documented limitation of the paper phase.
- `market_cap` is asserted via S&P membership rather than a live cap feed
  (members exceed the floor by construction); a real cap feed is a live-phase
  item.

## What to review weekly

- `journal.jsonl`: rejection-code distribution — distinguishes "no
  opportunities" from "blocked by risk"; fill-quality records.
- Equity curve (`equity_by_day` in the state file) vs. the backtest's
  expectation band.
- Incident/kill events: every one must have a written cause before reset.

## Graduation gates (before ANY real order)

Per the reviewer's assessment and the acceptance standard: 3–6 months of paper
sessions · forward results broadly consistent with simulation · realized costs
within the modeled range · zero unresolved reconciliation errors · drawdown
within limits · no unexplained factor/sector concentration · a live-broker
integration with real borrow data, real caps feed, OCO/OTO at the broker, and
its own review. Passing paper does not authorize live trading; that requires an
explicit human decision.
