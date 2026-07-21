# Mandatory Strategy Simulation Acceptance Standard (v1)

**Status:** BINDING. Pre-registered before testing, per the standard's own
requirement that no exception or threshold change is valid without "a new written
architectural decision approved before testing begins."
**Authority:** user directive, 2026-07-20. Supersedes the looser M12 research
gates for all strategy acceptance from this date forward.
**Scope:** research/simulation acceptance only. Passing these gates does NOT
promote a strategy — promotion still requires complete evidence, immutable
fingerprints, authority-boundary verification, and explicit human approval.

## Numerical acceptance gates (ALL required)

1. **Trade frequency:** average **≥ 3 and ≤ 8 completed trades per available
   weekday trading day** over the approved validation period.
2. **Win rate:** **≥ 60%** after all spreads, commissions, slippage, financing,
   and execution costs.
3. **Net profitability:** strictly **positive net profit after costs**.
4. **Breadth:** **≥ 4 trading pairs must independently pass every gate.** Fewer
   than four passing pairs = unacceptable.
5. **No post-hoc pair exclusion:** no losing pair may be hidden, excluded, or
   removed after results are viewed unless the exclusion rule was documented
   before the simulation began.
6. **Consistent rules:** the same strategy rules and parameter set applied across
   all pairs. Pair-specific optimization is prohibited unless separately
   authorized and validated.
7. **No manufactured trades:** trades may not be inserted, duplicated, forced, or
   manufactured to satisfy the frequency gate.
8. **No post-final-test tuning:** entries, exits, stops, targets, filters, and
   costs may not change after final-test results have been viewed.
9. **Validation method:** chronological walk-forward validation + an untouched
   final-test period.

### Reward / risk and stop-loss gates (ALL required, in addition)

10. **Predefined justified stop on every trade** — based on documented market
    structure, volatility, or invalidation logic; deterministic and reproducible.
    No arbitrary, excessively wide/tight, or post-entry-widened stops.
11. **Realized reward-to-risk:** **average net win / average net loss > 1.00**
    (strictly). A ratio ≤ 1.00 fails.
12. **Stops move only by a deterministic rule documented before the sim.** Stops
    may never be widened after entry to avoid recording a loss.
13. **Positive expectancy after costs:**
    `(win_rate × avg_net_win) − (loss_rate × avg_net_loss) > 0`.
14. Win-rate and R:R gates are **both** required; neither substitutes for the
    other. Drawdown, tail-loss, loss-concentration, and stop-behavior limits also
    apply on top.

## Immediate-fail conditions

- avg frequency < 3/weekday or > 8/weekday
- win rate < 60%
- net profit after costs ≤ 0
- fewer than 4 pairs pass
- required evidence incomplete
- final-test isolation violated
- trades forced or thresholds weakened
- any trade lacks a valid predefined stop
- stop logic inconsistent / not reproducible
- stops widened after entry
- avg net win ≤ avg net loss (R:R ≤ 1.00)
- a few large wins conceal consistently poor stop behavior
- losses exceed configured per-trade / daily / strategy / portfolio risk limits

## Required evidence (report MUST include, per pair and aggregate)

Total trades · avg trades per available weekday · winning trades · losing trades ·
win rate · gross profit · gross loss · net profit after costs · profit factor ·
average win · average loss · maximum drawdown · results by pair · results by month
· results by market regime · cost-stress results · execution-degradation results.

**Stop/R:R evidence also required:** initial stop distance · stop distance as % of
entry · stop distance in volatility units · planned R:R · realized average R:R ·
maximum adverse excursion (MAE) · maximum favorable excursion (MFE) · stop-loss
exit count · % of trades stopped out · average loss after costs · largest loss ·
average win after costs · largest win · frequency of stop adjustments · results
WITH and WITHOUT any trailing-stop mechanism.

## Data constraint (as-built)

Minute-scale bars (MINUTE_5 / MINUTE_15) — required to reach 3–8 trades/weekday —
cover **2021-11-01 → 2026-06-30** only. Therefore the approved validation window at
this frequency is: warmup from 2021-11, dev+validation **2022-01-01 → 2025-06-30**
(walk-forward), untouched final-test **2025-07-01 → 2026-06-30**. Coarser history
(2019+) exists only at HOUR/DAY, which cannot meet the frequency gate.

## Pre-registration protocol

Before each simulation campaign: the strategy family, entry rule, exit rule, stop
rule (structure/volatility/invalidation), target rule, trailing rule (if any),
cost model, parameter set, pair list, and any documented pair-exclusion rule are
fixed and recorded here (or in a linked pre-registration note) BEFORE the run.
Final-test is executed once, only for candidates that pass walk-forward
validation, and never re-run with changed rules.
