# Information-Edge System — Research Synthesis & Build Blueprint

Synthesis of five parallel research reports (news APIs · whale/institutional
data · event-strategy evidence · signal combination · multi-agent AI
architectures), ~150 sources, July 2026. This is the design document for the
next build phase: news reaction, whale tracking, and an AI agent team, layered
onto the existing momentum system, pre-trade pipeline, and paper broker.

## 0. The corrected premise (read first)

The research is unanimous on three points that reshape the original goal:

1. **Nobody knows direction ahead of time.** Renaissance's Medallion ran a ~51%
   win rate; Buffett ~52%. The "93% accurate" LLM headlines results describe the
   price move that completes in **milliseconds-to-minutes — before anyone at
   retail latency can trade it**. Every *tradable* edge in the literature runs
   51–56% and pays through breadth, sizing, and loss asymmetry.
2. **The reaction race is unwinnable and not worth entering; the disclosure
   game is winnable and mostly free.** Unscheduled headlines are priced in 5–10
   minutes (HFT territory). But *slow, scheduled, filing-based* information —
   insider clusters, analyst revisions, short interest — carries documented
   months-horizon edges that have survived decades of publication, and the data
   comes free from EDGAR/FINRA.
3. **News's proven role at our cadence is the veto, not the trigger** — exactly
   the news gate we already run: block/delay trades that fight fresh (especially
   negative) news, pull M&A targets from the momentum book, treat earnings dates
   and halts as risk events. Zero added turnover, so it cannot be killed by
   costs.

Expectation set honestly: this program targets **incremental basis points of
expectancy and better risk avoidance** on top of the momentum book — not a
transformation of the win rate.

## 1. Data sources (ranked; almost everything we need is free)

### Adopt
| Source | What | Latency | Cost |
|---|---|---|---|
| **Alpaca News API** (Benzinga wire) | Primary live headlines: websocket push + REST archive to 2015 (point-in-time `created_at` → backtestable news gate) | seconds | **$0** (beta; adapter-wrapped in case pricing changes; fallback = Massive Benzinga add-on $99/mo) |
| **SEC EDGAR direct** (`data.sec.gov` + Atom) | 8-K + Form 4 live polling (acceptance timestamps = same key as our backtest ledger) | poll + ~1s | **$0** (10 req/s limit) |
| **Nasdaq Trader halt RSS** | Regulatory-halt "news pending" = cleanest hard-BLOCK input in existence | trivial | **$0** |
| **FINRA short interest + daily short volume** | Short-side tilt + aggregate exposure governor | bi-weekly/daily | **$0** |
| **Cboe/OCC EOD options volume** | Option-to-stock (O/S) ratio factor | EOD | **$0** |
| **EDGAR 13F** (+13f.info) | Quarterly conviction-consensus overlay | 45-day lag | **$0** |
| sec-api.io Stream (optional) | Managed ~300ms filing websocket if we don't want to run the poller | ~300ms | $49/mo |
| Alpha Vantage news-sentiment (optional) | Batch enrichment/labeling only (archive starts 2022 — too shallow to validate on) | minutes | $0–50/mo |

**Demote:** Yahoo Finance RSS (current gate source) → fallback checksum only
(unofficial, minutes-latency, no SLA).

### Rejected (with reasons)
NewsAPI.org (24h delayed free tier, $449 cliff, no tickers) · EODHD news
(15–60 min delay per own docs) · aggregator-crawlers as trigger sources
(non-point-in-time timestamps) · X/Twitter API (streaming now ~$42k/mo
enterprise) · StockTwits (dev program closed) · Discord self-bots (prohibited) ·
SEC PDS at $1,500/mo (its speed edge was eliminated in 2015) · paid "whale
sweep alert" products ($149/mo, zero peer-reviewed validation) · dark-pool
"prints" (2–4 wk lag, unknown direction) · CFTC COT for FX (research shows
positioning follows price).

## 2. The signals (evidence-graded)

### BUILD — documented, alive, capturable at daily cadence
1. **Insider cluster buys (Form 4)** — 82 bps/mo value-weighted alpha for
   *opportunistic* trades (Cohen-Malloy-Pomorski); clusters ≈ 2× singles;
   months horizon; free; weakest in large caps and most alpha bleeds before
   the filing → treat as a months-tilt/filter, sized modestly.
2. **Analyst estimate-revision momentum** — the strongest survivor: ~7.6%/yr
   decile spread through 2023, monthly IC ~0.2, *still working after 40 years
   of publication*. Complementary "fundamental momentum" to our price momentum.
   Only signal needing paid data (point-in-time estimates: Zacks/FMP tiers).
3. **O/S options-volume ratio** — 1.47%/mo decile spread (Johnson & So, JFE),
   computable from free EOD volume; must survive our own S&P 500 replication
   before trust.
4. **Short interest** — strong slow-moving evidence; short-leg tilt + aggregate
   net-exposure governor.
5. **News/event veto layer (upgraded)** — Alpaca wire + EDGAR live + halts
   feeding the existing BLOCK/CAUTION gate; backtestable via the Benzinga
   archive + our EDGAR ledger.

### SKIP — decayed, dead, or unreachable
PEAD in large caps (dead since ~2006; residue = don't fade fresh surprises) ·
index add/delete (cleanest documented anomaly death) · buyback drift
(post-2001 ~0) · FDA drift in liquid names · guidance-withdrawal trading ·
headline-reaction trading at retail latency · investor-persona AI ensembles ·
LLM traders/position-sizers (uniform failure in honest evaluations).

Apply the **McLean-Pontiff haircut** to every number above: published anomaly
returns fall 26% out-of-sample and 58% post-publication.

## 3. Architecture: how the data correlates (combination layer)

Core finding: **the combiner should be the simplest component; the validator
the most sophisticated.** Equal weights beat fitted weights out-of-sample (the
50-year "forecast combination puzzle"); edges come from breadth of independent
signals, not clever blending.

```
signals/    one SignalModel per source → cross-sectional score per (date,ticker)
features/   PIT feature store: append-only parquet, event_time + knowledge_time,
            merge_asof(direction=backward) — the single choke point that makes
            look-ahead structurally impossible (extends our PIT universe work)
combine/    rank → Gaussian-z normalize → EQUAL-WEIGHT mean (v1);
            residualize new signals vs momentum first (only orthogonal residue
            counts as new information — Paleologo)
portfolio/  rank buckets + portfolio-level VOLATILITY TARGETING (the one sizing
            overlay with solid evidence; specifically helps momentum)
validation/ trial registry (append-only, every backtest logged) → CPCV/PBO
            triage → Deflated Sharpe w/ honest trial count → SPA test where any
            composite must beat OUR LIVE MOMENTUM STRATEGY, not zero →
            locked final test, spent once
```

Later (only after ≥2 orthogonal sources are live and the linear composite has
cleared SPA): **meta-labeling** — momentum stays primary (direction); a small
secondary classifier fed by the *orthogonal* news/insider/options information
predicts *when the primary is right*, filtering and sizing. It can only veto or
shrink — structurally the same attenuation-only safety as the advisory layer.

## 4. The AI agent team (advisory-only; LLM proposes, rules dispose)

Five agents, each ONE task, each emitting a typed pydantic artifact into an
append-only store. **No agent touches orders, sizing, or pipeline config.**
Headline literature results (TradingAgents Sharpe 5–8) are contaminated by LLM
training-data look-ahead (Profit Mirage, FINSABER show collapse past training
cutoff) — so all agent evaluation is **forward-only** on the paper broker.

| Agent | Model | Task | Coupling |
|---|---|---|---|
| A1 News/Event Classifier | Haiku, Batch | headline/filing → typed event (type/direction/horizon/evidence-quotes) | feeds gate + calibration log |
| A2 Regime Commentator | Sonnet, 1×/day | narrate OUR computed vol/trend/breadth stats | human-facing |
| A3 Anomaly Explainer | Sonnet, on-event | explain fired rejection codes / distribution shifts | ops only |
| A4 Advisory Synthesizer + one bear-critique pass | Sonnet | per-name stance from A1+A2+quant features | **attenuation-only**: `size_scalar ∈ [0.25,1.0]` + veto (REJ_ADVISORY_VETO); absent ⇒ no effect; shadow mode until ≥8 wks positive forward calibration |
| A5 Strategy Researcher | Opus, weekly | strategy hypotheses + code → must pass walk-forward + human accept gate | human-gated |

Guardrails: closed vocabularies, mandatory verbatim evidence quotes
(string-checked), abstention legal, confidences display-only until calibrated
(Brier-scored per agent), every call archived for exact replay, agent layer
monitored like a data feed (staleness/cost breach ⇒ treated as absent, never a
halt). **Cost: ≈ $30–90/month** with batching + caching.

Do NOT build: persona zoos, multi-round debates, LLM traders/PMs/sizers,
memory-"compounding" modules (documented value destruction), open web browsing
inside decision-path agents (prompt-injection surface).

## 5. Build order

- **Phase 0 — foundations (build the lie detector first):** PIT feature store
  with `knowledge_time`; trial registry + DSR/SPA/CPCV gates; live-news
  upgrade (Alpaca websocket adapter + EDGAR live poller + halt RSS → existing
  gate; Yahoo demoted to fallback). *Cost $0.*
- **Phase 1 — signals, one at a time, each through the full gauntlet
  (residualize → CPCV → DSR → SPA vs momentum):** insider clusters → O/S
  ratio → short interest → analyst revisions (decide on paid estimates data
  only after the free signals prove the pipeline).
- **Phase 2 — composite:** rank-normalized equal-weight combine; SPA vs
  momentum alone; paper-trade the composite alongside the current book.
- **Phase 3 — agents:** A1 shadow → A2/A3 ops wins → A4 shadow →
  calibration-gated enforcement → A5 with human gates.
- **Phase 4 — meta-labeling** once ≥2 orthogonal sources are live.

Everything reuses what exists: the EDGAR ledger discipline, the news gate, the
pre-trade pipeline (A4 plugs in as one more check with its own rejection code),
the PIT universe, the paper broker as the forward-only proving ground, and the
locked-final-test governance.

## 6. Total cost

Mandatory: **$0/month** in data (Alpaca free beta + EDGAR + FINRA + Cboe EOD +
halt RSS). Optional: sec-api.io $49/mo (managed filing stream) · LLM agent team
$30–90/mo · point-in-time analyst-estimates feed (only if Phase 1 reaches the
revisions signal; price on request, evaluate then). Contrast: the professional
stack this approximates (Bloomberg $32k/yr + RavenPack enterprise) — whose
remaining advantages (sub-second latency, archive breadth) the evidence says do
not matter at our cadence.

## 7. Success criteria (pre-registered, honest)

- News-gate upgrade: measured reduction in adverse-event participation at zero
  turnover cost (compare gated vs ungated paper books).
- Each new signal: positive orthogonal contribution after costs, surviving
  DSR + SPA against the live momentum benchmark — expect single-digit bps/day
  at best; win rate stays ~50%.
- Agent layer: calibration (Brier) improving over time; A4 veto shows positive
  expected value over ≥8 weeks forward before enforcement.
- Any claim of a step-change in win rate is treated as a bug (leakage) until
  proven otherwise.
