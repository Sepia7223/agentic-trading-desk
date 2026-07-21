# Strategy Research — Master Summary

Complete record of every simulation in the search for a strategy meeting the
acceptance requirements. Three asset classes (FX, crypto, equities), three
tightening standards (v1 → v2 → v3), 200+ configurations.

**Revised 2026-07-21 to incorporate reviewer assessment** (§Reviewer assessment).
Several conclusions in the first draft were overstated; the corrected wording below
is the record of authority. Headline finding, corrected:

> **Within the tested strategy classes, higher return consistently required
> accepting greater drawdown, concentration, turnover, or regime dependence. No
> tested approach achieved both high returns and stable low drawdown after realistic
> costs.** (This is a statement about the tested space — not a universal law.)

All evidence is on branch `feature/multi-regime-strategy-portfolio`:
`docs/strategy-research/*` (write-ups), `artifacts/strategy_research/*` (machine
evidence), `scripts/*` (harnesses). ~40 commits form the dated audit trail.

## Status of the leading candidate
**Equity market-neutral momentum — PROMOTE TO RESEARCH CANDIDATE, NOT PRODUCTION.**
The result is promising but **provisional**: compromised by survivorship bias, a
short (1-year) final test, and unresolved short-selling / small-account
implementation assumptions. No autonomous deployment. Next phase is point-in-time
reconstruction + forward paper-testing of the frozen spec (§Recommended decision).

## Measurement standard (to add to every strategy record)
Decimal expectancies like `+0.000107` are hard to interpret. Future records should
report, per strategy: **gross expectancy · net expectancy · average cost/trade ·
cost as % of gross edge · break-even cost vs actual/stressed cost · median & mean
trade · tail-loss distribution**, all in normalized risk units (R) or basis points
after cost. A strategy whose break-even cost is only marginally above observed cost
is not deployable even when the base test is positive.

## The three standards
- **v1** — 3–8 trades/weekday · **≥60% win** · avg win > avg loss · net>0 · ≥4 pairs · walk-forward + locked final test.
- **v2** — dropped the win-rate floor (see Phase 3 correction); kept the rest.
- **v3** — compound from $1,000 · minimal losses · low drawdown · consistent (not lumpy) · good risk · market = **stocks/forex**.

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

**Verdict:** best (USDJPY hourly, PF 1.13, positive, 5/7 walk-forward windows) **fails the 2× cost-stress gate** (cost-sensitivity 1.7–2.6). A PF of ~1.13 and expectancy ~0.0001/trade leave no room for spread variation, slippage, latency, financing, or broker fills — any small execution mismatch absorbs the edge. Rejection was correct. *Record gap: report expectancy in bps-after-cost + cost-as-%-of-gross-edge so the failure mechanism is explicit.*

## Phase 02 — FX carry — FAIL
Policy-rate carry model (Fed/BoJ/ECB/BoE/RBA/BoC); re-priced trades with real swap income.

| Test | Result | Outcome |
|---|---|---|
| Carry overlay, USDJPY hourly @2× exec | −0.0000108 → −0.0000222 | ~80% of gap closed, still negative |
| Carry filter (trade only carry>0) | −0.000155 | backfired |
| Pure carry-harvest, USDJPY daily | +13.8% @2× cost | 15 trades only |
| Carry-harvest, EURJPY/USDCAD/others | negative | fail |

**Verdict:** the one "win" was a **historically profitable regime exposure, not a repeatable strategy** — 1 trade (Apr–Dec 2023) = 80% of profit, 4/15 winners. Price-edge (2019–21) and carry (2022–25) are anti-correlated: the carry overlay didn't add an independent return source, it partially offset losses in one period and rode a directional regime later. Correctly rejected.

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

**Verdict (corrected):** win rate never exceeded ~50% on any pair/config/direction, and higher entry thresholds didn't help. **Correction:** 60%-win and R:R>1 are **NOT mathematically incompatible** — they are mathematically compatible (e.g. 60% win, 1.1R win / 1R loss ⇒ +0.26R gross expectancy), simply rare and *unsupported by the tested strategies and datasets*. Defensible wording: *no tested 5-minute FX strategy demonstrated the edge required to sustain both a 60% win rate and average wins exceeding average losses after costs.* The binding constraint is **frequency × cost**: at 5-min frequency, cost consumes a large fraction of the small gross move. *Add a per-strategy break-even-cost analysis.*

## Phase 04 — Crypto trend-breakout portfolio (v2) — REJECTED (economic failure despite gate compliance)
20 coins, hourly, one config (40-bar entry / 40-bar exit / 3-ATR stop), 2022–2026.

| Window | Net | PF | R:R | Trades/day | Coins + | Gates |
|---|--:|--:|--:|--:|--:|---|
| Dev+validation | +15.17 | 1.107 | 2.60 | 5.36 | 17/20 | pass |
| **Locked final test** | **+0.004** | 1.000 | 2.39 | 5.22 | 11/20 | pass but **breakeven** |

Dev+val profit was heavily concentrated in 2024; final-test max drawdown ≈ **−33%** for ≈ 0 return (Calmar ≈ 0). Money (~$20k, $1k/position): +$15k dev+val (≈$16k of it in 2024 alone); final year ≈ $0.

**Verdict (corrected):** calling this a "technical pass" is fair only because the written v2 gates permitted it; **economically it failed** — ~0% return with a −33% drawdown is unacceptable risk-adjusted. Reclassified: *rejected for economic failure despite mechanical gate compliance.* This exposed a weakness in v2 — the gates weren't tied to **return quality**. Future gates need minimums for: return/drawdown, concentration by year & by instrument, contribution of the largest trades, regime stability, net return after stressed costs.

## Phase 05 — v3 consistency: crypto MR (ruin) → equity momentum (best candidate)

| Attempt | Market | Outcome | Why |
|---|---|---|---|
| Mean-reversion, compounded | Crypto | account → $0 (ruin) | MR fades moves; crypto trends → fights the tape |
| Market-neutral momentum | Stocks | **best candidate** | diversifiable + dollar-neutral → smooth simulated series |

## LEADING CANDIDATE — Market-neutral equity momentum (stocks) — PROVISIONAL
Rank 176 US large/mid-caps by 12-month return (skip last month); long top 30 / short bottom 30, dollar-neutral; rebalance daily; compound.

Full 2022-01 → 2026-06 from **$1,000 → $1,313** (+31%, **8.2%/yr**) at 1× gross · **max DD −12.3%** · Sharpe 0.78 · **64% months positive** · worst simulated day −3.4% · ~7.3 "trades"/day.

| Window | Return | Sharpe | Max DD | Months + |
|---|--:|--:|--:|--:|
| Dev+validation 2022-01→2025-06 | +5.2% | 0.26 | −12.3% | 60% |
| **Locked final test 2025-07→2026-06** | **+27.0%** | **1.98** | **−4.5%** | **83%** |
| 2× leverage, full period | +65.5% | 0.78 | −23.5% | 62% |

### Why it is provisional (reviewer-flagged, all material)
1. **Survivorship bias — potentially invalidating, not a minor caveat.** The 176-name universe is stocks liquid *today*; it omits delisted/bankrupt/acquired/removed names. Especially dangerous on the **short leg** (shorting historical losers, but a survivor-only universe drops some of the worst losers because they no longer exist). Return/Sharpe/DD are **provisional** until rebuilt on point-in-time membership with delisted-security returns and corporate actions.
2. **Final-test dominance / attribution.** Most lifetime gain came from the 1-year locked window (+27% vs +5.2% over 3.5 yrs). Could be a genuine emerging edge, a favorable momentum regime, universe differences, an outlier, or unintended factor exposure. Needs attribution before trust.
3. **Hidden factor/sector exposure.** Dollar-neutral ≠ risk-neutral. Long-winners/short-losers can carry concentrated beta/size/value/quality/vol/sector/short-interest/crowding exposure. Measure daily factor + sector decomposition.
4. **Short-side realism unmodeled.** Borrow availability, borrow fees, hard-to-borrow exclusions, recall risk, dividends owed on shorts, corporate actions, gap/asymmetric-loss risk. Weak stocks are often expensive or impossible to borrow.
5. **Account-size realism.** At 1× gross on $1,000, ~$500 long / $500 short across 60 names ≈ **$16.67/position** — below many brokers' minimums, fractional shorting often unavailable, costs could dominate. May work as a **return series** but be **un-implementable at a literal $1,000 account.**
6. **"Cannot blow up" — removed.** Corrected to: *under the tested return series and simulated exposure assumptions, it did not experience ruin.* Live long-short can still fail via squeezes, gaps, borrow recall, correlation spikes, or operational error.
7. **Trade-count ambiguity.** "7.3/day" needs a definition — orders vs fills vs position entries/exits vs rebalance events vs partial adjustments. ~7 symbols changing ≈ ~14 orders. For cost/execution modeling, report **one-way and round-trip turnover and cost per dollar traded**, not a single trade count.
8. **Daily rebalance may overtrade a slow signal.** 12-month momentum is slow; test **weekly / biweekly / monthly / buffered (hysteresis)** rebalancing (e.g. enter top-25, hold while ≤ rank-40, exit below 40) and keep daily only if it adds net risk-adjusted value after cost.
9. **Short (1-yr) final test.** 83% positive months ≈ 10/12 — small sample; Sharpe 1.98 over one year has wide CIs. Supplement with rolling pseudo-OOS, multiple non-overlapping locked windows, regime-stratified results, and **block-bootstrap** CIs.
10. **De-emphasize 2× leverage.** Sharpe unchanged (0.78), drawdown ~doubles — leverage amplifies, doesn't improve. Start **below** 1× gross, no leverage, given the preservation objective.

## Meta-conclusion (corrected)
1. **Tested FX strategies did not produce a robust, economically meaningful edge after realistic costs** — so stop allocating research to ordinary price-based retail FX *unless materially different data or a new hypothesis appears*. (Not a claim the entire FX market is edgeless — the search space was bounded: specific pairs/years/datasets/execution assumptions and a handful of strategy families. Edges may exist in event-driven, order-book, cross-market, or different-horizon spaces not tested.)
2. The real edges found (trend, carry) were low-frequency — can't meet a high-frequency gate.
3. Crypto trends but was lumpy and decayed out-of-sample — one big year, deep drawdowns, breakeven OOS.
4. **Among the tested approaches, diversified market-neutral equity momentum was the closest fit to the consistency/drawdown objective — result provisional** (survivorship bias, short final test, implementation unresolved). Not "stocks are the right market" as a proven claim.
5. **Within the tested classes, higher return required greater drawdown / concentration / turnover / regime dependence; none achieved high return + stable low drawdown after realistic costs.**

## Recommended decision
**Promote the equity strategy to a research candidate; no autonomous deployment.**
Research status: promising · Capital status: none yet · Next phase: point-in-time
reconstruction + forward paper test of the frozen spec · Initial live (only after
validation): very small capital, no leverage.

### Gates before paper trading
Point-in-time constituents (incl. delisted) · corporate actions modeled · borrow
availability + daily borrow cost · realistic bid/ask + slippage · financing on both
legs · verified implementable at intended account size · factor + sector exposure
measured · daily vs weekly vs buffered rebalance compared · exact trade/turnover
definitions reconciled · delayed-entry tests · stress/fault simulations.

### Gates before live trading
3–6 months paper execution · broker-realistic order sizes · zero unresolved
reconciliation errors · forward results aligned with simulation · realized costs
within modeled range · borrow consistent with assumptions · drawdown within
predefined limits · no hidden concentration/factor exposure · **no leverage** ·
hard portfolio + operational kill switches.

### Suggested first forward-test controls
| Control | Starting rule |
|---|---|
| Gross exposure | 0.50×–1.00× |
| Net exposure | within ±5% |
| Single-name gross weight | max 1–2% |
| Sector net / gross exposure | max ±5% / capped |
| Daily turnover | explicit maximum |
| Short borrow fee | reject above threshold; exclude unborrowable before ranking |
| Daily loss halt | 0.75–1.0% |
| Drawdown review / shutdown | 5% / 8–10% |
| Leverage | none initially |
| Rebalancing | test weekly / buffered vs daily |

*(Percentages are starting points, to be matched to the actual portfolio design and broker constraints.)*

## Reviewer assessment (2026-07-21)
| Area | Assessment |
|---|---|
| Research discipline | Strong |
| Willingness to reject strategies | Strong |
| Cost awareness | Strong |
| Out-of-sample discipline | Good |
| Statistical certainty | Moderate–weak |
| Equity momentum result | Promising, not proven |
| "Cannot blow account" claim | Overstated (corrected) |
| Readiness for autonomous live trading | Not yet |
| Best next action | Point-in-time rebuild + forward test |

Strongest defensible summary: *the original high-frequency, high-win-rate brief was
unrealistic for the tested markets and cost structure; most apparent edges were too
weak, too concentrated, too infrequent, or too regime-dependent. Diversified
long-short equity momentum is the first candidate whose simulated behavior broadly
matches the capital-preservation objective, but its evidence is materially
compromised by survivorship bias, a short final test, and unresolved short-selling
and small-account implementation assumptions. Do not discard it; do not deploy it
yet. Stop tuning, rebuild with point-in-time data, then forward-test the frozen
specification.*
