from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.render_ig_demo_certification import JSON_ARTIFACTS, render

ROOT = Path(__file__).parents[1]
TEMPLATES = ROOT / "artifacts" / "ig_demo_certification" / "templates"


def test_renderer_creates_complete_sanitized_package(tmp_path: Path) -> None:
    observations = tmp_path / "observations.json"
    observations.write_text(
        json.dumps(
            {
                "_configuration_fingerprints": {"opportunity": "c" * 64},
                "_sanitized_evidence_ids": ["evidence-1"],
                "environment_summary.json": {"result_status": "PASSED"},
                "_limitations": ["No natural entry occurred."],
                "_decision_summary": "Read-only paths passed; entry remains pending.",
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "rendered"
    render(
        TEMPLATES,
        observations,
        output,
        base_sha="a" * 40,
        head_sha="b" * 40,
        decision="PARTIALLY_CERTIFIED",
    )
    assert all((output / name).is_file() for name in JSON_ARTIFACTS)
    manifest = json.loads((output / "certification_manifest.json").read_text(encoding="utf-8"))
    assert manifest["result_status"] == "PARTIALLY_CERTIFIED"
    assert manifest["head_sha"] == "b" * 40
    assert manifest["configuration_fingerprints"]["opportunity"] == "c" * 64
    assert "PARTIALLY_CERTIFIED" in (output / "final_decision.md").read_text(encoding="utf-8")


def test_renderer_rejects_certified_without_complete_operational_evidence(
    tmp_path: Path,
) -> None:
    observations = tmp_path / "observations.json"
    observations.write_text(
        json.dumps(
            {
                "_configuration_fingerprints": {"opportunity": "c" * 64},
                "_sanitized_evidence_ids": ["evidence-1"],
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "rendered"
    with pytest.raises(ValueError, match="CERTIFIED evidence requirement failed"):
        render(
            TEMPLATES,
            observations,
            output,
            base_sha="a" * 40,
            head_sha="b" * 40,
            decision="CERTIFIED",
        )
    assert not output.exists()


def test_renderer_accepts_certified_only_with_complete_operational_evidence(
    tmp_path: Path,
) -> None:
    observations = tmp_path / "observations.json"
    observations.write_text(
        json.dumps(
            {
                "_configuration_fingerprints": {"opportunity": "c" * 64},
                "_sanitized_evidence_ids": ["entry-evidence", "close-evidence"],
                "environment_summary.json": {
                    "result_status": "PASSED",
                    "environment": "DEMO",
                    "live_available": False,
                    "canonical_gateway": True,
                },
                "read_only_scan_report.json": {
                    "result_status": "PASSED",
                    "broker_mutations": 0,
                },
                "scheduler_report.json": {
                    "result_status": "PASSED",
                    "duplicate_evaluations": 0,
                    "restart_verified": True,
                    "process_lock_verified": True,
                },
                "campaign_start_report.json": {
                    "result_status": "PASSED",
                    "duplicate_start_rejected": True,
                    "restart_verified": True,
                },
                "runtime_observation_report.json": {
                    "result_status": "PASSED",
                    "orders_submitted": 1,
                },
                "entry_certification.json": {
                    "result_status": "PASSED",
                    "natural_candidate_observed": True,
                    "positive_net_expected_value": True,
                    "exposure_clearance": True,
                    "correlation_clearance": True,
                    "risk_approved": True,
                    "mutation_attempts": 1,
                    "write_ahead_submission_recorded": True,
                    "single_submission_verified": True,
                    "broker_confirmation": "ACCEPTED",
                    "reconciliation": "RECONCILED",
                    "confirmed_quantity_present": True,
                    "confirmed_entry_level_present": True,
                },
                "lifecycle_certification.json": {
                    "result_status": "PASSED",
                    "position_discovered": True,
                    "monitoring_verified": True,
                    "close_attempts": 1,
                    "position_restart_verified": True,
                    "close_confirmation": "ACCEPTED",
                    "close_reconciliation": "POSITION_CLOSED",
                    "realized_pnl_present": True,
                    "realized_costs_present": True,
                    "campaign_updated": True,
                    "durable_lineage_verified": True,
                    "session_cleanup_completed": True,
                },
                "operations_center_report.json": {
                    "result_status": "PASSED",
                    "loopback_only": True,
                    "read_only_api_verified": True,
                    "websocket_server_to_client_only": True,
                    "mutation_controls_present": True,
                    "credential_exposure_detected": False,
                    "entry_projected": True,
                    "position_projected": True,
                    "lifecycle_close_projected": True,
                    "campaign_projected": True,
                    "journal_integrity_verified": True,
                },
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "rendered"
    render(
        TEMPLATES,
        observations,
        output,
        base_sha="a" * 40,
        head_sha="b" * 40,
        decision="CERTIFIED",
    )
    manifest = json.loads((output / "certification_manifest.json").read_text(encoding="utf-8"))
    assert manifest["result_status"] == "CERTIFIED"


@pytest.mark.parametrize("field", ("password", "api_key", "access_token", "account_id"))
def test_renderer_rejects_sensitive_fields_before_writing(tmp_path: Path, field: str) -> None:
    observations = tmp_path / "observations.json"
    observations.write_text(
        json.dumps({"environment_summary.json": {field: "synthetic-sensitive-value"}}),
        encoding="utf-8",
    )
    output = tmp_path / "rendered"
    with pytest.raises(ValueError, match="forbidden certification field"):
        render(
            TEMPLATES,
            observations,
            output,
            base_sha="a" * 40,
            head_sha="b" * 40,
            decision="FAILED",
        )
    assert not output.exists()
