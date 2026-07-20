"""Milestone 16 CI gates: secret scan and repository cleanliness.

These checks fail CI if a credential-like literal, a committed environment file,
or a temporary build artifact reaches the tree. They inspect only git-tracked
files so gitignored scratch (pytest temp dirs, caches) never causes a false
positive. Test fixtures deliberately use obviously fake values (``hunter2``,
``dummy``); the secret patterns target real credential shapes, not placeholders.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

_TEXT_SUFFIXES = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".json",
    ".toml",
    ".md",
    ".yml",
    ".yaml",
    ".cfg",
    ".ini",
    ".txt",
}

# Real credential shapes, not test placeholders.
_SECRET_PATTERNS = (
    re.compile(r"aws_secret_access_key\s*=\s*['\"][A-Za-z0-9/+]{40}['\"]", re.IGNORECASE),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"ghp_[A-Za-z0-9]{36}"),
    re.compile(r"sk-[A-Za-z0-9]{32,}"),
)
_ENV_ASSIGNMENT = re.compile(
    r"^\s*(IG_PASSWORD|IG_API_KEY|IG_IDENTIFIER|OANDA_TOKEN)\s*=\s*\S+", re.MULTILINE
)


def _tracked_files() -> list[Path]:
    try:
        output = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=REPO_ROOT,
            capture_output=True,
            check=True,
            text=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("git is unavailable; repository hygiene scan requires a git checkout")
    return [REPO_ROOT / name for name in output.split("\0") if name]


def test_no_credential_like_literals_are_committed() -> None:
    offenders: list[str] = []
    for path in _tracked_files():
        if path.suffix.lower() not in _TEXT_SUFFIXES:
            continue
        if path.name == "test_repository_hygiene.py":
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for pattern in _SECRET_PATTERNS:
            if pattern.search(content):
                offenders.append(f"{path.relative_to(REPO_ROOT)} :: {pattern.pattern}")
        if _ENV_ASSIGNMENT.search(content):
            offenders.append(f"{path.relative_to(REPO_ROOT)} :: populated credential assignment")
    assert not offenders, "credential-like content committed: " + "; ".join(offenders)


def test_no_environment_files_are_committed() -> None:
    committed_env = [
        path.relative_to(REPO_ROOT).as_posix()
        for path in _tracked_files()
        if path.name.startswith(".env")
        and not path.name.endswith((".example", ".template", ".sample"))
    ]
    assert not committed_env, f"environment files must not be committed: {committed_env}"


def test_no_temporary_or_backup_artifacts_are_committed() -> None:
    bad_suffixes = (".tmp", ".corrupt", ".pyc", ".pyo", ".orig", ".rej", ".bak")
    offenders = [
        path.relative_to(REPO_ROOT).as_posix()
        for path in _tracked_files()
        if path.name.endswith(bad_suffixes) or "__pycache__" in path.parts
    ]
    assert not offenders, f"temporary artifacts must not be committed: {offenders}"


def test_disaster_recovery_runbooks_exist() -> None:
    runbooks = REPO_ROOT / "docs" / "runbooks"
    required = {
        "disaster-recovery.md",
        "laptop-to-minipc-migration.md",
        "release-rollback.md",
    }
    present = {path.name for path in runbooks.glob("*.md")} if runbooks.is_dir() else set()
    assert required <= present, f"missing runbooks: {sorted(required - present)}"
