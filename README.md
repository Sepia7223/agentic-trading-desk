# Agentic Trading Desk

Safety-first automated trading application foundation, adapted from the original
MIT-licensed Claude + Robinhood MCP Agentic Trading Desk.

This milestone does not connect to IG, does not call the OpenAI API, and does
not implement order execution. It establishes the Python package structure,
deterministic strategy layer, safety configuration, and abstract integration
boundaries for later work.

## Roles

- **Codex** is the software development tool used to modify and maintain this
  repository.
- **OpenAI API** is the eventual runtime AI analysis provider. It will receive
  sanitized strategy outputs and context, not broker credentials.
- **IG demo** is the eventual broker environment. The default environment is
  always demo, and configuration accepts only the exact IG demo REST base URL.
- **Deterministic strategy calculations** remain local Python code. Indicators,
  score pillars, macro scoring, and decision flags are calculated by code, not
  by a language model.
- **Hard-coded risk controls** remain outside model control. The model must not
  choose position size or bypass risk limits.

## Current Safety Posture

- `broker_environment`: `DEMO`
- `operating_mode`: `READ_ONLY`
- `live_trading_allowed`: `false`
- `automatic_execution_enabled`: `false`

Unknown broker, position, market, or risk state must result in no trade. Order
execution is intentionally absent in this milestone.

The broker protocol is read-only and contains no order preview, validation, or
execution methods. Those concerns will use separate interfaces in later work.

## Project Layout

```text
src/trading_desk/
  config.py                 immutable safety-first configuration models
  ports/                    abstract protocols for future integrations
  strategy/
    indicators.py           EMA, RSI, MACD, TRIX, Bollinger calculations
    macro_pillar.py         cross-asset macro-sentiment pillar
    score.py                three-pillar scoring and decision flags
scripts/                    backwards-compatible CLI wrappers
tests/                      unit and regression tests
docs/original-claude-skill.md
```

## Strategy Framework

The deterministic strategy layer preserves the original three-pillar framework:

- **Trend**: price versus EMA20, EMA20/EMA50/EMA200 structure, and EMA200 slope.
- **Momentum**: RSI-14 using Wilder smoothing, MACD histogram, and TRIX versus
  signal.
- **Macro-Sentiment**: cross-asset regime score using RSP/SPY, 10Y-2Y,
  HYG/LQD, IWM/SPY, SPY/TLT, XLY/XLP, and SPY-TLT correlation.

Bollinger Bands are computed as a supporting exhaustion signal and do not feed
directly into the numeric momentum score.

## CLI Usage

The legacy script paths still work as wrappers:

```bash
python scripts/indicators.py input_ticker.json
python scripts/macro_pillar.py macro_input.json --json
python scripts/score.py ticker_input.json --json
```

Installed console scripts are also defined:

```bash
trading-desk-indicators input_ticker.json
trading-desk-macro-pillar macro_input.json --json
trading-desk-score ticker_input.json --json
```

## Development

```bash
python -m pip install -e ".[dev]"
python -m ruff format .
python -m ruff check .
python -m mypy
python -m pytest
```

Python 3.12+ is required.

## Attribution

The original Claude-specific skill has been preserved at
`docs/original-claude-skill.md` for attribution and reference. The MIT license
and original attribution remain in `LICENSE`.
