"""Probabilistic and Deflated Sharpe Ratios (Bailey & Lopez de Prado, 2014).

PSR answers: given estimation error from a finite, possibly non-normal return
sample, what is the probability the TRUE Sharpe exceeds a benchmark?

DSR hardens PSR against selection bias: the benchmark becomes the maximum
Sharpe expected from N independent trials under the null of zero skill, so a
strategy picked as "the best of N" must clear the luck ceiling its own search
created. All Sharpe inputs are per-period (not annualized); n is the number of
return observations; skewness/kurtosis are of the same return series (kurtosis
is the raw fourth standardized moment: normal = 3).
"""

from __future__ import annotations

import math

from scipy.stats import norm  # type: ignore[import-untyped]

EULER_GAMMA = 0.5772156649015329


def probabilistic_sharpe_ratio(
    observed_sharpe: float,
    benchmark_sharpe: float,
    n_observations: int,
    skewness: float = 0.0,
    kurtosis: float = 3.0,
) -> float:
    """P(true Sharpe > benchmark | sample), per Bailey-LdP eq. (11)."""

    if n_observations < 2:
        raise ValueError("need at least 2 observations")
    variance_adj = 1.0 - skewness * observed_sharpe + (kurtosis - 1.0) / 4.0 * observed_sharpe**2
    if variance_adj <= 0:
        # extreme higher moments: estimator variance undefined; fail closed
        return 0.0
    z = (
        (observed_sharpe - benchmark_sharpe)
        * math.sqrt(n_observations - 1)
        / math.sqrt(variance_adj)
    )
    return float(norm.cdf(z))


def expected_max_sharpe(n_trials: int, sharpe_variance: float) -> float:
    """E[max Sharpe] across n_trials of pure luck (null of zero skill).

    ``sharpe_variance`` is the cross-trial variance of the Sharpe estimates
    (use the empirical variance across registry trials; falls back sensibly
    for n_trials == 1).
    """

    if n_trials < 1:
        raise ValueError("n_trials must be >= 1")
    if sharpe_variance < 0:
        raise ValueError("sharpe_variance must be >= 0")
    if n_trials == 1:
        return 0.0
    sd = math.sqrt(sharpe_variance)
    a = norm.ppf(1.0 - 1.0 / n_trials)
    b = norm.ppf(1.0 - 1.0 / (n_trials * math.e))
    return float(sd * ((1.0 - EULER_GAMMA) * a + EULER_GAMMA * b))


def deflated_sharpe_ratio(
    observed_sharpe: float,
    n_trials: int,
    sharpe_variance: float,
    n_observations: int,
    skewness: float = 0.0,
    kurtosis: float = 3.0,
) -> float:
    """DSR = PSR evaluated against the luck ceiling of the search itself."""

    ceiling = expected_max_sharpe(n_trials, sharpe_variance)
    return probabilistic_sharpe_ratio(observed_sharpe, ceiling, n_observations, skewness, kurtosis)
