"""Render sanitized IG Demo certification evidence outside tracked source files."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

JSON_ARTIFACTS = (
    "certification_manifest.json",
    "environment_summary.json",
    "read_only_scan_report.json",
    "scheduler_report.json",
    "campaign_start_report.json",
    "runtime_observation_report.json",
    "entry_certification.json",
    "lifecycle_certification.json",
    "operations_center_report.json",
)
FORBIDDEN_KEYS = {
    "password",
    "api_key",
    "access_token",
    "refresh_token",
    "authorization",
    "raw_response",
    "raw_headers",
    "account_id",
}
FORBIDDEN_VALUE_MARKERS = ("bearer ", "x-ig-api-key", "x-security-token", "cst=")

CERTIFIED_EXACT_VALUES = {
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


def render(
    templates: Path,
    observations_path: Path,
    output: Path,
    *,
    base_sha: str,
    head_sha: str,
    decision: str,
) -> None:
    observations = json.loads(observations_path.read_text(encoding="utf-8"))
    _validate_sanitized(observations)
    common_fingerprints = observations.get("_configuration_fingerprints", {})
    common_evidence_ids = observations.get("_sanitized_evidence_ids", [])
    if not isinstance(common_fingerprints, dict) or not isinstance(common_evidence_ids, list):
        raise ValueError("common fingerprints and evidence IDs have invalid types")
    created_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    rendered: dict[str, dict[str, Any]] = {}
    for name in JSON_ARTIFACTS:
        document = json.loads((templates / name).read_text(encoding="utf-8"))
        overrides = observations.get(name, {})
        if not isinstance(overrides, dict):
            raise ValueError(f"artifact override must be an object: {name}")
        document.update(overrides)
        document.update(
            {
                "schema_version": "1.0",
                "created_at": created_at,
                "base_sha": base_sha,
                "head_sha": head_sha,
                "configuration_fingerprints": common_fingerprints,
                "sanitized_evidence_ids": common_evidence_ids,
            }
        )
        if name == "certification_manifest.json":
            document["result_status"] = decision
        _validate_sanitized(document)
        rendered[name] = document

    _validate_decision(decision, rendered)
    output.mkdir(parents=True, exist_ok=True)
    for name, document in rendered.items():
        (output / name).write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    limitations = observations.get("_limitations", [])
    if not isinstance(limitations, list) or not all(isinstance(item, str) for item in limitations):
        raise ValueError("limitations must be a list of strings")
    summary = observations.get("_decision_summary", "No decision summary supplied.")
    if not isinstance(summary, str):
        raise ValueError("decision summary must be a string")
    _validate_sanitized({"limitations": limitations, "summary": summary})
    (output / "limitations.md").write_text(
        "# Operational Limitations\n\n" + "".join(f"- {item}\n" for item in limitations),
        encoding="utf-8",
    )
    (output / "final_decision.md").write_text(
        f"# Final Decision\n\n`{decision}`\n\n{summary}\n", encoding="utf-8"
    )


def _validate_sanitized(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).casefold() in FORBIDDEN_KEYS:
                raise ValueError(f"forbidden certification field: {key}")
            _validate_sanitized(item)
    elif isinstance(value, list):
        for item in value:
            _validate_sanitized(item)
    elif isinstance(value, str):
        lowered = value.casefold()
        if any(marker in lowered for marker in FORBIDDEN_VALUE_MARKERS):
            raise ValueError("secret-like certification value rejected")


def _validate_decision(decision: str, documents: dict[str, dict[str, Any]]) -> None:
    if decision != "CERTIFIED":
        return
    evidence_ids = documents["certification_manifest.json"]["sanitized_evidence_ids"]
    fingerprints = documents["certification_manifest.json"]["configuration_fingerprints"]
    if not evidence_ids or not fingerprints:
        raise ValueError("CERTIFIED requires evidence IDs and configuration fingerprints")
    for artifact, requirements in CERTIFIED_EXACT_VALUES.items():
        document = documents[artifact]
        for field, expected in requirements.items():
            if document.get(field) != expected:
                raise ValueError(f"CERTIFIED evidence requirement failed: {artifact}:{field}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--templates", type=Path, required=True)
    parser.add_argument("--observations", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument(
        "--decision", choices=("CERTIFIED", "PARTIALLY_CERTIFIED", "FAILED"), required=True
    )
    args = parser.parse_args()
    render(
        args.templates,
        args.observations,
        args.output,
        base_sha=args.base_sha,
        head_sha=args.head_sha,
        decision=args.decision,
    )


if __name__ == "__main__":
    main()
