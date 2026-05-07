#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""
CI check: No direct persistence adapter imports in business logic.

Runners, skills, and handler modules must receive adapters via DI — never
construct them directly.  This validator catches the pattern that produced
PR #1535 (DelegationRunner manually importing and instantiating
SQLiteProjectionAdapter, bypassing the projection pipeline).

Checked directories:
  - src/omniclaude/delegation/  (excluding adapter definitions)
  - plugins/onex/skills/

Allowed:
  - *_adapter.py files (adapter definitions themselves)
  - test files (tests/)
  - Lines annotated with ``# di-ok``
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

FORBIDDEN_IMPORT_PATTERNS: tuple[str, ...] = (
    "sqlite_adapter",
    "SQLiteProjectionAdapter",
    "postgres_adapter",
    "PostgresAdapter",
    "db_adapter",
    "DatabaseAdapter",
)

CHECKED_DIRS: tuple[str, ...] = (
    "src/omniclaude/delegation",
    "plugins/onex/skills",
)

EXCLUDED_FILENAME_PATTERNS: tuple[str, ...] = (
    "_adapter.py",
    "_adapter_test.py",
    "conftest.py",
)


def _is_checked_file(path: Path, repo_root: Path) -> bool:
    """Return True if the file is in a checked directory and not excluded."""
    rel = str(path.relative_to(repo_root))
    if not any(rel.startswith(d) for d in CHECKED_DIRS):
        return False
    if any(path.name.endswith(pat) for pat in EXCLUDED_FILENAME_PATTERNS):
        return False
    if "/tests/" in rel or rel.startswith("tests/"):
        return False
    return True


def _line_has_annotation(source_lines: list[str], lineno: int) -> bool:
    """Check if the source line has a # di-ok annotation."""
    if 0 < lineno <= len(source_lines):
        return "# di-ok" in source_lines[lineno - 1]
    return False


class AdapterImportVisitor(ast.NodeVisitor):
    def __init__(self, filepath: Path, source_lines: list[str]) -> None:
        self.filepath = filepath
        self.source_lines = source_lines
        self.violations: list[str] = []

    def _check(self, name: str, lineno: int, context: str) -> None:
        if _line_has_annotation(self.source_lines, lineno):
            return
        lower = name.lower()
        for pattern in FORBIDDEN_IMPORT_PATTERNS:
            if pattern.lower() in lower:
                self.violations.append(
                    f"{self.filepath}:{lineno}: {context} imports '{name}' — "
                    f"persistence adapters must be injected via DI, not imported directly. "
                    f"Add '# di-ok' to suppress if this is a legitimate DI bootstrap."
                )
                return

    def visit_Import(self, node: ast.Import) -> None:  # noqa: N802
        for alias in node.names:
            self._check(alias.name, node.lineno, "import")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
        module = node.module or ""
        self._check(module, node.lineno, "from-import module")
        for alias in node.names:
            self._check(alias.name, node.lineno, "from-import name")
        self.generic_visit(node)


def check_file(filepath: Path) -> list[str]:
    try:
        source = filepath.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError as exc:
        return [f"{filepath}: SyntaxError: {exc}"]

    source_lines = source.splitlines()
    visitor = AdapterImportVisitor(filepath, source_lines)
    visitor.visit(tree)
    return visitor.violations


def main() -> int:
    root = Path(__file__).resolve()
    for _ in range(10):
        if (root / "pyproject.toml").exists() or (root / "src").exists():
            break
        root = root.parent

    all_violations: list[str] = []

    for py_file in sorted(root.rglob("*.py")):
        if "__pycache__" in str(py_file):
            continue
        if not _is_checked_file(py_file, root):
            continue
        violations = check_file(py_file)
        all_violations.extend(violations)

    if not all_violations:
        print(
            "OK: No direct adapter imports found in business logic "
            "(delegation runners, skills)"
        )
        return 0

    print(
        f"FAIL: Found {len(all_violations)} direct adapter import(s) "
        f"in business logic:\n"
    )
    for v in all_violations:
        print(f"  {v}")
    print(
        "\nBusiness logic (runners, skills) must not import persistence adapters."
        "\nAdapters should be injected via the DI container / event bus."
        "\nUse '# di-ok' annotation for legitimate DI bootstrap imports."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
