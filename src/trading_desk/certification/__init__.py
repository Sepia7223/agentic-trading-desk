"""Full IG Demo operational certification (Milestone 17).

Deterministic evidence contracts and verdict logic. This package structures and
evaluates certification evidence that actually occurred; it holds no trading
authority and never manufactures a candidate or forces a trade.
"""

from trading_desk.certification.evidence import (
    NATURAL_TRADE_ITEMS,
    SOFTWARE_READONLY_ITEMS,
    CertificationDefect,
    CertificationItem,
    DefectCategory,
    EvidenceObservation,
    manufactured_evidence_is_prohibited,
    observed_items,
)
from trading_desk.certification.verdict import (
    CertificationOutcome,
    CertificationVerdict,
    evaluate_certification,
)

__all__ = [
    "NATURAL_TRADE_ITEMS",
    "SOFTWARE_READONLY_ITEMS",
    "CertificationDefect",
    "CertificationItem",
    "CertificationOutcome",
    "CertificationVerdict",
    "DefectCategory",
    "EvidenceObservation",
    "evaluate_certification",
    "manufactured_evidence_is_prohibited",
    "observed_items",
]
