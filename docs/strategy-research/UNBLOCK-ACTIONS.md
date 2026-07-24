# The 8%/Month Plan — Exact Unblocking Actions (all free, minutes each)

State (2026-07-23): the challenge route is fully engineered and priced
(see PROP-CHALLENGE-DECISION.md). It is gated on validated Sharpe, and
every currently-validated edge has been measured against the viable
geometry and failed. The gates below are the ONLY things between the plan
and execution. None of them can be done by the agent — they need your
identity, your consent, or calendar time.

## Action 1 — FINRA API key (biggest Sharpe lever, ~10 minutes, free)

Unlocks: full bi-monthly short-interest history → the STRONG variant of
the short signal (the free daily proxy already survived costs at 0.76 on
the full universe) → re-run its gauntlet with years of real history.

1. Go to https://developer.finra.org → "Create account" (free tier).
2. Register with your email; company can be "individual".
3. In the API console, create an **API credential** — this gives you a
   CLIENT ID and a SECRET (it's a pair, not a single key).
4. Set both env vars (laptop shell, or mini PC `~/.trading_desk_env`):
   `FINRA_API_CLIENT_ID=<id>` and `FINRA_API_CLIENT_SECRET=<secret>`
   (never commit them).
5. Run `python scripts/fetch_short_interest.py` then
   `python scripts/validate_short_interest_signal.py` — the fetch AND the
   pre-registered gauntlet are already built and waiting (the trial plan
   was frozen in git BEFORE the data, so the result is untainted).

## Action 2 — Alpaca account (news wire, ~10 minutes, free)

Unlocks: Benzinga headline wire becomes the primary live news source for
the pre-trade gate (currently halt feed + EDGAR + Yahoo fallback).

1. https://alpaca.markets → sign up (paper account is enough; no funding).
2. Dashboard → "API Keys" → generate.
3. Mini PC `~/.trading_desk_env`: `APCA_API_KEY_ID=...` and
   `APCA_API_SECRET_KEY=...`
4. The dormant adapter activates on next nightly run automatically.

## Action 3 — LLM API key (advisory agents, ~5 minutes, pay-as-you-go)

Unlocks: A1 news classifier + A4 synthesizer start producing shadow
artifacts (attenuation-only; cannot increase risk by construction).
Note: ChatGPT Pro / Claude Pro subscriptions do NOT include API access —
this needs a platform key with a few dollars of credit.

- Either https://platform.openai.com → API key → `OPENAI_API_KEY=...`
- Or https://console.anthropic.com → API key → `ANTHROPIC_API_KEY=...`
- Expected cost at shadow volume: cents per day.

## Action 4 — IG demo credentials (broker-realistic stage)

Unlocks: IGDemoBroker running in parallel with paper — the stage you said
comes before any live account.

1. IG dashboard → My IG → Settings → API keys → create a DEMO key.
2. Mini PC env: `IG_API_KEY`, `IG_IDENTIFIER`, `IG_PASSWORD` (demo).
   Never committed, never on the laptop.

## Action 5 — the fee decision (ONLY when a config passes the gauntlet)

Nothing to do today. When forward evidence or new data produces a config
that passes DSR/SPA/CPCV, the agent brings you a one-page sheet:
measured Sharpe, P(fund), expected fees, and this pre-commitment to sign:

> Challenge budget: $____ total (suggested $1,100–1,650 ≈ 2-3 attempts).
> This is burnable money, separate from all trading capital. No re-ups
> beyond it within 6 months regardless of near-misses. The personal
> $1,000 track's risk settings are untouched. Fee is paid only at:
> FTMO 2-Step Swing (or a verified-equal geometry at time of purchase).

## What runs on its own meanwhile (no action needed)

- Nightly paper session (mini PC, 18:30 AST) — live gate evidence.
- Short-vol composite shadow log — the forward out-of-sample record that
  can honestly promote it (backtests cannot).
- Re-pricing the whole challenge decision after any input above:
  `PYTHONPATH="src;scripts" python scripts/prop_challenge_math.py` plus
  the two variant scripts — one command each, results feed the doc.
