"""One versioned canonical fingerprint library (Milestone 18).

The desk grew three divergent canonicalizers — the journal scheme (type-tagged,
secret-rejecting), the risk scheme, and the context scheme — each producing a
different digest for the same value. This library unifies them behind a single
entry point without changing any historical identity: each legacy scheme is
named explicitly and delegates to its original implementation, so previously
persisted fingerprints remain byte-for-byte reproducible. A new ``CANONICAL_V2``
scheme is the forward canonicalization; it wraps the type-tagged, secret-safe
representation in an explicit version envelope so a v2 digest can never be
confused with any legacy digest.

Migration policy: new code should compute ``CANONICAL_V2`` fingerprints and carry
the scheme alongside the digest (:class:`VersionedFingerprint`). Existing records
keep their legacy scheme; nothing is silently recomputed.
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from trading_desk.context.fingerprints import fingerprint as _context_fingerprint
from trading_desk.journal.fingerprints import fingerprint as _journal_fingerprint
from trading_desk.journal.fingerprints import reject_secret_fields, to_primitive
from trading_desk.risk.fingerprints import fingerprint as _risk_fingerprint

CANONICAL_V2_VERSION = 2


class CanonicalScheme(StrEnum):
    LEGACY_JOURNAL = "LEGACY_JOURNAL"
    LEGACY_RISK = "LEGACY_RISK"
    LEGACY_CONTEXT = "LEGACY_CONTEXT"
    CANONICAL_V2 = "CANONICAL_V2"


_LEGACY_SCHEMES = frozenset(
    {
        CanonicalScheme.LEGACY_JOURNAL,
        CanonicalScheme.LEGACY_RISK,
        CanonicalScheme.LEGACY_CONTEXT,
    }
)


def _canonical_v2(value: object) -> str:
    reject_secret_fields(value)
    envelope = {"__canonical_version__": CANONICAL_V2_VERSION, "payload": to_primitive(value)}
    text = json.dumps(
        envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


_DISPATCH = {
    CanonicalScheme.LEGACY_JOURNAL: _journal_fingerprint,
    CanonicalScheme.LEGACY_RISK: _risk_fingerprint,
    CanonicalScheme.LEGACY_CONTEXT: _context_fingerprint,
    CanonicalScheme.CANONICAL_V2: _canonical_v2,
}


def canonical_fingerprint(
    value: object, *, scheme: CanonicalScheme = CanonicalScheme.CANONICAL_V2
) -> str:
    """Compute a fingerprint under an explicit scheme.

    Legacy schemes reproduce their original digests exactly; ``CANONICAL_V2`` is
    the forward, version-enveloped scheme and is the default for new code.
    """

    return _DISPATCH[scheme](value)


def is_legacy(scheme: CanonicalScheme) -> bool:
    return scheme in _LEGACY_SCHEMES


class VersionedFingerprint(BaseModel):
    """A fingerprint that carries its scheme, so legacy and v2 never conflate."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    scheme: CanonicalScheme
    digest: str = Field(min_length=64, max_length=64)

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if any(character not in "0123456789abcdef" for character in self.digest):
            raise ValueError("digest must be lowercase hexadecimal")
        return self

    @property
    def is_legacy(self) -> bool:
        return is_legacy(self.scheme)


def versioned_fingerprint(
    value: object, *, scheme: CanonicalScheme = CanonicalScheme.CANONICAL_V2
) -> VersionedFingerprint:
    return VersionedFingerprint(scheme=scheme, digest=canonical_fingerprint(value, scheme=scheme))
