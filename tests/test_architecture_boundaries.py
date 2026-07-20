"""Milestone 18: automated architecture and dependency-direction enforcement.

These tests parse every module under ``src/trading_desk`` and assert the
structural rules that keep the desk maintainable as a release candidate:

- No domain reaches into another domain's private (underscore) helpers; cross-
  domain use must go through public contracts.
- The low-level fingerprint/canonical utility layer never imports a high-level
  domain, so the dependency direction cannot invert.
- The canonical library's only intra-project imports are the three legacy
  fingerprint leaf modules it deliberately delegates to.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1] / "src" / "trading_desk"


def _modules() -> Iterator[tuple[Path, str, ast.Module]]:
    for path in SRC_ROOT.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        relative = path.relative_to(SRC_ROOT).parts
        domain = relative[0][:-3] if len(relative) == 1 else relative[0]
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        yield path, domain, tree


def _imported_from(tree: ast.Module) -> Iterator[tuple[str, tuple[str, ...]]]:
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ImportFrom)
            and node.level == 0
            and node.module
            and node.module.startswith("trading_desk")
        ):
            yield node.module, tuple(alias.name for alias in node.names)


def test_no_cross_domain_private_helper_imports() -> None:
    violations: list[str] = []
    for path, domain, tree in _modules():
        for module, names in _imported_from(tree):
            parts = module.split(".")
            if len(parts) < 2:
                continue
            target_domain = parts[1]
            if target_domain == domain:
                continue
            for name in names:
                if name.startswith("_") and not name.startswith("__"):
                    rel = path.relative_to(SRC_ROOT.parent.parent)
                    violations.append(f"{rel}: from {module} import {name}")
    assert not violations, "cross-domain private imports must use public contracts: " + "; ".join(
        violations
    )


def test_utility_layer_only_imports_other_utilities() -> None:
    # The fingerprint/canonical layer sits at the bottom: its only intra-project
    # imports may be other fingerprint leaves or the canonical library. Importing
    # any higher-level domain module would invert the dependency direction.
    violations: list[str] = []
    for path, domain, tree in _modules():
        is_utility = domain == "canonical" or path.name == "fingerprints.py"
        if not is_utility:
            continue
        for module, _ in _imported_from(tree):
            if module.endswith(".fingerprints") or module.startswith("trading_desk.canonical"):
                continue
            rel = path.relative_to(SRC_ROOT.parent.parent)
            violations.append(f"{rel}: imports {module}")
    assert not violations, "utility layer must only import other utilities: " + "; ".join(
        violations
    )


def test_canonical_only_delegates_to_legacy_fingerprint_leaves() -> None:
    allowed = {
        "trading_desk.context.fingerprints",
        "trading_desk.journal.fingerprints",
        "trading_desk.risk.fingerprints",
        "trading_desk.canonical.fingerprints",
    }
    violations: list[str] = []
    for path, domain, tree in _modules():
        if domain != "canonical":
            continue
        for module, _ in _imported_from(tree):
            if module not in allowed:
                rel = path.relative_to(SRC_ROOT.parent.parent)
                violations.append(f"{rel}: imports {module}")
    assert not violations, "canonical may only delegate to legacy fingerprint leaves: " + "; ".join(
        violations
    )


def test_every_module_parses_and_domains_are_discoverable() -> None:
    domains = {domain for _, domain, _ in _modules()}
    # Sanity: the packages this milestone touches are present and scanned.
    assert {"canonical", "analytics", "resilience", "allocation"} <= domains
