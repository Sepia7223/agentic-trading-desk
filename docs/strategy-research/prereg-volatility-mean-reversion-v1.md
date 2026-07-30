# Pre-registration — Volatility Mean-Reversion v1

**Recorded BEFORE any simulation run, per acceptance-standard-v1 §"Pre-registration
protocol".** Committed prior to execution. These rules and the pair list are fixed;
parameters may be tuned ONLY on dev+validation (walk-forward), never on the locked
final-test, and no rule may change after final-test results are viewed.

## Thesis
On FX majors, short-horizon over-extensions from a local mean tend to revert. Enter
against a statistically stretched move; take profit on partial reversion; cap loss
with a volatility-scaled stop placed beyond the noise.

## Instrument / data
- Bars: **MINUTE_5**, bid+ask, per pair.
- Pairs (all six, identical rules/params): EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD,
  EURJPY.
- Windows: warmup 2021-11-01+; **dev+validation 2022-01-01 → 2025-06-30**
  (walk-forward, reported by 6-month block and by month); **final-test
  2025-07-01 → 2026-06-30 (locked, untouched until validation passes)**.
- Direction: **bidirectional** (long fade of down-extensions, short fade of
  up-extensions). Mean-reversion requires both sides; this is research only and
  does not alter the production long-only contract. Long-only results are reported
  separately as a secondary cut.

## Signals (causal — indicators use only bars strictly before the fill bar)
- Local mean = SMA(mid_close, `W`=20).
- Dispersion = rolling stdev(mid_close, `W`=20) → `sigma`.
- `z` = (mid_close − mean) / sigma.
- **Long entry** when `z ≤ −z_entry` (`z_entry`=2.0) and flat.
- **Short entry** when `z ≥ +z_entry` and flat.
- Fill on the **next bar's** open (long: ask; short: bid) + slippage.

## Stop (predefined, volatility-justified, deterministic)
- ATR = mean true range over `atr_window`=14 (on mid).
- Stop distance = `stop_atr`=1.0 × ATR at entry, placed beyond entry
  (long: entry − stop_dist; short: entry + stop_dist).
- Reproducible from (entry bar, ATR); never widened after entry.

## Target (deterministic)
- Target distance = `target_atr`=1.5 × ATR at entry (long: entry + target_dist;
  short: entry − target_dist). **Planned reward-to-risk = target_atr / stop_atr =
  1.50** (> 1.0 by construction; realized R:R is measured and gated).

## Exits (priority per bar after entry)
1. **Stop** — adverse-first: if a bar's range touches both stop and target, the
   stop is assumed hit first (conservative).
2. **Target**.
3. **Time-stop** at `max_holding`=24 bars (2h): exit at that bar's mid close.

## Trailing variant (reported WITH and WITHOUT, per standard)
- Deterministic rule: once price reaches +1.0 × stop_dist in favor, move stop to
  breakeven (entry). No other adjustments. Never widened.

## Costs
- Real half-spread from bid/ask on both sides; slippage `0.5 bps`/side;
  commission 0; funding pro-rated per day held (negligible intraday).
- **Cost-stress**: re-price at 1.25× / 1.5× / 2.0× (spread+slippage).
- **Execution-degradation**: entry delayed one extra bar + `+0.5 bps`/side extra
  slippage; net re-reported.

## Regime labelling (deterministic, for "results by regime")
At entry: fast SMA(20) vs slow SMA(200) on mid, scaled by ATR —
`|SMA20 − SMA200| < 0.5×ATR` → **RANGE**; else **TREND_UP** (SMA20>SMA200) or
**TREND_DOWN**.

## Documented exclusion rule (fixed before the run)
**None.** No pair may be excluded post-hoc. All six pairs are reported; ≥4 must
independently pass every gate for the strategy to pass.

## Tuning policy
Only `W`, `z_entry`, `atr_window`, `stop_atr`, `target_atr`, `max_holding` may be
adjusted, and only against dev+validation, applied identically to all pairs
(no pair-specific values). Each tuned parameter set is re-recorded here before its
run. The final-test is executed once, for the validation-passing set only.
