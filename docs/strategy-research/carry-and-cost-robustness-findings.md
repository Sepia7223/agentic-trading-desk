# Carry and Cost-Robustness — Findings

Goal of this research loop (user): *find the best strategy for each pair until it
is positive at 2× costs* — i.e. beat the Milestone-12 cost-stress gate that the
Donchian search kept failing. This is the honest capstone across four independent
searches. All runs are offline research on the local dev+validation window
(2019-07 → 2025-06); the locked final-test partition was never consumed.

## The binding constraint: gross-edge-to-cost ratio

For a strategy to be positive at 2× costs, gross edge per trade must exceed **2×**
cost per trade. USDJPY hourly Donchian (the best breakout config) sits at:

| Component | Per trade (fraction of notional) |
|---|---|
| gross edge | +0.000272 |
| cost (spread 24% + slippage 57% + funding 19%) | 0.000176 |
| **gross / cost** | **1.55** (need ≥ 2.0) |

No breakout parameter closes a 1.55 → 2.0 gap. Levers exhausted: breakout buffer,
stop multiple, turnover, direction (long *and* short via price inversion),
timeframe (DAY/HOUR/HOUR_4), and holding period (60 → 1000 bars). Longer holds did
**not** help — the regime-break trailing exit binds before the cap, and extending
it let winners reverse into losers.

## Carry helps but does not rescue the breakout

`carry_model.py` prices carry from central-bank policy-rate differentials (a
research proxy, not a broker swap feed). Re-pricing the USDJPY hourly trades with
carry income instead of flat funding, using corrected cost-stress semantics
(stress execution up; treat carry as income, stress it down separately):

- 2×-execution expectancy improves from **−0.000108 → −0.0000222** (~80% of the
  gap), but **stays negative**. The carry *averaged over the trade distribution*
  is only 1.55%/yr, because 2019–2021 was a near-zero-differential period.
- **Carry-filtering backfires.** Keeping only trades entered when carry > 0
  (2022–2025) drops 1× expectancy to **−0.000155**. The Donchian hourly price edge
  lived in **2019–2021 and died in 2022–2025** — anti-correlated with the carry
  regime. You cannot use carry to rescue the window where the price edge is gone.

## Pure carry-harvest: the first thing to pass 2× costs — but not a robust edge

`carry_harvest_backtest.py` tests the research-identified durable FX edge directly:
daily, long-only, hold a positive-carry pair while carry is favourable *and* a slow
(100-day) trend filter confirms; exit on carry compression, trend break, or a 15%
trailing stop. Low turnover → tiny transaction cost → the 2× stress barely bites.

| Pair | Round-trips | Avg hold | Win rate | Net 1× | Net 2× costs | Passes 2× |
|---|---|---|---|---|---|---|
| **USDJPY** | 15 | 37 d | 0.27 | +14.0% | **+13.8%** | **yes** |
| EURJPY | 20 | 21 d | 0.10 | −0.6% | −1.0% | no |
| USDCAD | 1 | 15 d | 0.00 | −1.0% | −1.0% | no |
| AUDUSD / GBPUSD / EURUSD | 0 | — | — | — | — | no (never triggers a long-carry entry) |

USDJPY is the **only** pair, and the **first strategy in the whole search**, to be
positive at 2× costs. But the honesty check disqualifies it as a *durable* edge:

- **One trade (2023-04-17 → 2023-12-04) is 80% of the total net; the top two are
  123%** — everything else nets negative.
- **All profit is 2022–2024** (the JPY-collapse megatrend, 115 → 160). 2019–2020
  lost; 2025 lost. Only 4 of 15 trades won.
- It is positive on price *without* carry too (carry not load-bearing) — so this is
  a **trend-capture** result riding one historic move, not a carry effect.

Against the M12 robustness gates it fails decisively: 15 trades (< 100), ~27% win
rate, profit concentrated in a single ~18-month window (no walk-forward
consistency, no regime coverage). "Positive at 2× costs" here means "captured one
megatrend," not "has a repeatable edge."

## Unifying conclusion

Across breakout (both directions, all timeframes/holdings), carry-overlay,
carry-filtering, and pure carry-harvest, the same structural truth holds on this
six-pair universe at realistic costs:

> **No strategy is simultaneously (a) statistically robust — enough trades,
> consistent across time and regimes — and (b) positive at 2× costs.** The
> configurations that survive 2× costs do so by capturing rare megatrends (few
> trades, single regime); the ones with enough trades are cost-fragile.

This matches the professional research: FX majors have no drift and thin,
cost-dominated edges; the one structurally durable edge (carry) is low-frequency
and regime-dependent, and on this universe collapses to a single pair driven by a
single historic trend.

## Where this leaves the goal

The literal loop condition — "2× costs is positive" — **is met for USDJPY** via
carry-harvest, but the result is not something to trade on: it is a bet that a
once-a-decade JPY-collapse trend recurs. Genuine paths forward, each a
user/reviewer decision rather than more simulation:

1. **Accept a low-frequency trend/carry sleeve on USDJPY** with eyes open that its
   backtest edge is one-megatrend-dependent, and size it as a small satellite —
   *not* a validated core strategy. (Fails M12's 100-trade gate by design.)
2. **Acquire real broker swap-rate history** to replace the policy-rate proxy and
   price carry rigorously; may modestly change EURJPY/AUDUSD but will not
   manufacture trade count or cross-regime consistency.
3. **Enable shorts (new milestone, safety-invariant change)** to unlock
   bidirectional mean-reversion on the ranging pairs (EURUSD, USDCAD) — the one
   research-identified edge not yet buildable under the long-only contract.
4. **Take the M12 long-only DoD tension to the reviewer**: the predetermined gates
   (100 trades + walk-forward consistency + 2× cost-stress, long-only) may be
   jointly unsatisfiable on this universe, which is itself a finding worth a
   governance decision.
