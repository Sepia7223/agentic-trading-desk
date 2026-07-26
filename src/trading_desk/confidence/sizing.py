"""Confidence-weighted fractional-Kelly sizing with evidence-gated unlocks.

The rule set that keeps 'money hungry' harnessed instead of dangerous:

- Baseline risk is whatever the account's governed configuration says;
  this module only produces a MULTIPLIER on it.
- A bucket may multiply ABOVE 1.0 only after MIN_TRADES closed outcomes
  prove its edge (the unlock the user specified: 'know how many times that
  high percentage confidence works' BEFORE risking more on it).
- Downsizing (low-confidence buckets) applies immediately - reducing risk
  needs no evidence.
- The multiplier comes from quarter-Kelly of the bucket's own realized
  record, relative to the all-trades baseline, and is hard-capped.
- Stops stay volatility-owned. Confidence moves the dollar risk (this
  multiplier) and the TARGET distance (let high-confidence winners run).
- Everything here sits BELOW the stress budget, correlation caps and
  circuit breakers, which bind exactly as before.
"""

from __future__ import annotations

from dataclasses import dataclass

from trading_desk.confidence.ledger import CalibrationLedger
from trading_desk.confidence.models import BUCKETS, bucket_of

KELLY_FRACTION = 0.25  # quarter-Kelly everywhere; full Kelly is never used
MIN_TRADES_TO_UNLOCK = 30  # closed outcomes a bucket needs to size above 1x
MAX_MULTIPLIER = 3.0
MIN_MULTIPLIER = 0.25
LOW_CONFIDENCE_MULTIPLIER = 0.5  # immediate downsizing, no evidence needed

TARGET_R_MIN = 1.5  # reward:risk target at zero confidence
TARGET_R_MAX = 3.0  # reward:risk target at full confidence


@dataclass(frozen=True)
class SizeDecision:
    confidence: float
    bucket: str
    multiplier: float
    unlocked: bool
    reason: str


def target_r_multiple(confidence: float) -> float:
    """Reward:risk target scales linearly with confidence."""

    if not 0.0 <= confidence <= 1.0:
        raise ValueError("confidence must be in [0, 1]")
    return TARGET_R_MIN + (TARGET_R_MAX - TARGET_R_MIN) * confidence


class KellySizer:
    def __init__(self, ledger: CalibrationLedger) -> None:
        self.ledger = ledger

    def _baseline_kelly(self) -> float:
        """Quarter-Kelly of ALL recorded trades pooled (the account's own
        demonstrated edge). Zero until any history exists."""

        pooled = [self.ledger.bucket_stats(name) for name, _ in BUCKETS]
        n = sum(s.n for s in pooled)
        if n == 0:
            return 0.0
        wins = sum(s.n * s.win_rate for s in pooled)
        win_rate = wins / n
        avg_win = sum(s.n * s.win_rate * s.average_win_r for s in pooled) / wins if wins else 0.0
        loss_n = n - wins
        avg_loss = (
            sum(s.n * (1 - s.win_rate) * s.average_loss_r for s in pooled) / loss_n
            if loss_n
            else 0.0
        )
        if avg_loss == 0 or avg_win <= 0:
            return 0.0
        payoff = avg_win / abs(avg_loss)
        return max(0.0, KELLY_FRACTION * (win_rate - (1 - win_rate) / payoff))

    def decide(self, confidence: float) -> SizeDecision:
        bucket = bucket_of(confidence)
        if bucket == "low":
            return SizeDecision(
                confidence,
                bucket,
                LOW_CONFIDENCE_MULTIPLIER,
                True,
                "low confidence: immediate downsizing (no evidence required)",
            )
        stats = self.ledger.bucket_stats(bucket)
        if stats.n < MIN_TRADES_TO_UNLOCK:
            return SizeDecision(
                confidence,
                bucket,
                1.0,
                False,
                f"bucket has {stats.n}/{MIN_TRADES_TO_UNLOCK} closed trades: "
                "baseline size until the record earns more",
            )
        bucket_kelly = KELLY_FRACTION * stats.kelly_fraction()
        baseline = self._baseline_kelly()
        if baseline <= 0:
            return SizeDecision(
                confidence,
                bucket,
                1.0,
                False,
                "account-level record has no positive edge yet: baseline size",
            )
        multiplier = max(MIN_MULTIPLIER, min(MAX_MULTIPLIER, bucket_kelly / baseline))
        return SizeDecision(
            confidence,
            bucket,
            round(multiplier, 4),
            True,
            f"quarter-Kelly of bucket record (n={stats.n}, "
            f"win {stats.win_rate:.0%}, payoff {stats.payoff_ratio:.2f}) "
            f"vs account baseline",
        )
