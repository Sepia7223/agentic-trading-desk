from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).parents[1]
DOCS = tuple(
    f"docs/{index:02d}_{name}.md"
    for index, name in enumerate(
        (
            "ENGINEERING_BLUEPRINT",
            "SYSTEM_ARCHITECTURE",
            "ROADMAP",
            "IG_INTEGRATION",
            "STRATEGY_ENGINE",
            "MATHEMATICS",
            "BACKTESTING",
            "RISK_ENGINE",
            "AI_ARCHITECTURE",
            "DEPLOYMENT",
            "DEVELOPMENT_STANDARDS",
            "ARCHITECTURAL_DECISIONS",
            "GLOSSARY",
            "TRADE_JOURNAL_AND_MEMORY",
        )
    )
)


def test_numbered_document_set_is_complete_and_has_governed_front_matter() -> None:
    assert tuple(path for path in DOCS if (ROOT / path).is_file()) == DOCS
    assert tuple(int(Path(path).name[:2]) for path in DOCS) == tuple(range(14))
    for relative_path in DOCS:
        content = (ROOT / relative_path).read_text(encoding="utf-8")
        assert content.startswith("---\n")
        assert "\n---\n" in content[4:]
        assert "review_required_after_every_milestone: true" in content


def test_readme_documentation_index_is_complete_ordered_and_resolves() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    section = readme.split("## Project Documentation", maxsplit=1)[1].split("\n## ", maxsplit=1)[0]
    links = tuple(re.findall(r"\((docs/\d{2}_[^)]+\.md)\)", section))
    assert links == DOCS
    assert all((ROOT / link).is_file() for link in links)


def test_documents_do_not_claim_current_execution_live_trading_or_ai_control() -> None:
    corpus = "\n".join((ROOT / path).read_text(encoding="utf-8") for path in DOCS).lower()
    prohibited_claims = (
        r"(?:currently|current implementation|validated).*live trading is implemented",
        r"(?:currently|current implementation|validated).*order execution is implemented",
        r"ai currently controls trad",
        r"(?<!no )ai controls trading decisions",
    )
    assert all(re.search(pattern, corpus) is None for pattern in prohibited_claims)


def test_governed_documents_identify_milestone_11_as_current() -> None:
    for relative_path in DOCS:
        content = (ROOT / relative_path).read_text(encoding="utf-8")
        assert re.search(r'current_validated_milestone: ["\']?11', content), relative_path


def test_milestone_9_documents_read_only_operations_boundary() -> None:
    corpus = "\n".join(
        (ROOT / path).read_text(encoding="utf-8").lower()
        for path in (*DOCS, "README.md", "AGENTS.md")
    )
    assert "operations center" in corpus
    assert "loopback" in corpus
    assert "dashboard authority: read only" in corpus
    assert "replay mode - no operational authority" in corpus


def test_milestone_8_documentation_preserves_authority_boundaries() -> None:
    journal = (ROOT / "docs/13_TRADE_JOURNAL_AND_MEMORY.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    corpus = "\n".join((journal, readme, agents)).lower()
    assert "durable sqlite" in corpus
    assert "hard deletion" in corpus
    assert "read-only" in corpus
    assert "semantic vector search" in corpus
    assert "journal cannot call a broker" in corpus or "broker access: disabled" in corpus
    assert "autonomous strategy" in corpus


def test_milestone_7_5_is_documented_with_research_isolation() -> None:
    for relative_path in DOCS:
        content = (ROOT / relative_path).read_text(encoding="utf-8").lower()
        assert "milestone 7.5" in content, relative_path
    corpus = "\n".join(
        (ROOT / path).read_text(encoding="utf-8").lower()
        for path in (*DOCS, "README.md", "AGENTS.md")
    )
    assert "research_only" in corpus or "research only" in corpus
    assert "capital preservation" in corpus
    assert "ai strategy selection" in corpus or "ai-selected strategies" in corpus


def test_operational_certification_templates_are_complete_and_sanitized() -> None:
    root = ROOT / "artifacts" / "ig_demo_certification" / "templates"
    json_names = (
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
    assert all(
        (root / name).is_file() for name in (*json_names, "limitations.md", "final_decision.md")
    )
    forbidden_keys = {
        "password",
        "api_key",
        "access_token",
        "refresh_token",
        "authorization",
        "raw_response",
        "raw_headers",
        "account_id",
    }
    for name in json_names:
        document = json.loads((root / name).read_text(encoding="utf-8"))
        assert {
            "schema_version",
            "created_at",
            "base_sha",
            "head_sha",
            "configuration_fingerprints",
            "sanitized_evidence_ids",
            "result_status",
        } <= document.keys()
        assert forbidden_keys.isdisjoint(document.keys())
