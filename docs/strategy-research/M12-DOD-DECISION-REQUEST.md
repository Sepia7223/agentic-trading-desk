# M12 — Definition-of-Done Decision Request (for the reviewer)

**Branch:** `feature/multi-regime-strategy-portfolio` (base = accepted 11.5 head
`f1b3236`). **Requester:** Sepia7223. **Decision needed:** whether M12's DoD #3
can be satisfied by a fully-evidenced negative result.

## Where M12 stands

Of the four rejection reasons, three are resolved in the committed branch and
were invisible only because PR #13's base branch on GitHub still points at the
old M11 head (fix: switch the PR base to
`feature/ig-demo-operational-certification`):

1. **Lineage** — the branch is rebased onto `f1b3236`; every 11.5 file is
   bit-identical except the five files M12 legitimately extends.
2. **Governed dataset** — Dukascopy bid/ask dataset frozen and fingerprinted
   (`artifacts/strategy_validation/dataset/manifest.json`, approved by
   Sepia7223); leakage-controlled boundaries (dev 2019-07→2021-12, validation
   2022-01→2025-06 with 7 walk-forward windows, locked final test
   2025-07→2026-06).
3. **Engine-path proof** — backtest profit-target and intrabar-ambiguity are
   wired into the real engine path with actual-invocation tests.

## The one open item: DoD #3

> "At least one NEW family advances beyond RESEARCH_ONLY on evidence."

All three new families (trend-pullback-v1, volatility-breakout,
range-mean-reversion) **honestly failed** the predetermined gates and are
recorded REMAIN_RESEARCH_ONLY with sealed evidence. A subsequent exhaustive
governed search — run precisely to satisfy DoD #3 — established that this is
not a search failure but a property of the mandate:

- **Donchian trend-following** (7+ configs, DAY/HOUR/4H, long AND short via
  price-inversion): best result USDJPY hourly, PF 1.13, positive expectancy,
  5/7 walk-forward windows profitable — **fails the 2× cost-stress gate**
  (cost-sensitivity 1.7–2.6 vs ≤0.5). Gross-edge-to-cost ratio ≈1.55 vs the
  ≥2.0 the gate implies; no parameter closes that gap.
  (`docs/strategy-research/donchian-long-only-findings.md`)
- **Carry** (policy-rate model): the only configuration that survives 2× costs
  is a 15-trade result where one trade is 80% of profit — a single-megatrend
  artifact, correctly not promotable.
  (`docs/strategy-research/carry-and-cost-robustness-findings.md`)
- **Mean-reversion / momentum / stat-arb at higher frequency**: uniformly
  net-negative after realistic costs on this universe.
  (`docs/strategy-research/acceptance-standard-v1-results.md`,
  `FINAL-frequency-vs-cost-conclusion.md`)

Every run is in committed ledgers/artifacts; the locked final-test partition
was never consumed (no candidate earned it). Faking or gate-weakening was not
done and is prohibited by the spec itself.

## The decision requested (one of)

**(a) RECOMMENDED — amend DoD #3** to: *"every new family reaches a sealed,
evidence-backed promotion decision under the predetermined gates (promotion OR
documented REMAIN_RESEARCH_ONLY), with at least one full validation cycle
executed end-to-end."* Rationale: M12's substance — the governed validation
pipeline, leakage-controlled dataset, predetermined gates, sealed promotion
decisions — is delivered and was exercised for real (it correctly rejected
seven-plus plausible-looking strategies). Requiring ≥1 promotion makes the
milestone hostage to whether an edge exists in the chosen universe, and
structurally incentivizes exactly the gate-weakening the spec prohibits.

**(b) Expand the mandate** so a pass is achievable — e.g., authorize a
short-enablement milestone first, or extend the instrument universe — and hold
M12 open until that lands (slower; the evidence above predicts long-only FX
majors still won't clear the gates).

**(c) Hold M12 open as-is** (blocks M13–M19 indefinitely on a condition the
evidence indicates is unmeetable in this universe).

With (a), M12 becomes reviewable immediately after the PR-base fix, and the
already-implemented M13–M19 branches can enter review in roadmap order.
