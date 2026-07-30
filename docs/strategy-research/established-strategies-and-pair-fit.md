# Established Strategies and Pair Fit — Research for a Long-Only FX Desk

Durable record of the strategy research (2026-07-20). Two adversarially-verified
web-research passes: (A) strategy archetypes and their documented pair fit and
long-only viability; (B) per-pair behavioral characterization and sessions.
Universe: **AUDUSD, EURJPY, EURUSD, GBPUSD, USDCAD, USDJPY**. Bars: daily / 1h /
15m / 5m (2019–2025). Binding constraint: **the desk is long-only** and pays real
costs (spread + slippage + swap).

## Bottom line (the decision)

**FX spot has no structural drift.** A pair is a relative price — there is no
equity-risk-premium tailwind. This one fact reframes everything: in equities,
long-only strategies are partly rescued by secular upward drift; in FX there is
no such rescue. Consequently:

- **Long-only cripples symmetric strategies** — mean-reversion and plain
  breakout keep only half their signals with nothing to compensate the lost half.
- **Long-only is *compatible* with directional-premium strategies** — carry (and
  carry-driven trend). Carry's premium lives in one direction of a pair; for
  today's positive-carry pairs that direction is "long," so long-only forfeits
  nothing on the carry axis. **This is the only place the constraint helps.**

**Recommended core for the first promotable strategy:**
**carry-aware trend-following on daily bars, focused on USDJPY and EURJPY** (the
two pairs that are both positive-carry longs and had persistent multi-year
uptrends), with a **let-winners-run exit** (trailing channel / generous
max-holding, *not* a fixed target). USDCAD is a weaker positive-carry secondary.

This directly explains why the earlier strategies lost: they were symmetric
strategies (trend-pullback, volatility-breakout, range-mean-reversion) crippled
by long-only **and** run uniformly on all six pairs — including AUDUSD (a
multi-year *downtrend*, no longer positive-carry) and range-bound EUR/USD, whose
losses drown any edge on the pairs where the strategy fits. And they used a
**fixed profit target that caps winners** — fatal for trend/carry, whose entire
edge is the fat right tail.

## Strategy → pair fit (the map we build to)

| Pair | Best-fit archetype | Session | Timeframe | Long-only 2019–2025 | Carry (long) today |
|---|---|---|---|---|---|
| **USD/JPY** | **Trend-following + carry** | Tokyo open & London–NY overlap | **Daily / H1** | **Excellent** (clean uptrend) | **Positive (largest)** |
| **EUR/JPY** | **Trend-following + carry** | London open / handover | **Daily / H1** | **Excellent** (strong uptrend) | **Positive** |
| **USD/CAD** | Mean-reversion / range (carry-positive) | New York + overlap | H1 / Daily | Poor for directional long | Positive (modest) |
| **GBP/USD** | London opening-range breakout | London + overlap | M15 / M5; H1 trend | Conditional (recovery phases) | ~Neutral |
| **EUR/USD** | Mean-reversion / range | London + overlap | H1 / M15 | Conditional (up-phases only) | Negative |
| **AUD/USD** | Trend by character, wrong way | Asian (Sydney–Tokyo) | Daily / H1 | **Worst** (downtrend 2021–24) | Slightly negative |

## Archetype evidence summary (confidence tags: HIGH / MED / LOW)

- **Carry (rate differential)** — **HIGH, and uniquely long-only-compatible.**
  Best-documented FX anomaly (Lustig-Roussanov-Verdelhan 2011; Menkhoff et al.
  2012; Koijen-Moskowitz-Pedersen-Vrugt 2018). Negatively skewed — crashes on
  funding-liquidity/risk-appetite drops (Brunnermeier-Nagel-Pedersen 2008; the
  Aug-2024 yen-carry unwind). Positive-carry longs today: USDJPY, EURJPY, USDCAD.
  **AUDUSD long is no longer positive-carry** (Fed ≈ RBA now; was true 2010–13) —
  carry sign is regime-dependent and must be re-derived from live rates, never
  hard-coded.
- **Time-series momentum / trend-following** — **HIGH** diversified (Moskowitz-
  Ooi-Pedersen 2012, Sharpe ~1.28; AQR *Century of Evidence*, positive every
  decade 1880–2016). On the actual majors a walk-forward found only **USDJPY
  (~0.78) and EURUSD (~0.54)** tradeable (single unrefereed study, numbers
  reproduced). Long-only forfeits the short-leg *crisis alpha* (~half the edge,
  FX-unverified) and excludes the EM cross-section where FX momentum is
  strongest. Daily/H1 only; needs a generous winner-run.
- **Donchian / dual-MA breakout** — trend family; **breakout specifically
  underperformed plain momentum in FX**, and fast/intraday trend has been weakest
  post-2008. Best used as the **mechanical trend trigger** (20/55 Donchian or
  20/50 EMA) for the carry+trend engine on daily bars. Rules are HIGH (primary
  Turtle source); majors-specific edge is MED/LOW.
- **Opening-range / session breakout** — structure is real (quiet Asia →
  London/NY vol expansion) and the pair/session map is HIGH-confidence (GBPUSD/
  EURUSD/EURJPY London; USDCAD/USDJPY NY; AUDUSD a poor London fit). But the
  strong ORB proof is **US equities, not FX**; naive FX "London breakout"
  backtests run **break-even-to-negative**, and independent work shows costs kill
  most intraday breakout edges. **Speculative — admit only if it clears an honest
  per-pair net-of-cost test.**
- **Mean-reversion / range (Bollinger/RSI fade)** — **most crippled by long-only.**
  FX mean-reverts at ~2–30 min and >2 years; the 1h–2yr band is trend-dominated
  (our daily/H1 is trend-zone, our 5m/15m is cost-zone). Negative expectancy
  pre-cost on these pairs/timeframes; fat left tail. **Avoid as a core**; at most
  a regime-gated dip-buy with mandatory stops. Do **not** import Connors' "stops
  hurt" finding into FX (no floor without drift).
- **Dead/weak:** day-of-week/seasonality (gone by the 1990s), cross-sectional
  momentum (real but in EM/illiquid — our six majors are the weak end),
  "momentum-of-momentum" (no rigorous FX evidence).

## Per-pair notes

- **USD/JPY** — multi-year uptrend (~102→150s), positive carry (long USD funded
  in JPY), prime carry funding pair; mean-reverts intraday between releases.
  Hazard: intervention zones >155–160. **Best long-only trend+carry pair.**
- **EUR/JPY** — strong staged uptrend (~114→170s), risk-on/off barometer + carry;
  violent reversals on carry unwinds. **Best long-only trend candidate.**
- **USD/CAD** — rangey (2nd-least trending of majors), lowest % daily vol; oil
  correlation has weakened since 2022. Positive carry long but poor directional
  trend — mean-reversion longs near band bottom, not trend.
- **GBP/USD** — "Cable" (**not** "the Dragon" — that's GBP/JPY); most volatile of
  the traditional USD majors; the flagship London-breakout pair; whippy/headline-
  driven. Long-only only in recovery phases.
- **EUR/USD** — most liquid/efficient, lowest USD-major vol, range-bound intraday;
  whipsaws trend-followers; the only pair with a positively-backtested time-of-day
  mean-reversion pattern. Negative carry long. Range/MR, not trend.
- **AUD/USD** — commodity/risk barometer, statistically trendy *by character* but
  its 2021–2024 direction was **down**, and it is no longer positive-carry long.
  **Worst fit for a long-only mandate** until a confirmed multi-year base.

## Implications for Milestone 12

1. **Pair selection is half the strategy.** Do not run one strategy uniformly on
   all six pairs. Match each strategy to the pairs it fits; for the first
   promotable long-only strategy that means **USDJPY + EURJPY (and USDCAD)**.
2. **Build carry-aware daily trend-following** with a Donchian/EMA trend trigger
   and a **let-winners-run exit** (the fixed-target cap is a prime suspect for the
   earlier losses). Re-derive carry sign from live rates; cap JPY concentration
   (both big longs short JPY).
3. **The higher-leverage structural fix is enabling short entries** (still
   DEMO-only). Long-only is a genuine handicap for every archetype *except* carry;
   with shorts, symmetric trend and mean-reversion and the crisis-alpha short leg
   all become available. Carry-trend on JPY pairs is the one path that does **not**
   require shorts — so it is the right first target — but a short-enabled backtest
   path is the biggest expected-value unlock for the strategy program overall.
4. **Validate honestly, per the M12 pipeline** — walk-forward, cost-stress,
   robustness — and promote only if the predetermined gates clear. Reputation is
   not evidence; the earlier "proven" strategies still lost net of costs here.

## Primary sources (selection)

Turtle rules: tradingwithrayner.com OriginalTurtleRules PDF; turtletrader.com/rules.
Trend/TSMOM: Moskowitz-Ooi-Pedersen (SSRN 2089463); AQR *Century of Evidence*.
Carry: NBER w14082, w19325, w14473; City Research (Menkhoff et al. 2012); BIS
Bulletin 90 (Aug-2024 unwind). FX momentum: BIS WP 366. Mean-reversion horizons:
qoppac.blogspot.com; Meese-Rogoff (ECB WP 88); PPP half-life (Papell). ORB
(equities): SSRN 4416622; cost falsification: arXiv 2605.04004. Pair behavior:
earnforex.com trend/hourly guides; offbeatforex ADR table; dailyforex range
article. Sessions: babypips, mataf volatility tool. Time-of-day MR: SSRN 2099321.

*Every non-obvious claim in the source research carried an inline URL and a
HIGH/MED/LOW confidence tag. The two most decision-relevant corrections to common
priors: (a) long-only is genuinely carry-compatible — the constraint aligns with
the premium's direction; and (b) AUDUSD is no longer a positive-carry long.*
