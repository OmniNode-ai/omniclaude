#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""
CI check: No direct EventBus instantiation outside of DI bootstrap.

Handlers, skills, runners, and orchestrators must receive the event bus via
DI injection or select_event_bus() — never construct EventBusInmemory or
EventBusKafka directly. Direct construction bypasses the contract-driven
bus selection layer and produces environment-split bugs (local vs. Kafka).

Checked directories:
  - src/omniclaude/  (excluding bootstrap files)
  - plugins/onex/

Allowed:
  - Files named auto_configure.py (DI bootstrap is their purpose)
  - Files named bus_bootstrap.py (explicit bootstrap factory, pending OMN-10718)
  - *_bootstrapper.py files (skill/runtime bootstrappers are bootstrap factories)
  - Test files (tests/)
  - Lines annotated with ``# bus-ok``
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

FORBIDDEN_CALL_NAMES: tuple[str, ...] = (
    "EventBusInmemory",
    "EventBusKafka",
)

CHECKED_DIRS: tuple[str, ...] = (
    "src/omniclaude",
    "plugins/onex",
)

EXCLUDED_FILENAME_PATTERNS: tuple[str, ...] = (
    "auto_configure.py",
    "bus_bootstrap.py",
    "_bootstrapper.py",
)


def _is_checked_file(path: Path, repo_root: Path) -> bool:
    """Return True if the file is in a checked directory and not excluded."""
    rel = str(path.relative_to(repo_root))
    if not any(rel.startswith(d) for d in CHECKED_DIRS):
        return False
    if any(
        path.name == pat or path.name.endswith(pat)
        for pat in EXCLUDED_FILENAME_PATTERNS
    ):
        return False
    if "/tests/" in rel or rel.startswith("tests/"):
        return False
    return True


def _call_has_annotation(source_lines: list[str], node: ast.Call) -> bool:
    """Check if the call site has a # bus-ok annotation.

    Checks the call's opening line, closing line (end_lineno), and the line
    immediately preceding the call — this handles ruff-reformatted multi-line
    calls where the trailing ) lands on a different line from the function name.
    """
    candidates = {node.lineno}
    if hasattr(node, "end_lineno") and node.end_lineno:
        candidates.add(node.end_lineno)
    candidates.add(node.lineno - 1)
    for lineno in candidates:
        if 0 < lineno <= len(source_lines) and "# bus-ok" in source_lines[lineno - 1]:
            return True
    return False


class BusInstantiationVisitor(ast.NodeVisitor):
    def __init__(self, filepath: Path, source_lines: list[str]) -> None:
        self.filepath = filepath
        self.source_lines = source_lines
        self.violations: list[str] = []
        self._forbidden_aliases: set[str] = set(FORBIDDEN_CALL_NAMES)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
        for alias in node.names:
            if alias.name in FORBIDDEN_CALL_NAMES:
                self._forbidden_aliases.add(alias.asname or alias.name)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        matched_name = None
        if isinstance(node.func, ast.Name):
            if node.func.id in self._forbidden_aliases:
                matched_name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            if node.func.attr in FORBIDDEN_CALL_NAMES:
                matched_name = node.func.attr

        if matched_name is not None:
            if not _call_has_annotation(self.source_lines, node):
                self.violations.append(
                    f"{self.filepath}:{node.lineno}: direct {matched_name}() construction — "
                    f"bus must come from DI container or select_event_bus(). "
                    f"Add '# bus-ok: <reason>' to suppress for legitimate bootstrap sites."
                )
        self.generic_visit(node)


def check_file(filepath: Path) -> list[str]:
    try:
        source = filepath.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError as exc:
        return [f"{filepath}: SyntaxError: {exc}"]

    source_lines = source.splitlines()
    visitor = BusInstantiationVisitor(filepath, source_lines)
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
            "OK: No direct EventBus instantiation found outside DI bootstrap "
            "(src/omniclaude, plugins/onex)"
        )
        return 0

    print(
        f"FAIL: Found {len(all_violations)} direct EventBus instantiation(s) "
        f"outside DI bootstrap:\n"
    )
    for v in all_violations:
        print(f"  {v}")
    print(
        "\nHandlers, skills, and runners must not construct EventBus directly."
        "\nUse DI injection or select_event_bus() instead."
        "\nAdd '# bus-ok: <reason>' to suppress for legitimate bootstrap sites."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
