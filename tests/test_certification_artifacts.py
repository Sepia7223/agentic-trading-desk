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
