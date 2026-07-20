"""Milestone 19: deterministic live-trading readiness assessment."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from trading_desk.readiness import (
    Approver,
    AssessmentDomain,
    DomainAssessment,
    DomainStatus,
    Finding,
    FindingSeverity,
    GoLivePrerequisites,
    Recommendation,
    evaluate_readiness,
)


def domain(
    which: AssessmentDomain,
    *,
    status: DomainStatus = DomainStatus.PASS,
    findings: tuple[Finding, ...] = (),
) -> DomainAssessment:
    return DomainAssessment(
        domain=which, status=status, summary=f"{which.value} assessed", findings=findings
    )


def all_pass() -> tuple[DomainAssessment, ...]:
    return tuple(domain(item) for item in AssessmentDomain)


def met_prerequisites() -> GoLivePrerequisites:
    return GoLivePrerequisites(
        milestones_accepted=True,
        demo_operationally_certified=True,
        legal_and_financial_review_obtained=True,
        independent_safety_review_obtained=True,
        separate_live_infrastructure_and_credentials=True,
    )


APPROVERS = (Approver(name="Sepia7223", role="operator", review_date="2026-07-20"),)


def test_all_domains_must_be_assessed() -> None:
    with pytest.raises(ValueError):
        evaluate_readiness((domain(AssessmentDomain.ENGINEERING),), GoLivePrerequisites())


def test_current_demo_only_state_is_conditional_go_not_go() -> None:
    # Strong engineering but no legal review / certification / acceptance yet.
    dossier = evaluate_readiness(all_pass(), GoLivePrerequisites())
    assert dossier.recommendation is Recommendation.CONDITIONAL_GO
    assert "MILESTONES_NOT_ACCEPTED" in dossier.unmet_prerequisites
    assert "LEGAL_FINANCIAL_REVIEW_MISSING" in dossier.unmet_prerequisites
    assert "DEMO_NOT_CERTIFIED" in dossier.unmet_prerequisites


def test_demo_certification_alone_is_not_financial_suitability() -> None:
    # Only Demo certification set; legal/financial + safety review still missing.
    prereqs = GoLivePrerequisites(demo_operationally_certified=True)
    dossier = evaluate_readiness(all_pass(), prereqs, approvers=APPROVERS)
    assert dossier.recommendation is Recommendation.CONDITIONAL_GO
    assert "LEGAL_FINANCIAL_REVIEW_MISSING" in dossier.unmet_prerequisites


def test_unresolved_high_finding_forces_no_go() -> None:
    findings = (
        Finding(
            domain=AssessmentDomain.SECURITY,
            severity=FindingSeverity.HIGH,
            summary="credential rotation procedure undefined",
        ),
    )
    assessments = tuple(
        domain(item, status=DomainStatus.CONCERNS, findings=findings)
        if item is AssessmentDomain.SECURITY
        else domain(item)
        for item in AssessmentDomain
    )
    dossier = evaluate_readiness(assessments, met_prerequisites(), approvers=APPROVERS)
    assert dossier.recommendation is Recommendation.NO_GO
    assert any("SECURITY:HIGH" in item for item in dossier.blocking_findings)


def test_failed_domain_forces_no_go() -> None:
    assessments = tuple(
        domain(
            item,
            status=DomainStatus.FAIL
            if item is AssessmentDomain.RISK_GOVERNANCE
            else DomainStatus.PASS,
        )
        for item in AssessmentDomain
    )
    dossier = evaluate_readiness(assessments, met_prerequisites(), approvers=APPROVERS)
    assert dossier.recommendation is Recommendation.NO_GO


def test_go_requires_all_prerequisites_pass_and_approvers() -> None:
    dossier = evaluate_readiness(all_pass(), met_prerequisites(), approvers=APPROVERS)
    assert dossier.recommendation is Recommendation.GO
    assert dossier.unmet_prerequisites == ()
    assert dossier.blocking_findings == ()


def test_go_is_impossible_without_approvers_even_with_prerequisites() -> None:
    dossier = evaluate_readiness(all_pass(), met_prerequisites(), approvers=())
    assert dossier.recommendation is Recommendation.CONDITIONAL_GO


def test_resolved_findings_do_not_block() -> None:
    findings = (
        Finding(
            domain=AssessmentDomain.ENGINEERING,
            severity=FindingSeverity.HIGH,
            summary="was a gap, now fixed",
            resolved=True,
        ),
    )
    assessments = tuple(
        domain(item, findings=findings) if item is AssessmentDomain.ENGINEERING else domain(item)
        for item in AssessmentDomain
    )
    dossier = evaluate_readiness(assessments, met_prerequisites(), approvers=APPROVERS)
    assert dossier.recommendation is Recommendation.GO


def test_dossier_is_deterministic_and_fingerprinted() -> None:
    a = evaluate_readiness(all_pass(), GoLivePrerequisites())
    b = evaluate_readiness(tuple(reversed(all_pass())), GoLivePrerequisites())
    assert a.dossier_id == b.dossier_id


def test_dossier_fingerprint_rejects_tampering() -> None:
    dossier = evaluate_readiness(all_pass(), GoLivePrerequisites())
    payload = dossier.model_dump(mode="python")
    payload["recommendation"] = Recommendation.GO.value
    with pytest.raises(ValidationError):
        type(dossier).model_validate(payload)


def test_dossier_carries_demo_only_notice() -> None:
    dossier = evaluate_readiness(all_pass(), met_prerequisites(), approvers=APPROVERS)
    assert "does not enable Live trading" in dossier.demo_only_notice


def test_readiness_package_has_no_broker_or_live_dependencies() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "trading_desk" / "readiness"
    forbidden = re.compile(
        r"from trading_desk\.(ig|execution|lifecycle)"
        r"|import httpx|import requests|LIVE|live_credentials"
    )
    for path in root.glob("*.py"):
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith(("import ", "from ")):
                assert not forbidden.search(stripped), f"{path.name}: {stripped}"
