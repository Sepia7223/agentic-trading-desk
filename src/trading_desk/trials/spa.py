"""Hansen's Superior Predictive Ability test (2005), vendored and minimal.

Question answered: "after accounting for having searched over K candidates,
does the BEST candidate genuinely outperform the benchmark?" This is the gate
any composite must pass against the live momentum strategy before adoption.

Implementation: stationary bootstrap (Politis-Romano) over the loss
differentials d[k, t] = candidate_k[t] - benchmark[t] (positive = candidate
better), studentized by bootstrap variance, with Hansen's consistent
recentering so deeply-inferior candidates do not distort the null. Vendored
(~120 lines) instead of importing arch to keep the dependency surface small
and the math auditable. Deterministic via seed.
"""

from __future__ import annotations

import math

import numpy as np


def stationary_bootstrap_indices(
    n: int, n_boot: int, mean_block: float, rng: np.random.Generator
) -> np.ndarray:
    """(n_boot, n) index matrix from the Politis-Romano stationary bootstrap."""

    if mean_block < 1:
        raise ValueError("mean_block must be >= 1")
    p = 1.0 / mean_block
    out = np.empty((n_boot, n), dtype=np.int64)
    for b in range(n_boot):
        idx = np.empty(n, dtype=np.int64)
        t = rng.integers(0, n)
        for i in range(n):
            idx[i] = t
            # new block with prob p, else continue the current block (circular)
            t = rng.integers(0, n) if rng.random() < p else (t + 1) % n
        out[b] = idx
    return out


def spa_test(
    benchmark: np.ndarray,
    candidates: dict[str, np.ndarray],
    *,
    n_boot: int = 1000,
    mean_block: float = 21.0,
    seed: int = 42,
) -> dict[str, float]:
    """Consistent SPA p-value for H0: no candidate beats the benchmark.

    Returns {"p_value", "t_stat", "best_candidate_mean"}. Small p-value =>
    the best candidate's outperformance is unlikely to be a search artifact.
    """

    if not candidates:
        raise ValueError("need at least one candidate")
    bench = np.asarray(benchmark, dtype=float)
    n = bench.shape[0]
    if n < 30:
        raise ValueError("need at least 30 observations")
    names = sorted(candidates)
    arrays = [np.asarray(candidates[k], dtype=float) for k in names]
    if any(a.shape != bench.shape for a in arrays):
        raise ValueError("candidate series must align with the benchmark")
    d = np.stack([a - bench for a in arrays])  # (K, n)

    rng = np.random.default_rng(seed)
    means = d.mean(axis=1)  # (K,)
    boot_idx = stationary_bootstrap_indices(n, n_boot, mean_block, rng)
    boot_means = d[:, boot_idx].mean(axis=2)  # (K, n_boot)

    # bootstrap estimate of the asymptotic variance of sqrt(n)*mean
    omega2 = n * boot_means.var(axis=1, ddof=1)  # (K,)
    omega = np.sqrt(np.maximum(omega2, 1e-18))

    t_stat = float(np.max(np.maximum(np.sqrt(n) * means / omega, 0.0)))

    # Hansen's consistent recentering: candidates whose deficit is beyond the
    # log-log boundary contribute a zero-mean null, not their full deficit.
    boundary = omega / math.sqrt(n) * math.sqrt(2.0 * math.log(math.log(max(n, 3))))
    recenter = np.where(means >= -boundary, means, 0.0)  # (K,)

    z = boot_means - recenter[:, None]  # (K, n_boot)
    t_boot = np.max(np.maximum(np.sqrt(n) * z / omega[:, None], 0.0), axis=0)
    p_value = float((t_boot >= t_stat).mean())
    return {
        "p_value": p_value,
        "t_stat": t_stat,
        "best_candidate_mean": float(means.max()),
    }
