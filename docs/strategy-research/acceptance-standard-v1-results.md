# Acceptance Standard v1 — Results (single-pair directional strategies)

Testing against `acceptance-standard-v1.md` (3–8 trades/weekday, ≥60% win after
costs, avg net win > avg net loss, net positive, ≥4 pairs, consistent params,
chronological dev+validation). All runs on MINUTE_5 bars, 2022-01 → 2025-06,
bidirectional, six pairs, evidence JSONs in `artifacts/strategy_research/mr_evidence/`.

## What was tested

Pre-registered **volatility mean-reversion v1** (fade z-extensions) plus its mirror
image **momentum** (follow z-extensions), swept across the full win/reward-risk
frontier (z-entry 2.0–3.5; stop 1.0–2.0 ATR; target 1.5–2.5 ATR; ±trailing).

## Result: 0 of 6 pairs pass, every configuration

| Approach | Win rate (all 6 pairs) | Realized R:R | Net | Pairs passing |
|---|---|---|---|---|
| Mean-reversion, R:R≈1 | 43.8–50.2% | 0.49–0.66 | all negative | 0/6 |
| Mean-reversion, R:R>1 target | 37.3–39.2% | 0.84–1.14 | all negative | 0/6 |
| Mean-reversion + trailing | 32.5–36.7% | 0.56–0.83 | all negative | 0/6 |
| Momentum, R:R≈1 | 41.9–47.5% | 0.48–0.67 | all negative | 0/6 |
| Momentum, R:R>1 target | 34.3–37.3% | 0.85–1.17 | all negative | 0/6 |

**Win rate never exceeds ~50% on any pair, any config, either direction.** Raising
the entry z from 2.5→3.0→3.5 did not raise win rate (47%→47%→44%) — there is no
reversion edge; and its mirror (momentum) is no better — there is no continuation
edge. Every configuration is net-negative after costs.

## Why — the mechanism (not a tuning failure)

On a (near-)driftless series the win rate is pinned by geometry:
`win ≈ stop / (stop + target)`, so `win = 60%` forces `target/stop = 0.667`
(R:R = 0.667). Achieving **both** win ≥ 60% **and** R:R > 1 requires ~10+ points of
directional edge above the 50% coin-flip baseline, *net of costs*. The sweeps show
5-minute FX supplies **zero** exploitable directional edge (both fade and follow
land at ~45–50%), and transaction costs (~1.5 bps/round-trip vs ~5–8 bps target
moves) push every result net-negative. No parameter can manufacture edge that the
price series does not contain.

## Conclusion

**Under the standard exactly as written — single FX pair, price-only, 3–8
trades/weekday, ≥4 of 6 pairs — the 60%-win + R:R>1 + net-positive combination is
not achievable on this dataset, and this is now demonstrated across both directional
strategy families and all six pairs.** The 60% win-rate gate is the binding
constraint: it is jointly incompatible with R:R>1 and net-positive at this
frequency, because the required edge does not exist in single-pair 5-minute price.

## What could actually satisfy the numeric gates (each needs a decision)

1. **Statistical arbitrage / cointegration relative-value** (e.g., EURUSD–GBPUSD or
   JPY-cross baskets). A cointegrated spread is a *synthetic* mean-reverting series
   with a genuine edge that single pairs lack — the one price-based class that can
   plausibly reach high win rate + R:R>1 at frequency. Caveat: it trades *spreads*,
   not the six named FX pairs, so "≥4 pairs pass" must be reinterpreted as "≥4
   independent spreads pass."
2. **Relax one jointly-binding gate.** The achievable frontier is real but elsewhere:
   trend/carry strategies reach net-positive with R:R>1 but ~30–45% win and <1
   trade/day; 5-min scalps reach the frequency but not the win/R:R. Dropping the
   60%-win floor (keeping R:R>1 + net-positive) or the 3–8/day band admits real
   strategies.
3. **Add a non-price signal** (economic-calendar/event, order-flow, or cross-asset)
   — data the current bar set does not contain; would need acquisition.

Per the standard's own clause — no threshold change without a new written decision
approved before testing — proceeding down any of these requires explicit
authorization first.
