"""Milestone 17: deterministic certification verdict logic."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from trading_desk.certification import (
    NATURAL_TRADE_ITEMS,
    SOFTWARE_READONLY_ITEMS,
    CertificationDefect,
    CertificationItem,
    CertificationVerdict,
    DefectCategory,
    EvidenceObservation,
    evaluate_certification,
    manufactured_evidence_is_prohibited,
)


def obs(item: CertificationItem, *, observed: bool = True) -> EvidenceObservation:
    return EvidenceObservation(
        item=item,
        observed=observed,
        source_evidence_id=f"evidence-{item.value.lower()}" if observed else "",
    )


def all_observations() -> tuple[EvidenceObservation, ...]:
    return tuple(obs(item) for item in CertificationItem)


def software_only_observations() -> tuple[EvidenceObservation, ...]:
    return tuple(obs(item) for item in SOFTWARE_READONLY_ITEMS)


def test_the_two_groups_partition_all_seventeen_items() -> None:
    assert SOFTWARE_READONLY_ITEMS.isdisjoint(NATURAL_TRADE_ITEMS)
    assert set(CertificationItem) == SOFTWARE_READONLY_ITEMS | NATURAL_TRADE_ITEMS
    assert len(set(CertificationItem)) == 17


def test_all_items_present_yields_certified() -> None:
    outcome = evaluate_certification(all_observations())
    assert outcome.verdict is CertificationVerdict.CERTIFIED
    assert outcome.pending_items == ()
    assert outcome.natural_trade_complete is True


def test_software_only_yields_partially_certified_not_failed() -> None:
    outcome = evaluate_certification(software_only_observations())
    assert outcome.verdict is CertificationVerdict.PARTIALLY_CERTIFIED
    assert outcome.software_readonly_complete is True
    assert outcome.natural_trade_complete is False
    assert set(outcome.pending_items) == NATURAL_TRADE_ITEMS
    assert "continue later" in outcome.rationale


def test_absent_natural_trade_is_never_a_defect() -> None:
    # No trade observed and no defect recorded -> not FAILED.
    outcome = evaluate_certification(software_only_observations(), ())
    assert outcome.verdict is not CertificationVerdict.FAILED


def test_any_defect_forces_failed_even_with_full_evidence() -> None:
    defect = CertificationDefect(
        category=DefectCategory.RECONCILIATION,
        summary="close reconciliation mismatch",
        source_evidence_id="evidence-recon-1",
    )
    outcome = evaluate_certification(all_observations(), (defect,))
    assert outcome.verdict is CertificationVerdict.FAILED
    assert "RECONCILIATION" in outcome.rationale


def test_duplicate_mutation_defect_forces_failed() -> None:
    defect = CertificationDefect(
        category=DefectCategory.DUPLICATE_MUTATION,
        summary="second submission after restart",
        source_evidence_id="evidence-dup-1",
    )
    outcome = evaluate_certification(all_observations(), (defect,))
    assert outcome.verdict is CertificationVerdict.FAILED


def test_incomplete_software_evidence_stays_partially_certified() -> None:
    partial = tuple(
        obs(item)
        for item in SOFTWARE_READONLY_ITEMS
        if item is not CertificationItem.OPERATIONS_CENTER_VISIBILITY
    )
    outcome = evaluate_certification(partial)
    assert outcome.verdict is CertificationVerdict.PARTIALLY_CERTIFIED
    assert outcome.software_readonly_complete is False


def test_outcome_is_deterministic_and_fingerprinted() -> None:
    a = evaluate_certification(software_only_observations())
    b = evaluate_certification(tuple(reversed(software_only_observations())))
    assert a.outcome_id == b.outcome_id


def test_outcome_fingerprint_rejects_tampering() -> None:
    outcome = evaluate_certification(all_observations())
    payload = outcome.model_dump(mode="python")
    payload["verdict"] = CertificationVerdict.CERTIFIED.value
    payload["pending_items"] = [CertificationItem.CONTROLLED_ORDER_SUBMISSION.value]
    with pytest.raises(ValidationError):
        type(outcome).model_validate(payload)


def test_observed_item_requires_source_evidence() -> None:
    with pytest.raises(ValidationError):
        EvidenceObservation(
            item=CertificationItem.CONTROLLED_ORDER_SUBMISSION,
            observed=True,
            source_evidence_id="",
        )


def test_manufactured_evidence_guard_rejects_synthetic_notes() -> None:
    manufactured_evidence_is_prohibited("natural candidate from live scan")
    for banned in ("forced entry", "synthetic candidate", "manufactured trade"):
        with pytest.raises(ValueError):
            manufactured_evidence_is_prohibited(banned)


def test_certification_package_has_no_broker_or_mutation_dependencies() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "trading_desk" / "certification"
    forbidden = re.compile(
        r"from trading_desk\.(ig|execution|lifecycle|api|risk|portfolio)"
        r"|import httpx|import requests"
    )
    for path in root.glob("*.py"):
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith(("import ", "from ")):
                assert not forbidden.search(stripped), f"{path.name}: {stripped}"
