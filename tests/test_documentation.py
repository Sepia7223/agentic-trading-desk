from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
EXPECTED_DOCUMENTS = [
    "00_ENGINEERING_BLUEPRINT.md",
    "01_SYSTEM_ARCHITECTURE.md",
    "02_ROADMAP.md",
    "03_IG_INTEGRATION.md",
    "04_STRATEGY_ENGINE.md",
    "05_MATHEMATICS.md",
    "06_BACKTESTING.md",
    "07_RISK_ENGINE.md",
    "08_AI_ARCHITECTURE.md",
    "09_DEPLOYMENT.md",
    "10_DEVELOPMENT_STANDARDS.md",
    "11_ARCHITECTURAL_DECISIONS.md",
    "12_GLOSSARY.md",
    "13_TRADE_JOURNAL_AND_MEMORY.md",
]
VALIDATED_MILESTONE = 'current_validated_milestone: "2 (Milestone 3 planned)"'


def test_engineering_manual_is_complete_and_governed() -> None:
    for name in EXPECTED_DOCUMENTS:
        path = DOCS / name
        assert path.is_file(), f"missing documentation file: {name}"
        content = path.read_text(encoding="utf-8")
        assert content.startswith("---\n"), f"missing YAML front matter: {name}"
        assert "review_required_after_every_milestone: true" in content, (
            f"missing milestone review rule: {name}"
        )
        assert VALIDATED_MILESTONE in content, f"incorrect validated milestone: {name}"


def test_document_numbering_is_contiguous() -> None:
    actual_numbers = sorted(
        int(path.name[:2])
        for path in DOCS.glob("[0-9][0-9]_*.md")
        if path.name in EXPECTED_DOCUMENTS
    )
    assert actual_numbers == list(range(14))


def test_readme_links_every_engineering_document() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    linked_paths = set(re.findall(r"\((docs/[0-9]{2}_[^)]+\.md)\)", readme))
    expected_paths = {f"docs/{name}" for name in EXPECTED_DOCUMENTS}
    assert expected_paths <= linked_paths
    for relative_path in linked_paths:
        assert (ROOT / relative_path).is_file(), f"broken README link: {relative_path}"


def test_agents_requires_documentation_alignment() -> None:
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "docs/00_ENGINEERING_BLUEPRINT.md" in agents
    assert "docs/01_SYSTEM_ARCHITECTURE.md" in agents
    assert "docs/02_ROADMAP.md" in agents
    assert "docs/10_DEVELOPMENT_STANDARDS.md" in agents
    assert "docs/11_ARCHITECTURAL_DECISIONS.md" in agents
    assert (
        "A milestone is not complete until implementation, tests, architecture, "
        "and affected documentation are aligned." in agents
    )


def test_roadmap_separates_validated_planned_and_future_work() -> None:
    roadmap = (DOCS / "02_ROADMAP.md").read_text(encoding="utf-8")
    assert "| M2 | IG OAuth v3 Demo read-only integration | Complete |" in roadmap
    assert "| M3 | Regime-aware strategy engine | Planned |" in roadmap
    assert "| M3.5 | Leakage-controlled backtesting | Planned |" in roadmap
    assert "| M13 | Controlled live trading | Future |" in roadmap

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    validated = readme.split("## Current Validated Milestones", maxsplit=1)[1].split(
        "## Planned and Future Milestones", maxsplit=1
    )[0]
    assert "Milestone 2" in validated
    assert "Milestone 3" not in validated


def test_ig_document_matches_the_read_only_adapter_contract() -> None:
    integration = (DOCS / "03_IG_INTEGRATION.md").read_text(encoding="utf-8")
    required_contract = (
        "https://demo-api.ig.com/gateway/deal",
        "OAuth session v3 only",
        "`POST /session`, version 3",
        "`DELETE /session`, version 1",
        "`GET /accounts`, version 1",
        "`GET /positions`, version 2",
        "`GET /markets`, version 1",
        "`GET /markets/{epic}`, version 3",
        "`GET /prices/{epic}`, version 3",
        "All mutation and execution endpoints remain prohibited",
        "live-host support",
    )
    assert all(value in integration for value in required_contract)
    assert "https://api.ig.com" not in integration


def test_docs_do_not_claim_execution_or_runtime_ai_is_implemented() -> None:
    governed_files = [
        *(DOCS / name for name in EXPECTED_DOCUMENTS),
        ROOT / "README.md",
        ROOT / "AGENTS.md",
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in governed_files).lower()
    forbidden_claims = (
        "live trading is implemented",
        "automatic execution is implemented",
        "ai currently controls trading",
        "ai approves trades",
        "validated milestone 3",
    )
    for claim in forbidden_claims:
        assert claim not in combined
