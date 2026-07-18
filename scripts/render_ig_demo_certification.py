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
    output.mkdir(parents=True, exist_ok=True)
    created_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
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
