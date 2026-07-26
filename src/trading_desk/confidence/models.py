"""Deterministic pre-trade confidence score (formula v1, versioned).

The score is a transparent weighted blend of measurable states - nothing
here is model-generated or subjective, so the calibration ledger can hold
it accountable trade by trade. Changing the formula (weights, inputs)
MUST bump SCORE_VERSION: buckets from different versions are never pooled.
"""

from __future__ import annotations

from dataclasses import dataclass

SCORE_VERSION = "cwk-v1"

# (name, lower bound inclusive) - upper bound is the next bucket's lower.
BUCKETS: tuple[tuple[str, float], ...] = (
    ("low", 0.0),
    ("base", 0.40),
    ("elevated", 0.55),
    ("high", 0.70),
    ("very_high", 0.85),
)

WEIGHT_SIGNAL = 0.35
WEIGHT_AGREEMENT = 0.25
WEIGHT_REGIME = 0.20
WEIGHT_CROWDING = 0.20
CAUTION_DISCOUNT = 0.75  # news CAUTION multiplies the whole score


@dataclass(frozen=True)
class ConfidenceInputs:
    """All inputs are 0..1 and must be computable BEFORE the trade.

    signal_percentile: strength of the entry signal within its ranking
        (e.g. momentum-score percentile inside the eligible cross-section).
    sleeve_agreement: fraction of independent validated sleeves whose
        current reading agrees with the trade direction (0.5 = neutral
        when only one sleeve exists or the other has no reading).
    regime_vol_percentile: today's realized index vol vs its own history
        (high percentile = hostile regime = lower confidence).
    crowding_penalty: from the pre-trade correlation module (1 = maximally
        crowded book for this name's cluster).
    news_state: "clear" or "caution". BLOCK never reaches sizing at all -
        the pre-trade pipeline rejects it before this module is consulted.
    """

    signal_percentile: float
    sleeve_agreement: float
    regime_vol_percentile: float
    crowding_penalty: float
    news_state: str

    def __post_init__(self) -> None:
        for name in (
            "signal_percentile",
            "sleeve_agreement",
            "regime_vol_percentile",
            "crowding_penalty",
        ):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be in [0, 1], got {value}")
        if self.news_state not in ("clear", "caution"):
            raise ValueError("news_state must be 'clear' or 'caution'")


def confidence_score(inputs: ConfidenceInputs) -> float:
    """0..1 confidence, deterministic, formula v1."""

    score = (
        WEIGHT_SIGNAL * inputs.signal_percentile
        + WEIGHT_AGREEMENT * inputs.sleeve_agreement
        + WEIGHT_REGIME * (1.0 - inputs.regime_vol_percentile)
        + WEIGHT_CROWDING * (1.0 - inputs.crowding_penalty)
    )
    if inputs.news_state == "caution":
        score *= CAUTION_DISCOUNT
    return max(0.0, min(1.0, score))


def bucket_of(score: float) -> str:
    """Bucket name for a 0..1 score."""

    if not 0.0 <= score <= 1.0:
        raise ValueError(f"score must be in [0, 1], got {score}")
    name = BUCKETS[0][0]
    for bucket_name, lower in BUCKETS:
        if score >= lower:
            name = bucket_name
    return name
