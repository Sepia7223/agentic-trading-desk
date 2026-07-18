import pytest
from pydantic import ValidationError
from tests.opportunity_helpers import candidate, evidence


def test_models_are_frozen_strict_and_deterministic() -> None:
    first = candidate()
    second = candidate()
    assert first == second
    assert first.candidate_fingerprint == second.candidate_fingerprint
    with pytest.raises(ValidationError):
        evidence(extra="prohibited")
    with pytest.raises(ValidationError):
        first.instrument_id = "GBP/USD"  # type: ignore[misc]


def test_unfinished_and_missing_evidence_fail_closed() -> None:
    with pytest.raises(ValidationError):
        evidence(completed_bar_timestamp=evidence().created_at)
    with pytest.raises(ValidationError):
        evidence(evidence_ids=())
