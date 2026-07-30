"""Deterministic artifact validators — hallucination becomes a filter.

Every Evidence.quote must appear VERBATIM in the supplied source texts; an
artifact failing the check is discarded and logged, never repaired. This
converts model hallucination from a quality problem into a mechanical reject.
"""

from __future__ import annotations

from trading_desk.agents.models import Evidence


class EvidenceError(ValueError):
    """An evidence quote does not match its claimed source."""


def validate_evidence(
    evidence: tuple[Evidence, ...] | list[Evidence],
    sources: dict[str, str],
) -> None:
    """Raise EvidenceError unless every quote appears verbatim in its source."""

    for item in evidence:
        source_text = sources.get(item.source_id)
        if source_text is None:
            raise EvidenceError(f"unknown source_id {item.source_id!r}")
        if item.quote not in source_text:
            raise EvidenceError(
                f"quote not found verbatim in {item.source_id!r}: {item.quote[:60]!r}"
            )
