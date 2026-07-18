"""Machine-readable, fingerprinted strategy-validation artifact packages."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from trading_desk.context.fingerprints import fingerprint

REQUIRED_ARTIFACT_FILES = (
    "manifest.json",
    "configuration.json",
    "dataset_manifest.json",
    "development_results.json",
    "validation_results.json",
    "final_test_results.json",
    "walk_forward_results.json",
    "cost_stress_results.json",
    "robustness_results.json",
    "portfolio_results.json",
    "promotion_decision.json",
    "summary.md",
)


class ValidationArtifactManifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    artifact_id: str = Field(min_length=64, max_length=64)
    strategy_id: str
    strategy_version: str
    created_at: datetime
    dataset_fingerprint: str = Field(min_length=64, max_length=64)
    configuration_fingerprint: str = Field(min_length=64, max_length=64)
    files: tuple[tuple[str, str], ...]
    complete: bool

    @model_validator(mode="after")
    def identity(self) -> Self:
        names = {name for name, _ in self.files}
        if self.complete and names != set(REQUIRED_ARTIFACT_FILES) - {"manifest.json"}:
            raise ValueError("complete validation artifact has missing or extra files")
        if self.artifact_id != fingerprint(self.model_dump(mode="python", exclude={"artifact_id"})):
            raise ValueError("validation artifact fingerprint mismatch")
        return self


def build_artifact_package(
    directory: Path,
    *,
    strategy_id: str,
    strategy_version: str,
    dataset_fingerprint: str,
    configuration_fingerprint: str,
    documents: dict[str, object],
    created_at: datetime,
) -> ValidationArtifactManifest:
    if created_at.tzinfo is None or created_at.utcoffset() != UTC.utcoffset(created_at):
        raise ValueError("artifact timestamp must be UTC")
    expected = set(REQUIRED_ARTIFACT_FILES) - {"manifest.json"}
    if set(documents) != expected:
        raise ValueError("artifact package must be complete before it can be sealed")
    directory.mkdir(parents=True, exist_ok=True)
    file_fingerprints: list[tuple[str, str]] = []
    for name in sorted(expected):
        value = documents[name]
        content = (
            str(value)
            if name.endswith(".md")
            else json.dumps(value, sort_keys=True, indent=2, default=str, allow_nan=False)
        )
        (directory / name).write_text(content.rstrip() + "\n", encoding="utf-8")
        file_fingerprints.append((name, fingerprint(content.rstrip() + "\n")))
    fields = {
        "strategy_id": strategy_id,
        "strategy_version": strategy_version,
        "created_at": created_at,
        "dataset_fingerprint": dataset_fingerprint,
        "configuration_fingerprint": configuration_fingerprint,
        "files": tuple(file_fingerprints),
        "complete": True,
    }
    manifest = ValidationArtifactManifest.model_validate(
        {**fields, "artifact_id": fingerprint(fields)}
    )
    (directory / "manifest.json").write_text(
        manifest.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def verify_artifact_package(directory: Path) -> ValidationArtifactManifest:
    manifest = ValidationArtifactManifest.model_validate_json(
        (directory / "manifest.json").read_text(encoding="utf-8")
    )
    for name, expected in manifest.files:
        path = directory / name
        if not path.is_file() or fingerprint(path.read_text(encoding="utf-8")) != expected:
            raise ValueError(f"validation artifact failed integrity verification: {name}")
    return manifest
