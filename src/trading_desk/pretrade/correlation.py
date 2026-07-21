"""Correlation-cluster calculator for the portfolio projection.

Supplies ``PortfolioProjection.max_correlated_cluster_weight``: the largest
combined gross weight of any group of held names whose pairwise return
correlation exceeds a threshold. Greedy single-linkage clustering over the
correlation matrix of trailing daily returns — deterministic, dependency-free,
and conservative (single-linkage merges aggressively, so clusters are never
understated).

Pure logic: the caller supplies aligned return series; no I/O here.
"""

from __future__ import annotations

from decimal import Decimal


def _pearson(a: list[float], b: list[float]) -> float:
    n = len(a)
    if n < 3:
        return 0.0
    ma = sum(a) / n
    mb = sum(b) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b, strict=True))
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((y - mb) ** 2 for y in b)
    if va <= 0 or vb <= 0:
        return 0.0
    return float(cov / (va * vb) ** 0.5)


def max_correlated_cluster_weight(
    returns: dict[str, list[float]],
    weights: dict[str, Decimal],
    *,
    threshold: float = 0.7,
    min_observations: int = 30,
) -> Decimal:
    """Largest combined |weight| of any single-linkage cluster at ``threshold``.

    ``returns``: aligned trailing daily returns per held symbol (same length).
    ``weights``: gross weight per held symbol (sign irrelevant; abs is used).
    Symbols with fewer than ``min_observations`` observations are treated as
    their own cluster (their weight still counts alone).
    """

    symbols = [s for s in weights if s in returns]
    parent: dict[str, str] = {s: s for s in symbols}

    def find(s: str) -> str:
        while parent[s] != s:
            parent[s] = parent[parent[s]]
            s = parent[s]
        return s

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    usable = [s for s in symbols if len(returns[s]) >= min_observations]
    for i, a in enumerate(usable):
        for b in usable[i + 1 :]:
            k = min(len(returns[a]), len(returns[b]))
            if _pearson(returns[a][-k:], returns[b][-k:]) >= threshold:
                union(a, b)

    cluster_weight: dict[str, Decimal] = {}
    for s in symbols:
        root = find(s)
        cluster_weight[root] = cluster_weight.get(root, Decimal("0")) + abs(weights[s])
    if not cluster_weight:
        return Decimal("0")
    return max(cluster_weight.values())
