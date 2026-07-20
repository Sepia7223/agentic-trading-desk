# Donchian Long-Only Search — Findings

Governed search for a promotable long-only Donchian channel-breakout strategy on
the six-pair FX universe, net of real costs (spread + slippage + funding), against
the Milestone-12 gates. All runs are in the committed ledger
(`artifacts/strategy_research/daily_ledger.jsonl`) and the per-config battery
verdicts (`artifacts/strategy_research/battery_*.json`). Development+validation
only; the locked final-test was never consumed (no config earned it).

## Results

| Timeframe | Config | Trades | Profit factor | Expectancy | Full battery |
|---|---|---|---|---|---|
| DAY | USDJPY ch20 | 21 | 0.89 | −0.0003 | fail (too few trades, negative) |
| DAY | USDJPY+EURJPY ch15 | 33 | 0.45 | −0.0028 | fail |
| DAY | USDJPY+EURJPY+USDCAD ch20 | 28 | 0.41 | −0.0027 | fail |
| **HOUR** | **USDJPY buffer0.20** | **429** | **1.13** | **+0.000096** | **fail — cost-stress** |
| HOUR | USDJPY buffer0.30 stop3.0 | 374 | 1.14 | +0.00011 | fail — cost-stress |
| HOUR | USDJPY buffer0.25 stop2.5 | 405 | 1.12 | +0.00009 | fail — cost-stress |
| HOUR_4 | USDJPY buffer0.20 | 155 | 0.92 | −0.00017 | fail (negative) |

## What each timeframe showed

- **Daily** — the right character for trend-following, but structurally too
  low-frequency: a strong multi-year uptrend produces few round-trips, so it
  cannot reach the 100-trade gate even pooled, and it is near break-even to
  negative. Pooling the choppier pairs makes it worse, not better.
- **Hourly** — the only positive timeframe. USDJPY hourly with a stronger
  breakout filter is genuinely profitable at realistic costs (PF 1.13, positive
  expectancy, profitable in 5 of 7 walk-forward windows) and its parameter
  neighborhood is a stable plateau, not a spike. **But it fails the cost-stress
  gate**: expectancy is +0.000096 at 1x costs, +0.000008 at 1.5x, and **negative
  at 2x**; cost-sensitivity is 1.7–2.0 across three tuned configs (gate ≤ 0.50).
  Reducing turnover did not fix it — the fragility is structural: the hourly
  gross edge is too thin relative to hourly trading costs.
- **4-hour** — negative expectancy; the breakouts are less reliable at that
  scale.

## Conclusion

**No long-only Donchian configuration clears the Milestone-12 gate battery.** The
best result — USDJPY hourly — is a *real but marginal, cost-fragile* edge: it
makes money at current costs and is time-consistent, but it does not survive a 2x
cost stress, which is a predetermined M12 gate that cannot be weakened. This
matches the research prediction that long-only trend-following on these majors is
a meaningful haircut, and that intraday breakout in FX is cost-dominated.

## Recommendation

The evidence points to a structural cause, not a tuning failure: **FX has no drift,
so a long-only mandate keeps only the thin, cost-fragile half of a trend edge.**
The highest-leverage fix is to **enable short entries** (still DEMO-only) — which
opens the symmetric trend, mean-reversion, and crisis-alpha legs the research
identifies as where the real, cost-robust edges live. That is a core-architecture
change and warrants its own milestone and review; it is the recommended direction
after this search. A remaining long-only avenue to test for completeness is
opening-range breakout (GBP/USD), though the research predicts it is also
cost-fragile in FX.

*The USDJPY hourly edge, while below the strict M12 promotion gate, is a genuine
positive-expectancy result at realistic costs and is preserved in the ledger for
future reference (e.g., if a short-enabled, lower-cost, or multi-pair-diversified
variant changes the cost-robustness picture).*
