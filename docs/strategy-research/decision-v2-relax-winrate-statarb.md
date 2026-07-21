# Architectural Decision v2 — Relax win-rate gate; adopt statistical arbitrage

**Status:** APPROVED by user (2026-07-20), recorded BEFORE testing, per
acceptance-standard-v1's clause forbidding threshold changes without "a new written
architectural decision approved before testing begins." Amends
`acceptance-standard-v1.md`.

## Evidence that justified this decision
Single-pair directional strategies (mean-reversion AND momentum), full win/R:R
frontier, all six pairs on MINUTE_5: win rate never exceeded ~50%, all net-negative
— no directional edge exists in single-pair 5-min FX
(`acceptance-standard-v1-results.md`). A statistical-arbitrage probe showed the
first positive-expectancy, R:R>1, 3–8/day results, but at ~50% win rate. The
60%-win gate proved jointly incompatible with R:R>1 + net-positive at this
frequency even for a genuinely profitable strategy.

## The change
1. **DROP the ≥60% win-rate gate.** All other gates stand unchanged: 3–8
   trades/weekday; **net positive after costs**; **positive expectancy after
   costs**; **realized avg net win / avg net loss > 1.00**; ≥4 instruments pass;
   consistent rules/params across instruments; predefined deterministic stops;
   chronological walk-forward + untouched final-test; complete evidence
   (incl. MAE/MFE, stop metrics, by-month, by-regime, cost-stress,
   execution-degradation, with/without trailing).
2. **"≥4 trading pairs" is interpreted for stat-arb as "≥4 independent spreads."**
   A spread (long pair A, short β·pair B) is the tradeable instrument.
3. **Immediate-fail conditions** are updated to remove the win-rate trigger; all
   others (frequency band, net≤0, expectancy≤0, R:R≤1.0, <4 instruments passing,
   incomplete evidence, final-test violation, forced trades, invalid/inconsistent
   stops, stops widened after entry, risk-limit breaches) remain.

Promotion still requires complete evidence, immutable fingerprints,
authority-boundary verification, and explicit human approval — passing the numeric
gates does not promote.

---

# Pre-registration — Statistical Arbitrage v1 (recorded before the run)

## Thesis
Two cointegrated FX pairs share a common driver; the spread (relative value)
mean-reverts even when neither pair does. The reversion is a genuine edge, absent
in single-pair price.

## Instrument universe (fixed, no post-hoc exclusion)
**All 15 pairwise spreads** of {EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, EURJPY}.
Every spread is reported; ≥4 must independently pass. No spread may be dropped
after results are seen.

## Construction (causal)
- Log mid prices. Rolling hedge ratio β = cov(logA,logB)/var(logB) over `W`=100
  bars, **clamped to [0.2, 5.0]** so an unstable regression cannot create a
  levered, mis-normalised position (this fixes the two-JPY-leg artifact seen in the
  probe).
- Spread s = logA − β·logB; z = (s − rollmean_W(s)) / rollstd_W(s).
- **PnL and costs are normalised by gross notional (1 + |β|)** so every spread is a
  return on deployed capital and cross-spread-comparable.

## Signals / exits
- Enter when flat: `z ≤ −z_entry` → long spread; `z ≥ +z_entry` → short spread
  (`z_entry` tuned on dev+val, same for all spreads). Fill next bar.
- **Predefined deterministic stop:** exit if `|z| ≥ z_stop` (spread diverged past
  the reversion band — a volatility/structure-justified invalidation, reproducible
  from z alone; never widened). `z_stop` tuned on dev+val.
- Target: reversion to `z = 0` (mean). Time-stop at `max_holding` bars.
- Trailing variant reported with/without (deterministic: once `|z|` halves in
  favour, tighten stop to entry z).

## Costs
Half-spread on both legs (sized 1 and β), entry and exit; slippage 0.5 bps/leg/side;
all divided by (1+|β|). Cost-stress ×1.25/1.5/2.0; execution-degradation = +1 bar
entry delay + 0.5 bps/leg extra slippage.

## Window
Dev+validation 2022-01→2025-06 (walk-forward by 6-month block + by month);
final-test 2025-07→2026-06 locked until validation passes.

## Tuning policy
Only `W`, `z_entry`, `z_stop`, `max_holding` may be tuned, on dev+val only, applied
identically to all 15 spreads (no per-spread values). Final-test run once.
