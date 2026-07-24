"""Prop-challenge barrier-race math: P(hit +target before bust), honestly.

Monte Carlo first-passage simulation of a funded-account evaluation ("reach
+T% before a -D% drawdown, respecting a daily-loss cap and optional time
limit") for a strategy summarized by its annualized Sharpe and volatility.

Modeling choices, all pessimistic or neutral on purpose:
- End-of-day evaluation. Firms that check drawdown/daily-loss INTRADAY are
  stricter, so real pass probabilities there are at or below these numbers.
- A bust on the same day the target is reached counts as a bust.
- P&L is additive on the initial balance (fixed-notional), matching how firms
  measure targets and limits in account currency.
- Paths are truncated at ``max_days``; unresolved paths count as ``timeout``,
  never as passes — with no time limit the reported p_pass is a lower bound.
- Trailing drawdown is measured from the end-of-day high-water mark including
  the starting balance, and never "locks off" at breakeven (some firms stop
  trailing once the buffer clears the start — that leniency is ignored).

Honest framing: our validated momentum edge is small (net annualized Sharpe
~0.1-0.3). Over a one-to-three-month challenge horizon such an edge moves
P(pass) only a few points off the no-edge barrier-geometry baseline
D/(T+D). A challenge fee is therefore priced as a defined-risk option
purchase — never as an expectation of skill-dominated outcomes.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

TRADING_DAYS_PER_YEAR = 252


@dataclass(frozen=True)
class ChallengeRules:
    """One evaluation phase, end-of-day evaluated.

    All fractions are of the initial phase balance (how firms quote them).
    """

    profit_target: float
    max_drawdown: float
    trailing: bool
    daily_loss_limit: float | None
    time_limit_days: int | None
    min_trading_days: int = 0

    def __post_init__(self) -> None:
        if not 0 < self.profit_target < 1:
            raise ValueError("profit_target must be in (0, 1)")
        if not 0 < self.max_drawdown < 1:
            raise ValueError("max_drawdown must be in (0, 1)")
        if self.daily_loss_limit is not None and not 0 < self.daily_loss_limit < 1:
            raise ValueError("daily_loss_limit must be in (0, 1) or None")


@dataclass(frozen=True)
class PhaseOutcome:
    p_pass: float
    p_bust: float
    p_timeout: float
    median_days_to_pass: float | None


@dataclass(frozen=True)
class ChallengeOutcome:
    phases: tuple[PhaseOutcome, ...]
    p_total: float


def daily_params(annual_sharpe: float, annual_vol: float) -> tuple[float, float]:
    """Per-trading-day (mu, sigma) from annualized Sharpe and volatility."""

    if annual_vol < 0:
        raise ValueError("annual_vol must be >= 0")
    mu = annual_sharpe * annual_vol / TRADING_DAYS_PER_YEAR
    sigma = annual_vol / float(np.sqrt(TRADING_DAYS_PER_YEAR))
    return mu, sigma


def analytic_pass_static(mu: float, sigma: float, target: float, drawdown: float) -> float:
    """P(hit +target before -drawdown), Brownian motion, STATIC floor, no
    time limit, no daily cap (classical two-barrier gambler's ruin).

    With theta = 2*mu/sigma^2: P = (e^{theta*D} - 1) / (e^{theta*D} - e^{-theta*T});
    the driftless limit is D / (T + D) — volatility-independent.
    """

    if sigma <= 0:
        raise ValueError("sigma must be > 0 for the analytic form")
    theta = 2.0 * mu / (sigma * sigma)
    if abs(theta) < 1e-12:
        return drawdown / (target + drawdown)
    num = float(np.expm1(theta * drawdown))
    den = float(np.exp(theta * drawdown) - np.exp(-theta * target))
    return num / den


def analytic_pass_trailing(mu: float, sigma: float, target: float, drawdown: float) -> float:
    """P(hit +target before a -drawdown from the running maximum), Brownian,
    no time limit (Taylor 1975 / Lehoczky 1977 stopped-diffusion formula).

    With alpha = 2*mu/sigma^2: P = exp(-target*alpha / (e^{alpha*D} - 1));
    the driftless limit is e^{-target/drawdown}.
    """

    if sigma <= 0:
        raise ValueError("sigma must be > 0 for the analytic form")
    alpha = 2.0 * mu / (sigma * sigma)
    if abs(alpha) < 1e-12:
        return float(np.exp(-target / drawdown))
    return float(np.exp(-target * alpha / np.expm1(alpha * drawdown)))


def _first_true_day(mask: NDArray[np.bool_], sentinel: int) -> NDArray[np.int64]:
    """Per path: index of the first True in mask, or sentinel if none."""

    hit = mask.any(axis=1)
    first = mask.argmax(axis=1).astype(np.int64)
    return np.where(hit, first, np.int64(sentinel))


def simulate_phase(
    rules: ChallengeRules,
    mu_daily: float,
    sigma_daily: float,
    *,
    n_paths: int = 20_000,
    max_days: int = 400,
    seed: int = 7,
) -> PhaseOutcome:
    """Monte Carlo P(pass/bust/timeout) for one evaluation phase."""

    if n_paths < 1 or max_days < 1:
        raise ValueError("n_paths and max_days must be positive")
    horizon = max_days
    if rules.time_limit_days is not None:
        horizon = min(horizon, rules.time_limit_days)

    rng = np.random.default_rng(seed)
    returns = rng.normal(mu_daily, sigma_daily, size=(n_paths, horizon))
    equity = 1.0 + np.cumsum(returns, axis=1)

    sentinel = horizon + 1
    target_day = _first_true_day(equity >= 1.0 + rules.profit_target, sentinel)

    if rules.trailing:
        high_water = np.maximum(np.maximum.accumulate(equity, axis=1), 1.0)
        dd_bust = equity <= high_water - rules.max_drawdown
    else:
        dd_bust = equity <= 1.0 - rules.max_drawdown
    bust_day = _first_true_day(dd_bust, sentinel)
    if rules.daily_loss_limit is not None:
        daily_bust_day = _first_true_day(returns <= -rules.daily_loss_limit, sentinel)
        bust_day = np.minimum(bust_day, daily_bust_day)

    # Ties go to the bust (strict <). min_trading_days delays the pass
    # declaration (the trader flattens after the target, adding riskless
    # days), so it affects calendar time, not the pass/bust outcome.
    effective_pass_day = np.maximum(target_day, max(rules.min_trading_days - 1, 0))
    passed = (target_day < bust_day) & (effective_pass_day < sentinel)
    if rules.time_limit_days is not None:
        passed &= effective_pass_day < rules.time_limit_days
    busted = ~passed & (bust_day < sentinel)

    n = float(n_paths)
    p_pass = float(passed.sum()) / n
    p_bust = float(busted.sum()) / n
    median_days: float | None = None
    if passed.any():
        median_days = float(np.median(effective_pass_day[passed])) + 1.0
    return PhaseOutcome(
        p_pass=p_pass,
        p_bust=p_bust,
        p_timeout=max(0.0, 1.0 - p_pass - p_bust),
        median_days_to_pass=median_days,
    )


def simulate_challenge(
    phases: tuple[ChallengeRules, ...],
    annual_sharpe: float,
    annual_vol: float,
    *,
    n_paths: int = 20_000,
    max_days: int = 400,
    seed: int = 7,
) -> ChallengeOutcome:
    """All phases in sequence; phases are independent (same strategy, fresh
    balance each phase), so P(fund) is the product of phase pass rates."""

    if not phases:
        raise ValueError("need at least one phase")
    mu, sigma = daily_params(annual_sharpe, annual_vol)
    outcomes = tuple(
        simulate_phase(rules, mu, sigma, n_paths=n_paths, max_days=max_days, seed=seed + i)
        for i, rules in enumerate(phases)
    )
    p_total = 1.0
    for outcome in outcomes:
        p_total *= outcome.p_pass
    return ChallengeOutcome(phases=outcomes, p_total=p_total)


def expected_fees_per_funded_account(p_total: float, fee: float) -> float:
    """E[fees paid until first funding] under independent retries (geometric).

    This is the honest price of one funded account: fee / P(fund). It assumes
    the buyer pre-commits to burnable fee money and identical retries — any
    tilt-driven size-up between attempts invalidates it (and the buyer).
    """

    if not 0 < p_total <= 1:
        raise ValueError("p_total must be in (0, 1]")
    if fee < 0:
        raise ValueError("fee must be >= 0")
    return fee / p_total
