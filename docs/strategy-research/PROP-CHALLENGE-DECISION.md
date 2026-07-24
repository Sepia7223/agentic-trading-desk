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
| Blueberry Funded (SVG-registered operator; the ASIC license belongs to a separate AU broker entity) | ❌ stock-CFD program **discontinued** Oct 2025; historical stock accounts banned EAs + overnight holds anyway | ❌ | **Excluded** — verified 2026-07-23; see §5 |
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

## 4. The concentrated-CFD backtest — MEASURED (2026-07-23)

`scripts/validate_challenge_cfd_variant.py` ran the momentum engine on the
FTMO-shaped universe with the CFD financing model (net drag = gross ×
2.5%/yr; benchmark cancels in a symmetric L/S book; Sharpe is
leverage-invariant). Registered in the trial registry like every variant.

| Run | Sharpe (equity costs) | Sharpe after CFD financing |
|---|---|---|
| **Legacy pre-2026 list (30 names, honest)** | 0.305 | **0.130** |
| +2026 additions (PLTR/SNOW/GME/MSTR — LOOK-AHEAD, sensitivity only) | 0.644 | 0.483 |

**The +0.35 Sharpe gap is listing look-ahead**: the firm added those names
AFTER they ran. A naive backtest on the current symbol list would have
"found" a tripled edge that never existed ex ante. Honest gates on the
legacy run: **DSR 0.51 — FAIL** (bar: 0.95), **CPCV 9/15 positive folds —
FAIL** (standard: 15/15). Verdict: **the concentrated CFD variant is NOT
promotable.** It carries the same ~0.12-0.13 net edge as the full-universe
strategy; concentration adds nothing provable and financing eats a third
of it. P(fund) at the measured Sharpe: **40.6%** (12% vol) — i.e. mostly
barrier geometry, as §1 predicted.

**Candidate #2 also measured (`validate_challenge_shortvol_variant.py`)**:
the short-volume signal — our strongest fully-validated edge on the full
universe (net Sharpe 0.76, DSR 0.9993, CPCV 15/15) — restricted to the
same legacy CFD universe: **Sharpe −0.41 before financing, −0.66 after;
DSR 0.08; CPCV 1/15. Hard FAIL.** The signal's alpha lives outside the
mega-caps (consistent with the literature); it cannot be ported to a CFD
symbol list. With momentum marginal and short-vol negative on this venue,
**every validated edge has now been tested against the only viable
geometry — none passes today.**

## 5. Recommended path (no fee is paid before all gates)

1. **Verdict from §4 stands**: no challenge-mode config currently passes
   the gauntlet. **Therefore no fee is paid today.** This is the same
   honest "no" the gauntlet gave the insider signal and the composite.
2. **The Sharpe pipeline is the binding constraint** — every +0.1 Sharpe
   adds ~3-5pp pass probability and ~50% more funded-phase income, and the
   whole chain flips clearly +EV around S≈0.3-0.5. Cheapest available
   Sharpe: FINRA key (short-interest history → re-gauntlet), Alpaca key
   (news wire), short-vol composite forward evidence accumulating nightly
   in shadow. When the composite's forward record justifies adoption, the
   challenge math is re-run in one command.
3. **Firm shortlist frozen while we wait** (verified terms, July 2026):
   - **FTMO 2-Step Swing** ($100k = €540 list/€439 promo, fee refunded
     with first reward, 80→90% split, static 10%, no time limit, EAs +
     VPS explicitly allowed, MT5/cTrader Python paths, weekend holds OK
     on Swing) — Tier-A payout record. The realistic host.
   - **FundedNext Stellar 2-Step** ($549.99 refundable, same geometry,
     EAs on MT4/5) — best economics, but ZERO stock CFDs: only relevant
     if we ever validate an FX/index strategy.
   - **Excluded on verified rules**: FundingPips (weekend-hold ban on
     funded accounts, Jan 2026 — fatal to a multi-day book), Alpha
     Capital (autonomous EAs banned), all futures firms (daily
     force-flatten + trailing DD + no single-stock futures), Apex
     (denial history), ThinkCapital (no MT5/EA-capable platform),
     Trade The Pool (2 req/min webhook beta, 60s holds), The5ers CFD
     (no stock CFDs; MT5-only).
   - **Blueberry Funded: excluded (verified 2026-07-23).** The 1,000+
     stock-CFD program was DISCONTINUED (new purchases stopped Oct 2025,
     product pages removed) — and even historically its stock accounts
     banned EAs, banned overnight holds, and mandated stop-losses, so it
     never could have hosted this book. Trustpilot rating suppressed for
     fake-review guideline breach (36% 1-star; payout-denial-at-review
     patterns); SVG-registered operator, not the ASIC entity; fees
     non-refundable; funded accounts capped at 1.5% loss per trade idea.
4. **When a config passes**: user pre-commits a burnable fee budget
   (2-3 attempts ≈ $1,100-1,650) in writing before attempt #1; no re-ups
   beyond it inside 6 months; challenge runs at 12-16% vol with daily σ ≤
   ¼ of the daily cap; funded phase steps down to 6-10% vol (same
   signals, one dial); the personal $1k track is never touched.

## 6. What we will NOT do

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
