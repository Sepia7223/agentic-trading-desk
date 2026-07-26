"""Confidence-weighted fractional-Kelly sizing (user-specified, 2026-07-25).

Design contract:
- A deterministic 0..1 confidence score is computed BEFORE each trade from
  measurable inputs (signal strength, sleeve agreement, news state, vol
  regime, crowding). No LLM output can raise it (advisory stays
  attenuation-only elsewhere).
- Every closed trade is recorded in an append-only calibration ledger:
  (confidence bucket -> realized R). Confidence earns sizing power only
  through this forward record.
- Sizing: fractional Kelly (quarter) per bucket, with hard unlock rules -
  a bucket must have >= MIN_TRADES closed outcomes before it may size
  ABOVE baseline; downsizing low confidence needs no evidence. Multiplier
  capped; the portfolio stress budget and circuit breakers still bind
  upstream of everything here.
"""

from trading_desk.confidence.ledger import BucketStats, CalibrationLedger
from trading_desk.confidence.models import (
    BUCKETS,
    ConfidenceInputs,
    bucket_of,
    confidence_score,
)
from trading_desk.confidence.sizing import KellySizer, target_r_multiple

__all__ = [
    "BUCKETS",
    "BucketStats",
    "CalibrationLedger",
    "ConfidenceInputs",
    "KellySizer",
    "bucket_of",
    "confidence_score",
    "target_r_multiple",
]
