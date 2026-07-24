"""Challenge barrier-race simulator: the math must not flatter the buyer."""

from __future__ import annotations

import pytest

from trading_desk.research.challenge import (
    ChallengeRules,
    analytic_pass_static,
    analytic_pass_trailing,
    daily_params,
    expected_fees_per_funded_account,
    simulate_challenge,
    simulate_phase,
)

GENERIC = ChallengeRules(
    profit_target=0.08,
    max_drawdown=0.10,
    trailing=False,
    daily_loss_limit=0.05,
    time_limit_days=None,
    min_trading_days=0,
)


def test_sure_win_passes_every_path() -> None:
    out = simulate_phase(GENERIC, mu_daily=0.002, sigma_daily=0.0, n_paths=100)
    assert out.p_pass == 1.0
    assert out.p_bust == 0.0
    # 8% target at 20 bps/day: day 40 (1-indexed)
    assert out.median_days_to_pass == 40.0


def test_sure_loss_busts_every_path() -> None:
    out = simulate_phase(GENERIC, mu_daily=-0.002, sigma_daily=0.0, n_paths=100)
    assert out.p_pass == 0.0
    assert out.p_bust == 1.0


def test_driftless_pass_rate_matches_barrier_geometry() -> None:
    # Continuous no-cap benchmark: P = D / (T + D) = 10/18 ~ 0.556.
    rules = ChallengeRules(
        profit_target=0.08,
        max_drawdown=0.10,
        trailing=False,
        daily_loss_limit=None,
        time_limit_days=None,
    )
    out = simulate_phase(
        rules, mu_daily=0.0, sigma_daily=0.015, n_paths=8_000, max_days=1_000, seed=11
    )
    assert out.p_timeout < 0.01
    assert out.p_pass == pytest.approx(10.0 / 18.0, abs=0.05)


def test_trailing_drawdown_is_never_easier_than_static() -> None:
    static = simulate_phase(GENERIC, mu_daily=0.0003, sigma_daily=0.01, seed=3)
    trailing_rules = ChallengeRules(
        profit_target=GENERIC.profit_target,
        max_drawdown=GENERIC.max_drawdown,
        trailing=True,
        daily_loss_limit=GENERIC.daily_loss_limit,
        time_limit_days=GENERIC.time_limit_days,
    )
    trailing = simulate_phase(trailing_rules, mu_daily=0.0003, sigma_daily=0.01, seed=3)
    assert trailing.p_pass <= static.p_pass


def test_daily_loss_cap_binds_at_high_volatility() -> None:
    no_cap = ChallengeRules(
        profit_target=0.08,
        max_drawdown=0.10,
        trailing=False,
        daily_loss_limit=None,
        time_limit_days=None,
    )
    capped = simulate_phase(GENERIC, mu_daily=0.0, sigma_daily=0.03, seed=5)
    uncapped = simulate_phase(no_cap, mu_daily=0.0, sigma_daily=0.03, seed=5)
    assert capped.p_pass < uncapped.p_pass


def test_time_limit_only_hurts() -> None:
    limited_rules = ChallengeRules(
        profit_target=0.08,
        max_drawdown=0.10,
        trailing=False,
        daily_loss_limit=0.05,
        time_limit_days=30,
    )
    limited = simulate_phase(limited_rules, mu_daily=0.0003, sigma_daily=0.008, seed=9)
    unlimited = simulate_phase(GENERIC, mu_daily=0.0003, sigma_daily=0.008, seed=9)
    assert limited.p_pass <= unlimited.p_pass


def test_deterministic_given_seed() -> None:
    a = simulate_phase(GENERIC, mu_daily=0.0002, sigma_daily=0.012, seed=42)
    b = simulate_phase(GENERIC, mu_daily=0.0002, sigma_daily=0.012, seed=42)
    assert a == b


def test_two_phase_probability_is_product_of_phases() -> None:
    phase2 = ChallengeRules(
        profit_target=0.05,
        max_drawdown=0.10,
        trailing=False,
        daily_loss_limit=0.05,
        time_limit_days=None,
    )
    out = simulate_challenge((GENERIC, phase2), annual_sharpe=0.3, annual_vol=0.20)
    assert len(out.phases) == 2
    assert out.p_total == pytest.approx(out.phases[0].p_pass * out.phases[1].p_pass)


def test_daily_params_annualization() -> None:
    mu, sigma = daily_params(annual_sharpe=0.5, annual_vol=0.16)
    assert mu == pytest.approx(0.5 * 0.16 / 252)
    assert sigma == pytest.approx(0.16 / 252**0.5)


def test_expected_fees_price_the_retries() -> None:
    assert expected_fees_per_funded_account(0.5, 600.0) == 1200.0
    with pytest.raises(ValueError):
        expected_fees_per_funded_account(0.0, 600.0)


def test_analytic_zero_edge_limits() -> None:
    # Static: D/(T+D); trailing: e^(-T/D) (Taylor/Lehoczky).
    assert analytic_pass_static(0.0, 0.10, 0.08, 0.10) == pytest.approx(10 / 18)
    assert analytic_pass_trailing(0.0, 0.10, 0.08, 0.10) == pytest.approx(0.449, abs=0.001)


def test_monte_carlo_matches_analytic_static_with_edge() -> None:
    # Annual mu=20%, sigma=20% -> theta*D = 1.0 -> analytic ~0.757 (agent-
    # verified worked example). MC with daily steps carries small overshoot
    # bias; require agreement within 2.5pp.
    mu, sigma = daily_params(annual_sharpe=1.0, annual_vol=0.20)
    rules = ChallengeRules(
        profit_target=0.08,
        max_drawdown=0.10,
        trailing=False,
        daily_loss_limit=None,
        time_limit_days=None,
    )
    mc = simulate_phase(rules, mu, sigma, n_paths=20_000, max_days=2_000, seed=17)
    analytic = analytic_pass_static(mu * 252, sigma * 252**0.5, 0.08, 0.10)
    assert analytic == pytest.approx(0.757, abs=0.01)
    assert mc.p_pass == pytest.approx(analytic, abs=0.025)


def test_monte_carlo_brackets_analytic_trailing_with_edge() -> None:
    # The closed form (Taylor/Lehoczky) assumes CONTINUOUS monitoring of the
    # high-water mark; our simulator marks end-of-day, which misses intraday
    # peaks and is therefore genuinely more lenient. The EOD Monte Carlo must
    # sit AT OR ABOVE the continuous analytic, and within a bounded gap.
    mu, sigma = daily_params(annual_sharpe=1.0, annual_vol=0.20)
    rules = ChallengeRules(
        profit_target=0.08,
        max_drawdown=0.10,
        trailing=True,
        daily_loss_limit=None,
        time_limit_days=None,
    )
    mc = simulate_phase(rules, mu, sigma, n_paths=20_000, max_days=2_000, seed=19)
    analytic = analytic_pass_trailing(mu * 252, sigma * 252**0.5, 0.08, 0.10)
    assert analytic == pytest.approx(0.628, abs=0.01)
    assert mc.p_pass >= analytic - 0.01
    assert mc.p_pass <= analytic + 0.06


def test_rules_validation_rejects_nonsense() -> None:
    with pytest.raises(ValueError):
        ChallengeRules(
            profit_target=0.0,
            max_drawdown=0.10,
            trailing=False,
            daily_loss_limit=None,
            time_limit_days=None,
        )
    with pytest.raises(ValueError):
        ChallengeRules(
            profit_target=0.08,
            max_drawdown=1.5,
            trailing=False,
            daily_loss_limit=None,
            time_limit_days=None,
        )
