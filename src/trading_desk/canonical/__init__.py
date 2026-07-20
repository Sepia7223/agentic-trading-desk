"""Versioned canonical fingerprint library (Milestone 18).

One entry point for canonical fingerprints. Legacy schemes preserve historical
identities exactly; ``CANONICAL_V2`` is the forward scheme for new code.
"""

from trading_desk.canonical.fingerprints import (
    CANONICAL_V2_VERSION,
    CanonicalScheme,
    VersionedFingerprint,
    canonical_fingerprint,
    is_legacy,
    versioned_fingerprint,
)

__all__ = [
    "CANONICAL_V2_VERSION",
    "CanonicalScheme",
    "VersionedFingerprint",
    "canonical_fingerprint",
    "is_legacy",
    "versioned_fingerprint",
]
