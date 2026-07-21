# Strategy Research — Master Summary

Complete record of every simulation in the search for a strategy meeting the
acceptance requirements. Three asset classes (FX, crypto, equities), three
tightening standards (v1 → v2 → v3), 200+ configurations. Through-line:
**a low-drawdown, capital-preserving compounder is achievable; a consistently
high-return one is not** — every market trades edge against frequency against cost.

All evidence is on branch `feature/multi-regime-strategy-portfolio`:
`docs/strategy-research/*` (write-ups), `artifacts/strategy_research/*` (machine
evidence), `scripts/*` (harnesses). ~40 commits form the dated audit trail.

## The three standards
- **v1** — 3–8 trades/weekday · **≥60% win** · avg win > avg loss · net>0 · ≥4 pairs · walk-forward + locked final test.
- **v2** — proved 60%-win + R:R>1 impossible together → **dropped the win-rate floor**; kept the rest.
- **v3** — **compound from $1,000, no ruin** · minimal losses · low drawdown · consistent (not lumpy) · good risk · market = **stocks/forex**.

## Phase 01 — FX Donchian trend-following (15 runs) — FAIL
Turtle channel breakout, 6 pairs, DAY/HOUR/4H, long+short, all buffers/stops/holds, 2019–2026, net of real costs.

| Config | TF | Dir | Trades | PF | Expectancy | Screen |
|---|---|---|--:|--:|--:|---|
| USDJPY | Day | long | 21 | 0.89 | −0.000305 | fail |
| USDJPY+EURJPY | Day | long | 33 | 0.45 | −0.002783 | fail |
| +USDCAD pool | Day | long | 28 | 0.41 | −0.002701 | fail |
| USDJPY default | Hour | long | 546 | 1.05 | +0.000033 | fail |
| USDJPY buf0.20 | Hour | long | 429 | 1.13 | +0.000096 | screen ok |
| USDJPY buf0.30 s3.0 | Hour | long | 374 | 1.14 | +0.000107 | screen ok |
| USDJPY buf0.25 s2.5 | Hour | long | 405 | 1.12 | +0.000090 | screen ok |
| USDJPY max-hold 500/1000 | Hour | long | 425 | 1.09 | +0.000067 | fail |
| USDJPY | 4-hour | long | 155 | 0.92 | −0.000165 | fail |
| AUDUSD | Hour | short | 459 | 0.97 | −0.000023 | fail |
| USDJPY | Hour | short | 355 | 0.63 | −0.000232 | fail |

**Verdict:** best (USDJPY hourly, PF 1.13, positive, 5/7 walk-forward windows) **fails the 2× cost-stress gate** (cost-sensitivity 1.7–2.6). Shorts and longer holds don't help. No promotable FX trend edge.

## Phase 02 — FX carry — FAIL
Policy-rate carry model (Fed/BoJ/ECB/BoE/RBA/BoC); re-priced trades with real swap income.

| Test | Result | Outcome |
|---|---|---|
| Carry overlay, USDJPY hourly @2× exec | −0.0000108 → −0.0000222 | ~80% of gap closed, still negative |
| Carry filter (trade only carry>0) | −0.000155 | backfired |
| Pure carry-harvest, USDJPY daily | +13.8% @2× cost | 15 trades only |
| Carry-harvest, EURJPY/USDCAD/others | negative | fail |

**Verdict:** the one "win" (USDJPY carry-harvest passing 2× costs) was a single-megatrend artifact — **1 trade (Apr–Dec 2023) = 80% of profit**, 4/15 winners. The price-edge (2019–21) and the carry (2022–25) are anti-correlated. Not tradeable.

## Phase 03 — FX mean-reversion / momentum / stat-arb (v1) — FAIL
MINUTE_5, 2022–2025. Full win/reward frontier on 6 pairs; stat-arb on all 15 spreads.

| Strategy | Win rate | Realized R:R | Net | Pass |
|---|--:|--:|---|--:|
| Mean-reversion R:R≈1 | 44–50% | 0.49–0.66 | negative | 0/6 |
| Mean-reversion R:R>1 | 37–39% | 0.84–1.14 | negative | 0/6 |
| Mean-reversion + trailing | 32–37% | 0.56–0.83 | negative | 0/6 |
| Momentum R:R≈1 | 42–48% | 0.48–0.67 | negative | 0/6 |
| Momentum R:R>1 | 34–37% | 0.85–1.17 | negative | 0/6 |
| Stat-arb (15 spreads × 6 params) | 37–42% | 0.80–1.09 | negative | 0/15 |

**Verdict:** win rate never exceeds ~50% on any pair/config/direction, and higher entry thresholds didn't help → no directional edge in 5-min FX. **60%-win + R:R>1 is mathematically incompatible without a real edge.** The true blocker is **frequency × cost**, not win rate.

## Phase 04 — Crypto trend-breakout portfolio (v2) — TECHNICAL PASS, breakeven OOS
20 coins, hourly, one config (40-bar entry / 40-bar exit / 3-ATR stop), 2022–2026.

| Window | Net | PF | R:R | Trades/day | Coins + | Gates |
|---|--:|--:|--:|--:|--:|---|
| Dev+validation | +15.17 | 1.107 | 2.60 | 5.36 | 17/20 | pass |
| **Locked final test** | **+0.004** | 1.000 | 2.39 | 5.22 | 11/20 | pass but **breakeven** |

Cost-robust to 2× costs (+10.38) and 3× slippage in-sample. Money (~$20k, $1k/position): +$15k dev+val (≈$16k of it in 2024 alone); final year ≈ $0 with a −33% drawdown.

**Verdict:** first strategy to pass the untouched final test — technically — but out-of-sample profit is breakeven (trend decay) and the profile is lumpy. Passed the letter of v2, not the spirit → prompted v3.

## Phase 05 — v3 consistency: crypto MR (ruin) → equity momentum (fits)

| Attempt | Market | Outcome | Why |
|---|---|---|---|
| Mean-reversion, compounded | Crypto | account → $0 (ruin) | MR fades moves; crypto trends → fights the tape |
| Market-neutral momentum | Stocks | **fits the brief** | diversifiable + dollar-neutral → smooth, no ruin |

## WINNER — Market-neutral equity momentum (stocks)
Rank 176 US large/mid-caps by 12-month return (skip last month); long top 30 / short bottom 30, dollar-neutral; rebalance daily; compound. Cannot blow a $1,000 account by construction.

Full 2022-01 → 2026-06 from **$1,000 → $1,313** (+31%, **8.2%/yr**) at 1× gross · **max DD −12.3%** · Sharpe 0.78 · **64% months positive** · worst day −3.4% · 7.3 trades/day · **no ruin**.

| Window | Return | Sharpe | Max DD | Months + |
|---|--:|--:|--:|--:|
| Dev+validation 2022-01→2025-06 | +5.2% | 0.26 | −12.3% | 60% |
| **Locked final test 2025-07→2026-06** | **+27.0%** | **1.98** | **−4.5%** | **83%** |
| 2× leverage, full period | +65.5% | 0.78 | −23.5% | 62% |

**Caveats (do not over-trust):** survivorship bias (current-survivors universe flatters momentum — needs point-in-time data); regime-dependent (weak 2022–25, strong final year); 1-year final-test sample; modest ~8%/yr base. **Next step is forward-testing, not more tuning.**

## Meta-conclusion
1. FX has no exploitable intraday edge — cost matches the move at 3–8 trades/day.
2. The real edges (trend, carry) are low-frequency — can't meet a high-frequency gate.
3. Crypto trends but is lumpy and decaying — one big year, deep drawdowns, breakeven OOS.
4. Stocks are the right market for consistency — diversifiable → market-neutral, smooth, no ruin.
5. **Consistent + low-drawdown + no-ruin is achievable; consistent + reliably high-return is not.**
