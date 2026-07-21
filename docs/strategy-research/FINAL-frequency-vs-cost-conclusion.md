# Final conclusion — the binding constraint is frequency × cost, not win rate

Complete result of the search to satisfy the acceptance standard (v1, then v2 with
the win-rate floor dropped) on the six FX majors, MINUTE_5, dev+validation
2022-01→2025-06, realistic costs (real half-spreads + 0.5 bps/side slippage).

## Everything tested, and how it failed

| Approach | Freq 3–8/day? | Net after costs | Realized R:R | Win | Verdict |
|---|---|---|---|---|---|
| Mean-reversion (fade), all params, 6 pairs | ✅ | **negative** | <1 | ~45–50% | fail |
| Momentum (follow), all params, 6 pairs | ✅ | **negative** | <1 | ~42–48% | fail |
| Statistical arbitrage, 15 spreads, 6 param sets | ✅ | **negative** | ~0.8–1.09 | ~37–42% | fail |
| Hourly Donchian trend | ❌ ~0.27/day | positive @1× (fails 2×) | ~1.27 | ~47% | fail (freq) |
| Daily / carry-harvest trend | ❌ <0.1/day | positive | >1 | low | fail (freq) |

## The mechanism

- **At 3–8 trades/day (5-minute bars), every price-only strategy is net-negative.**
  The reason is cost, not signal geometry: intraday FX round-trip cost is ~2–3 bps
  (single-leg) to ~3–4 bps (two-leg spread), while the exploitable move at 5-minute
  scale is comparable in size. Stat-arb even has a *tiny positive gross edge*
  (~+0.00005/trade before cost) — but cost (~0.00015/trade) erases it.
- **Cutting cost by trading only tight-spread prime hours is blocked by the
  frequency gate itself**: restricting to the London–NY overlap (~4h/day) drops
  frequency below the 3/day floor. Achieving 3–8/day *forces* trading in
  wide-spread hours, which reimposes the cost that kills the edge.
- **The only net-positive, R:R>1 strategies found trade <1/day** (hourly/daily
  trend, carry). Frequency and net-positivity are, on this data, **mutually
  exclusive**.

## Bottom line

Neither the strict standard (v1) nor the relaxed one (v2, no win-rate floor) is
satisfiable on this universe. Dropping the win-rate gate did not help because
win rate was never the true blocker — **the true binding constraint is the 3–8
trades/day frequency gate combined with realistic intraday costs.** That pairing is
what makes net-positive impossible; no price-only strategy (single-pair directional
or multi-pair cointegration) overcomes it.

## The genuine choice (each needs a written decision, per the standard)

1. **Relax the frequency gate** (allow < 3 trades/day). This unlocks the strategies
   that *are* net-positive with R:R > 1 on this data — hourly/daily trend and carry.
   Trade-off: a working strategy trades ~0.2–1×/day, not intraday. This is the only
   change that admits a net-positive result on the current data/costs.
2. **Change the cost structure** — a tighter-spread venue/broker or a
   maker/rebate execution model — so intraday edge can clear cost at 3–8/day.
   Requires different cost assumptions than the current (conservative) model.
3. **Change the market / add data** — a less-efficient instrument (e.g., crypto,
   small-cap), or non-price signals (order-flow, events, cross-asset). Out of scope
   for the current FX bar set; requires acquisition.
4. **Keep both gates as-is** and accept the proven result: no strategy on this
   6-pair 5-minute FX dataset satisfies the standard.

Recommendation: **(1)** — relax the frequency gate — because it is the one option
that yields a genuinely net-positive, R:R>1 strategy from data already in hand;
the low-frequency trend/carry results are real, just slow.
