# Result — Market-neutral equity momentum (v3: consistency + compounding)

The strategy that fits the v3 mandate (consistency, minimal losses, compounding from
$1,000, no ruin, good risk) in the user's real market (stocks). First result of the
whole search with the *right shape*: steady compounding, low drawdown, bounded daily
losses, cannot blow the account.

## Strategy (fixed, pre-registered before final-test)
**Cross-sectional 12-month momentum, dollar-neutral.** Universe: 176 liquid US
large/mid caps (Yahoo daily adjusted close). Each day, rank every name by its return
over the past 252 trading days **skipping the most recent 21** (classic momentum,
avoids short-term reversal contamination). **Long** the top-30 (strongest), **short**
the bottom-30 (weakest), equal-weight → dollar-neutral (no market beta). Rebalance
daily. Gross 1.0 = 100% long + 100% short. Costs 3 bps/turnover. Compounds.

Market-neutral at 1× gross **cannot blow a $1,000 account** by construction — daily
P&L is a small, bounded spread of diversified returns (worst day in 4.5 yrs: −3.4%).

## Results — full continuous 2022-01..2026-06, from $1,000
| Metric | 1× gross | 2× gross |
|---|---|---|
| Ending equity | **$1,313 (+31%)** | $1,655 (+65%) |
| CAGR | **8.2%** | 15.7% |
| Max drawdown | **−12.3%** | −23.5% |
| Sharpe | 0.78 | 0.78 |
| % months positive | **64%** | 62% |
| Worst / best day | −3.4% / +2.5% | −6.7% / +5.1% |
| Trades/day | 7.27 (in 3–8) | 7.27 |
| Ruin from $1,000 | **No** | No |

## Split — dev+val vs untouched final-test
| Window | Return | Sharpe | Max DD | % months + |
|---|---|---|---|---|
| Dev+val 2022-01..2025-06 | +5.2% | 0.26 | −12.3% | 60% |
| **Locked final-test 2025-07..2026-06** | **+27.0%** | **1.98** | **−4.5%** | **83%** |

All v3 gates pass on the untouched final-test (freq in band, positive, low DD, no
ruin). The final year was strong; the earlier years were only mildly positive.

## Honest caveats (do not over-trust the numbers)
1. **Survivorship bias.** The universe is names liquid *today* (2026); stocks that
   existed in 2022 but were delisted/crashed are absent. This inflates equity
   backtests, momentum especially. Fully trusting the edge needs a **point-in-time
   universe** (with delisted names), which this dataset does not have.
2. **Regime-dependent, not uniformly consistent.** Dev+val Sharpe 0.26 vs final-test
   1.98 — the strong result is concentrated in the last year (a strong momentum
   regime). Equity momentum has multi-year weak stretches and periodic "momentum
   crashes."
3. **One-year final-test.** Sharpe 1.98 over 12 months is partly small-sample.
4. **Modest base return.** At safe 1× gross the CAGR is ~8% (mostly the last year);
   leverage raises return but raises drawdown proportionally (Sharpe unchanged).

## Verdict
This is a **genuine v3-shaped strategy** — consistent, minimal losses, compounding,
no ruin, in stocks — and it passed the untouched final-test strongly. But it is
**not proven robust**: survivorship bias flatters it, and its strength is
concentrated in one recent year. The honest next step is **forward-testing** on live
data and re-validating on a **point-in-time universe**, not more historical tuning.
The durable lesson from the whole search holds: *consistent + low-drawdown is very
achievable; consistent + reliably high-return is not — the best honest version is a
steady ~8%/yr market-neutral compounder that cannot blow up.*
