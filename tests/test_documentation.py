from __future__ import annotations

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
