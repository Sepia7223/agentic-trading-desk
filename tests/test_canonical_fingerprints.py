"""Milestone 18: versioned canonical fingerprint library.

Proves the unified library preserves every legacy digest exactly (historical
identity), that canonical-v2 is distinct from all legacy schemes, and that v2 is
deterministic and secret-rejecting.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from trading_desk.canonical import (
    CanonicalScheme,
    canonical_fingerprint,
    versioned_fingerprint,
)
from trading_desk.context.fingerprints import fingerprint as context_fingerprint
from trading_desk.journal.fingerprints import fingerprint as journal_fingerprint
from trading_desk.risk.fingerprints import fingerprint as risk_fingerprint

SAMPLE = {
    "b": Decimal("1.50"),
    "a": 2,
    "ts": datetime(2026, 1, 1, tzinfo=UTC),
    "nested": [Decimal("0.1"), "x"],
}


def test_legacy_schemes_reproduce_original_digests_byte_for_byte() -> None:
    assert canonical_fingerprint(SAMPLE, scheme=CanonicalScheme.LEGACY_JOURNAL) == (
        journal_fingerprint(SAMPLE)
    )
    assert canonical_fingerprint(SAMPLE, scheme=CanonicalScheme.LEGACY_RISK) == (
        risk_fingerprint(SAMPLE)
    )
    assert canonical_fingerprint(SAMPLE, scheme=CanonicalScheme.LEGACY_CONTEXT) == (
        context_fingerprint(SAMPLE)
    )


def test_canonical_v2_is_distinct_from_every_legacy_scheme() -> None:
    v2 = canonical_fingerprint(SAMPLE, scheme=CanonicalScheme.CANONICAL_V2)
    legacy = {
        canonical_fingerprint(SAMPLE, scheme=scheme)
        for scheme in (
            CanonicalScheme.LEGACY_JOURNAL,
            CanonicalScheme.LEGACY_RISK,
            CanonicalScheme.LEGACY_CONTEXT,
        )
    }
    assert v2 not in legacy


def test_canonical_v2_is_the_default_scheme() -> None:
    assert canonical_fingerprint(SAMPLE) == canonical_fingerprint(
        SAMPLE, scheme=CanonicalScheme.CANONICAL_V2
    )


def test_canonical_v2_is_deterministic_and_key_order_independent() -> None:
    reordered = {
        "nested": [Decimal("0.1"), "x"],
        "ts": datetime(2026, 1, 1, tzinfo=UTC),
        "a": 2,
        "b": Decimal("1.50"),
    }
    assert canonical_fingerprint(SAMPLE) == canonical_fingerprint(reordered)


def test_canonical_v2_distinguishes_decimal_from_string() -> None:
    # The type-tagged representation must not collapse Decimal("1") and "1".
    assert canonical_fingerprint({"v": Decimal("1")}) != canonical_fingerprint({"v": "1"})


def test_canonical_v2_rejects_secret_bearing_values() -> None:
    with pytest.raises(ValueError):
        canonical_fingerprint({"password": "hunter2"})


def test_versioned_fingerprint_carries_scheme_and_flags_legacy() -> None:
    v2 = versioned_fingerprint(SAMPLE)
    assert v2.scheme is CanonicalScheme.CANONICAL_V2
    assert v2.is_legacy is False
    legacy = versioned_fingerprint(SAMPLE, scheme=CanonicalScheme.LEGACY_JOURNAL)
    assert legacy.is_legacy is True
    assert legacy.digest == journal_fingerprint(SAMPLE)


def test_versioned_fingerprint_rejects_non_hex_digest() -> None:
    with pytest.raises(ValidationError):
        type(versioned_fingerprint(SAMPLE))(scheme=CanonicalScheme.CANONICAL_V2, digest="Z" * 64)
