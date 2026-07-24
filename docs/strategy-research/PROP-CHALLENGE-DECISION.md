# Prop-Firm Challenge — Decision Document (research + math, honest)

Goal as stated by the user: **"8% profit every month."** This document is the
honest engineering of that goal. Sustained 8%/month on one's own account
(~152%/year compounded) has no evidential basis at any capital scale — we do
not build toward it. The goal IS reachable in a different, mathematically
defensible frame:

1. **The challenge sprint**: hit +8-10% ONCE, inside an evaluation's rule
   geometry, with the fee as the entire, pre-decided maximum loss.
2. **Capital leverage**: 8%/month of the user's own $1,000 is $80/month. A
   $100k funded account at an 80% split needs only **~0.1%/month** to match
   that. Modest, consistent returns on funded capital beat aggressive returns
   on small personal capital — with bounded downside.

The personal $1,000 paper/IG track stays untouched at validated risk levels.
Challenge fees are burnable money only, pre-committed, never re-upped on tilt.

---

## 1. The math (built and validated in-repo)

`src/trading_desk/research/challenge.py` — Monte Carlo first-passage
simulator (EOD-evaluated, pessimistic on ties), cross-validated against the
closed forms (gambler's ruin for static drawdown; Taylor 1975/Lehoczky 1977
for trailing). 14 tests green. Reproduce with
`PYTHONPATH=src python scripts/prop_challenge_math.py`.

Structural facts (all verified analytically AND by simulation):

- **Zero edge passes a static 8/10 challenge 55.6% of the time**
  (P = D/(T+D), volatility-independent). The fee is priced against this.
  Firms' observed ~10% pass rates mean the median buyer trades with
  negative drift — the product exists because of them, not us.
- **P(pass) depends on skill only through θ = 2·Sharpe/σ.** With positive
  edge and no deadline, lower vol always raises P(pass) — but time to
  finish scales like T·D/σ², so vol buys speed at the price of probability.
- **Trailing drawdown costs 10-15pp vs static at identical skill.**
  Zero-edge trailing 8/10: e^(−T/D) = 44.9% vs 55.6% static. Intraday
  trailing (Apex-style) is stricter than everything we simulate.
- **Time limits convert moderate edge to noise.** At a 30-day deadline, a
  20%/yr-drift trader passes barely more often than a coin-flipper.
  Geometry to buy: **static drawdown, no time limit, EOD evaluation.**

### Our numbers (Monte Carlo, 20k paths/config, EOD, ties→bust)

Generic 2-step (8%→5% targets, 10% static, 5% daily cap, no time limit —
this is FundedNext Stellar 2-Step's exact geometry, fee $550):

| ann. vol | S=0.00 | S=0.12 (our momentum, net) | S=0.33 (composite, unproven) | S=0.80 |
|---|---|---|---|---|
| 4% (paper config) | 5.3% | 7.7% | 14.0% | 37.6% |
| 8% | 27.6% | 33.5% | 45.2% | 70.7% |
| **12%** | 35.2% | **40.1%** | **49.2%** | 68.8% |
| **16%** | 36.1% | **40.0%** | 47.0% | 62.3% |
| 24% | 35.3% | 37.9% | 42.6% | 53.3% |
| 48% | 23.6% | 24.6% | 26.5% | 30.5% |

Expected total fees per funded account at S=0.12, vol 12-16%: **~$1,370**
(geometric retries at $550/attempt; FundedNext refunds the fee at first
reward, improving this). FTMO's 10%→5% geometry at the same point: ~37%
pass, ~$1,640 expected fees. Futures-style trailing (6% target, 3%
trailing): ~20% roughly regardless of skill — **rejected on geometry**.

Three consequences:

- **The current paper configuration (≈4% vol) is the worst possible
  challenge vehicle** — 5-14% pass, $4k-10k expected fees. Challenge-mode
  must run ~3-4× the paper vol (12-16% annualized ≈ 0.76-1.0% daily σ,
  safely ≤ ¼ of a 5% daily cap).
- **Our honest edge adds only ~5pp over a coin-flip** (40% vs 35%). The
  challenge route *multiplies* whatever edge exists; it cannot create one.
  Raising validated Sharpe (short-vol composite forward evidence, FINRA
  short-interest history) remains the highest-value work.
- **Timeline honesty**: at 12-16% vol, expected time-to-resolution is
  ~2-6 months for phase 1 plus ~1-3 months for phase 2. This is a
  months-long project per attempt, not a weekend.

### The funded-phase chain (the part most buyers ignore)

EV = −fee·E[attempts] + P(fund)·[refund + P(payout)·E[Σ payouts]].

Independent base rates (FPFX Tech dataset, 300k accounts / 100k traders /
10 firms, 2024): **14% of traders ever got funded; 45% of funded got ≥1
payout; 7% of all traders were ever paid anything; average lifetime spend
~$800 (~3 attempts); average payout ≈ 4% of account size ($4k on $100k).
The 7% who win average ~4× their fees back.** Topstep discloses 33.3% of
funded participants ever received a payout; 40-50% of funded accounts
breach within ~3 months. An independent quant analysis (Delphic Alpha,
2026) puts the break-even Sharpe at **~1.1-1.5** under discretionary-trader
survival assumptions — our disciplined step-down plan improves on those
assumptions, but the direction of the message stands.

Our honest EV at S=0.12 (P(fund)≈0.40, expected fees ≈$1,370, funded phase
stepped down to 6-10% vol, FundedNext-style 2% on-demand payout cycles,
10-20% haircut for rule-denial and firm-failure risk): **approximately
breakeven — roughly $0 ± a few hundred dollars — with the error bars
spanning zero.** The route's real value today is (a) bounded-loss
optionality on a large capital base and (b) the payout stream becoming
strongly positive as validated Sharpe rises: at S≈0.33 the same chain is
clearly +EV, and every +0.1 of Sharpe adds ~3-5pp of pass probability and
~50% more funded-phase income. **The challenge multiplies edge; it cannot
create it. The Sharpe pipeline (short-vol forward evidence, FINRA key)
remains the binding constraint — same conclusion as every prior arc.**

## 2. Instrument fit — the real constraint

Our validated edge is **US equity long-short momentum (~60 names)**. The
2026 funded-account market cannot host that book as-is:

| Route | Universe fit | Automation | Verdict |
|---|---|---|---|
| Trade The Pool (real US equities, 12k symbols) | ✅ full | ❌ webhook-only beta, ~2 req/min, 60s min holds, 10¢ min profit, consistency rules, revocable | Structurally hostile to systematic baskets |
| FundedNext (best challenge economics, EAs allowed on MT4/5, fee refunded) | ❌ **zero single-stock CFDs** (FX/indices/commodities/crypto only) | ✅ | Needs a NEW validated FX/index strategy — we don't have one (M12 FX evidence was negative) |
| FTMO (most credible payer: $450-500M cumulative, 10-yr record; EAs explicitly allowed all phases; VPS allowed; MT5/cTrader Python paths) | ⚠️ ~50 stock CFDs → book must concentrate to ~20 names; overnight/weekend holds require the **Swing** account type (Standard funded accounts must flatten before weekends and observe ±2min news windows) | ✅ | Viable IF the concentrated variant re-passes the gauntlet |
| Blueberry Funded (ASIC-regulated parent; 1,000+ stock CFDs on MT5 — largest universe among CFD firms) | ✅ near-full | ❓ EA policy unverified | **Top candidate to verify** — could run our strategy nearly as-is |
| Futures firms (Topstep API is excellent) | ❌ no single-stock futures exist; book collapses to index spreads, losing all cross-sectional alpha | ✅ | Rejected (geometry also worst-in-class) |

**Alpha Capital**: bans autonomous EAs outright — excluded.
**Apex**: documented mass discretionary payout denials 2024-25 — excluded.

## 3. Credibility (who actually pays)

- **Tier A**: FTMO — $450-500M cumulative payouts across verified
  milestones, $62M net profit on $329M revenue (2024), acquired OANDA
  (Dec 2025), no payout-scandal history. Openly demo-based.
- **Tier B**: FundedNext ($107.8M tracked 2025 payouts, top of
  PropFirmMatch's tracker), FundingPips ($97.1M), Topstep (cleanest
  disclosure in the industry but Apr 2026 payout-cap cuts + 2025 platform
  outages). Trade The Pool ~4.3★ with payout-delay complaints.
- **Avoid**: Apex (denial patterns), anything young without a payout track
  record. Base rate: **~80-100 firms (13-14% of the industry) died
  2024-2025**; MyForexFunds vanished overnight with $310M of fees taken
  (CFTC case later dismissed for prosecutorial misconduct — never tried on
  the merits; the firm still disappeared for 2 years). Trustpilot
  trajectory (4+→3.2) is a leading indicator of collapse.
- Regulatory reality: funded accounts are **simulated** at nearly every
  firm including "funded" phases (FTMO/FundedNext/Alpha say so in their own
  terms); no FCA/FSCS protection; EU regulators circling but no binding
  rules yet. The fee buys a bet against a counterparty, not a brokerage
  relationship.

## 4. Recommended path (no fee is paid before all gates)

1. **Verify Blueberry Funded**: EA/automation policy in writing, stock-CFD
   symbol list vs our momentum universe, challenge geometry, payout
   evidence. If EAs are permitted and ≥~200 of our names exist → primary.
2. **In parallel, backtest the FTMO-shaped fallback**: our momentum
   gauntlet re-run on a ~20-name mega-cap universe (their symbol list),
   with CFD costs (overnight financing both legs, ~$15/side minimums).
   Verdict decides whether the concentrated variant retains enough edge.
3. **Design challenge-mode config** (same signals, one vol dial):
   12-16% annualized vol; daily σ ≤ ¼ of daily cap; static-DD/no-deadline
   geometry only; funded-mode step-down plan to 6-10% vol pre-written.
   Pre-register in the trial registry; validate through DSR/SPA/CPCV like
   everything else. **No fee before the config passes.**
4. **Fee budget decision (user)**: expected fees per funded account are
   ~$1,100-1,600 at today's honest Sharpe. The user pre-commits a total
   burnable budget (e.g. 2-3 attempts ≈ $1,100-1,650) — written down
   before attempt #1; no re-ups beyond it inside 6 months.
5. **Keep raising the real edge** — every +0.1 Sharpe adds ~3-5pp pass
   probability and ~50% more funded-phase income. The FINRA key +
   short-vol forward evidence remain the cheapest Sharpe available.

## 5. What we will NOT do

- No fee before the challenge-mode config passes the pre-registered gauntlet.
- No trailing-drawdown or time-limited geometries.
- No martingale re-ups after failed attempts; the budget is written first.
- No touching the personal $1k track's risk settings, ever.
- No opposite-hedging across accounts or any banned-practice "guarantees" —
  detection is real, confiscation is the penalty, and it's dishonest anyway.

*Generated 2026-07-23 from a 10-agent research fan-out (firm terms verified
on primary sources; probabilities computed by our own validated simulator).
Approximate rule sets in scripts/prop_challenge_math.py must be re-verified
against firm terms on purchase day — firms change rules retroactively
(FundingTicks precedent).*
