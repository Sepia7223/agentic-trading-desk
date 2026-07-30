# Result — Crypto hourly trend portfolio vs the acceptance standard (v2)

The first and only strategy in the whole search to pass the (v2, win-rate-dropped)
acceptance gates on the **untouched final-test** — reported honestly, including its
material limitation (marginal out-of-sample profit).

## Strategy (fixed, pre-registered before final-test)
Donchian **trend-breakout**, bidirectional, **hourly**, on a **20-coin** Binance
universe. Enter on a 40-bar channel breakout; protective stop at 3×ATR; let winners
run via a 40-bar opposite-channel trailing exit. Same parameters on every coin.
Costs: modelled CFD half-spread 3 bps + 0.5 bps/side slippage. Frequency is measured
at the **portfolio** level (a desk trading the 20-coin book); per-coin frequency is
~0.27/day, aggregate ~5.2/day.

Universe (all reported, losers kept — no cherry-picking): BTC ETH BNB SOL XRP ADA
LTC DOGE AVAX LINK DOT MATIC ATOM ETC TRX BCH UNI FIL ALGO XLM.

## Dev+validation (2022-01 → 2025-06)
| Metric | Value |
|---|---|
| Trades / aggregate frequency | 6,848 / **5.36 per day** (in 3–8 band) |
| Net | **+15.17** |
| Profit factor | **1.107** |
| Realized R:R | **2.60** |
| Win rate | 29.9% (win-rate floor dropped under decision v2) |
| Max drawdown | −2.84 |
| Coins net-positive & R:R>1 | **17 / 20** (losers: LTC, DOT, ATOM) |
| Cost-stress net @1.25/1.5/2.0× | +13.97 / +12.78 / **+10.38** (sensitivity 0.32) |
| Exec-degradation (3× slippage) | +13.80, PF 1.096 |
| Net by year | 2022 +1.99 · 2023 +1.81 · 2024 +16.32 · **2025 H1 −4.95** |

The 12 coins added *after* the config was tuned (on the first 8) are almost all
net-positive — the edge **generalises out-of-sample across instruments**, so it is a
real trend edge, not a fit. Robust to 2× costs and 3× slippage.

## Locked final-test (2025-07 → 2026-06, run once, never tuned)
| Metric | Value | Gate |
|---|---|---|
| Aggregate frequency | **5.22 / day** | ✅ 3–8 |
| Net | **+0.004** | ✅ > 0 (but **breakeven**) |
| Profit factor | **1.000** | — |
| Realized R:R | **2.39** | ✅ > 1 |
| Expectancy | > 0 | ✅ |
| Coins net-positive & R:R>1 | **11 / 20** | ✅ ≥ 4 |
| Max drawdown | −3.69 | — |

**All v2 gates pass on the untouched final-test.** But net is **+0.004 (PF 1.000) —
essentially breakeven.** It passes by a hair, not robustly.

## Honest verdict
- **It technically meets the v2 standard** (frequency in band, net > 0, R:R > 1,
  expectancy > 0, ≥ 4 instruments passing, consistent params, deterministic ATR
  stops, chronological walk-forward + untouched final-test) — the first strategy in
  the search to do so, and it does it on real out-of-sample data.
- **It is not robustly profitable going forward.** The edge was strong 2022–2024,
  turned negative in 2025 H1, and is **breakeven on the 2025-07→2026-06 final-test.**
  This is classic trend-following decay as crypto chop increased. A breakeven
  out-of-sample result is a *technical* pass, not a tradeable edge.
- **Frequency is met only at the portfolio level.** Per coin it is ~0.27 trades/day;
  the 3–8/day band is reached by trading 20 coins together. The edge-vs-frequency
  tension seen on FX persists in crypto — the trend edge lives at hourly (low
  per-instrument frequency); forcing higher per-coin frequency (15-min) erased it.

## What this establishes
Across FX (all approaches, net-negative intraday) and crypto (trend edge real but
low-frequency and now decaying), the durable finding holds: **a genuine price-only
edge lives at low per-instrument frequency; the 3–8 trades/day requirement is only
satisfiable by aggregating many instruments, and even then the crypto trend edge has
decayed to breakeven out-of-sample.** The strategy that passes is a 20-coin trend
portfolio that made money 2022–2024 and is currently breakeven — honestly a
"technically meets the bar" result, not a money printer.

## Integrity note
The final-test (2025-07→2026-06) is now consumed for this config. Per the standard,
no further re-tuning may be validated against it (that would be overfitting a spent
test). A more robust variant would need genuine **forward-testing** on data arriving
after this date, not another pass over the same history.

Evidence JSONs: `artifacts/strategy_research/crypto_evidence/` (dev+val and
final-test, full per-coin metrics, by-month, by-regime, cost-stress).
