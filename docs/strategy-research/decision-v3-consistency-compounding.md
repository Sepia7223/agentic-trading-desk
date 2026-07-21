# Architectural Decision v3 — Consistency, compounding, capital preservation

**Status:** APPROVED by user (2026-07-21), recorded before testing. Amends v2.

## Why
The v2-passing crypto trend portfolio was technically compliant but lumpy: ~all
profit in one year (2024), −33% drawdowns, breakeven out-of-sample. The user
rejects that profile.

## The new standard (v3)
Keep from v2: **3–8 trades/weekday** (portfolio-level allowed); **no win-rate
floor**; positive expectancy; chronological walk-forward + untouched final-test;
consistent params across instruments; predefined deterministic stops; full evidence.

**Remove:** the R:R>1 gate is replaced by the consistency mandate below (a strategy
may have big *or* consistent wins, but losses must be small — so R:R is no longer the
right single lens).

**Add — the core of v3:**
1. **Compounding.** Equity compounds; every dollar of profit is reinvested. The
   backtest runs a real compounding equity curve, not additive P&L.
2. **Capital preservation / no blow-up.** Starting from **$1,000**, the account must
   never be at risk of ruin. Enforced by construction: **fixed-fractional risk per
   trade** (small, e.g. ≤ 1% of equity), plus a **portfolio heat cap** (max total
   risk open at once) so correlated positions cannot combine into a catastrophic
   loss.
3. **Minimal losses.** No large individual losses; every trade has a tight,
   predefined stop. Worst single realised loss bounded (e.g. ≤ ~1–2% of equity).
4. **Consistency.** Smooth equity curve — reject "big win + big loss." Measured by:
   **max drawdown** (target small, e.g. ≤ ~15%), **% of months profitable** (high),
   **longest losing streak**, and return **stability** (Sharpe/Sortino; low
   volatility of monthly returns).
5. **Good risk, never excessive.** Position sizing is volatility-aware and capped;
   no martingale, no averaging into losers, no un-stopped positions.

## Immediate-fail conditions (v3)
- frequency outside 3–8/weekday
- net/expectancy ≤ 0 after costs (must compound upward)
- max drawdown exceeds the approved ceiling (excessive risk / not consistent)
- any single loss exceeds the per-trade risk cap (stop not honoured)
- account could reach ruin from $1,000 under the sizing rule
- required evidence incomplete; final-test isolation violated; forced trades

## Implication for strategy type
Trend-following is **disqualified** (inherently lumpy, deep drawdowns). The search
targets **mean-reversion and market-neutral (pairs/stat-arb)** strategies, which aim
for many small controlled outcomes, run with strict fixed-fractional sizing and a
portfolio heat cap so a $1,000 account compounds without ruin. Consistency still
requires a genuine, stable edge — the open question the search must answer honestly.
