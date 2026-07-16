from __future__ import annotations

import inspect
import re
from pathlib import Path

from trading_desk import cli
from trading_desk.journal.reader import ReadOnlyJournal
from trading_desk.journal.sqlite import SQLiteJournalRepository

ROOT = Path(__file__).parents[1]


def test_journal_cli_initializes_and_verifies_without_broker_configuration(
    tmp_path: Path, capsys
) -> None:  # type: ignore[no-untyped-def]
    database = tmp_path / "journal.db"
    assert cli.main(["journal", "init", "--database", str(database)]) == 0
    output = capsys.readouterr().out
    assert "Mode: JOURNAL" in output
    assert "Trading authority: NONE" in output
    assert "Broker access: DISABLED" in output
    assert "Mutation of source records: DISABLED" in output
    assert "Live trading: DISABLED" in output
    assert cli.main(["journal", "verify", "--database", str(database)]) == 0


def test_repository_has_no_update_or_delete_surface() -> None:
    methods = {
        name
        for name, member in inspect.getmembers(SQLiteJournalRepository, inspect.isfunction)
        if not name.startswith("_")
    }
    assert "update" not in methods
    assert "delete" not in methods
    assert "execute" not in methods


def test_ai_read_only_journal_has_no_mutation_surface() -> None:
    methods = {
        name
        for name, member in inspect.getmembers(ReadOnlyJournal, inspect.isfunction)
        if not name.startswith("_")
    }
    assert methods == {"get", "lineage", "query"}


def test_journal_package_has_no_broker_credential_or_execution_dependencies() -> None:
    forbidden_imports = (
        "trading_desk.ig",
        "trading_desk.execution",
        "IG_IDENTIFIER",
        "IG_PASSWORD",
        "IG_API_KEY",
    )
    for path in (ROOT / "src/trading_desk/journal").glob("*.py"):
        content = path.read_text(encoding="utf-8")
        assert all(item not in content for item in forbidden_imports), path


def test_no_hard_delete_sql_or_source_mutation_sql_exists() -> None:
    corpus = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "src/trading_desk/journal").glob("*.py")
    ).upper()
    assert "DELETE FROM JOURNAL_RECORDS" not in corpus
    assert "UPDATE JOURNAL_RECORDS SET PAYLOAD" not in corpus


def test_env_is_not_referenced_by_journal_package() -> None:
    corpus = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "src/trading_desk/journal").glob("*.py")
    )
    assert re.search(r"(?:open|read_text|Path)\([^\n]*[\"']\.env[\"']", corpus) is None
