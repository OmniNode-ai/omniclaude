#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""
CI check: No raw sqlite3.connect() calls outside adapter definitions.

Handlers, skills, orchestrators, and service modules must access SQLite
through an injected adapter — never call sqlite3.connect() directly. Direct
connections bypass the adapter abstraction, making code untestable and
coupling business logic to storage implementation details.

Checked directories:
  - src/omniclaude/  (excluding adapter definitions)
  - plugins/onex/   (excluding adapter definitions)

Allowed:
  - *_adapter.py files (adapter definitions are the authorised call site)
  - Test files (tests/)
  - Lines annotated with ``# di-ok``
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

FORBIDDEN_CALL: str = "connect"
FORBIDDEN_MODULE: str = "sqlite3"

CHECKED_DIRS: tuple[str, ...] = (
    "src/omniclaude",
    "plugins/onex",
)

EXCLUDED_FILENAME_PATTERNS: tuple[str, ...] = ("_adapter.py",)


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


def _call_has_annotation(source_lines: list[str], node: ast.Call) -> bool:
    """Check if the call site has a # di-ok annotation.

    Checks the call's opening line, closing line (end_lineno), and the line
    immediately preceding the call — this handles ruff-reformatted multi-line
    calls where the trailing ) lands on a different line from the function name.
    """
    candidates = {node.lineno}
    if hasattr(node, "end_lineno") and node.end_lineno:
        candidates.add(node.end_lineno)
    candidates.add(node.lineno - 1)
    for lineno in candidates:
        if 0 < lineno <= len(source_lines) and "# di-ok" in source_lines[lineno - 1]:
            return True
    return False


class RawSqlite3Visitor(ast.NodeVisitor):
    """Detect sqlite3.connect() calls outside authorised adapter files."""

    def __init__(self, filepath: Path, source_lines: list[str]) -> None:
        self.filepath = filepath
        self.source_lines = source_lines
        self.violations: list[str] = []
        self._sqlite3_aliases: set[str] = set()
        self._sqlite3_connect_aliases: set[str] = set()

    def visit_Import(self, node: ast.Import) -> None:  # noqa: N802
        for alias in node.names:
            if alias.name == FORBIDDEN_MODULE:
                self._sqlite3_aliases.add(alias.asname or alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
        if node.module == FORBIDDEN_MODULE:
            for alias in node.names:
                if alias.name == FORBIDDEN_CALL:
                    self._sqlite3_connect_aliases.add(alias.asname or alias.name)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        matched = False

        # sqlite3.connect(...)
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == FORBIDDEN_CALL
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in self._sqlite3_aliases
        ):
            matched = True

        # from sqlite3 import connect [as alias]; connect(...) / alias(...)
        if (
            isinstance(node.func, ast.Name)
            and node.func.id in self._sqlite3_connect_aliases
        ):
            matched = True

        if matched and not _call_has_annotation(self.source_lines, node):
            self.violations.append(
                f"{self.filepath}:{node.lineno}: raw sqlite3.connect() call — "
                f"database access must go through an injected adapter, not a direct connection. "
                f"Add '# di-ok' to suppress for legitimate adapter bootstrap."
            )

        self.generic_visit(node)


def check_file(filepath: Path) -> list[str]:
    try:
        source = filepath.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError as exc:
        return [f"{filepath}: SyntaxError: {exc}"]

    source_lines = source.splitlines()
    visitor = RawSqlite3Visitor(filepath, source_lines)
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
            "OK: No raw sqlite3.connect() calls found outside adapter definitions "
            "(src/omniclaude, plugins/onex)"
        )
        return 0

    print(
        f"FAIL: Found {len(all_violations)} raw sqlite3.connect() call(s) "
        f"outside adapter definitions:\n"
    )
    for v in all_violations:
        print(f"  {v}")
    print(
        "\nOnly *_adapter.py files may call sqlite3.connect() directly."
        "\nOther code must receive a database adapter via DI injection."
        "\nAdd '# di-ok' to suppress for legitimate adapter bootstrap."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
