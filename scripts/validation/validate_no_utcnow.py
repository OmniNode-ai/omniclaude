#!/usr/bin/env python3
"""
CI check: Clock-skew CI.

Task 11 from OMN-2592:
  grep for `datetime.utcnow` in effect/orchestrator code -> zero matches

`datetime.utcnow()` produces timezone-naive datetimes, which cause clock-skew
bugs when compared to timezone-aware datetimes from Kafka or PostgreSQL.

All timestamp creation must use `datetime.now(tz=timezone.utc)` or
`datetime.now(UTC)`.

This check applies to ALL Python files in src/ (not just effects/orchestrators)
because naive timestamps are dangerous anywhere.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path


class UtcNowVisitor(ast.NodeVisitor):
    """Detect datetime.utcnow() and datetime.utcnow calls."""

    def __init__(self, filepath: Path) -> None:
        self.filepath = filepath
        self.violations: list[str] = []

    def visit_Attribute(self, node: ast.Attribute) -> None:  # noqa: N802
        # Detect: datetime.utcnow or datetime.datetime.utcnow
        if node.attr == "utcnow":
            # Provide context
            if isinstance(node.value, ast.Name) and node.value.id in (
                "datetime",
                "dt",
            ):
                self.violations.append(
                    f"{self.filepath}:{node.lineno}: "
                    f"use of {node.value.id}.utcnow() — use datetime.now(tz=timezone.utc) instead"
                )
            elif (
                isinstance(node.value, ast.Attribute) and node.value.attr == "datetime"
            ):
                self.violations.append(
                    f"{self.filepath}:{node.lineno}: "
                    f"use of datetime.datetime.utcnow() — "
                    f"use datetime.datetime.now(tz=timezone.utc) instead"
                )
            else:
                self.violations.append(
                    f"{self.filepath}:{node.lineno}: "
                    f"use of .utcnow() — use .now(tz=timezone.utc) instead"
                )
        self.generic_visit(node)


def check_file(filepath: Path) -> list[str]:
    try:
        source = filepath.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError as exc:
        return [f"{filepath}: SyntaxError: {exc}"]

    visitor = UtcNowVisitor(filepath)
    visitor.visit(tree)
    return visitor.violations


def main() -> int:
    root = Path(__file__).resolve()
    for _ in range(10):
        if (root / "pyproject.toml").exists() or (root / "src").exists():
            break
        root = root.parent

    src_root = root / "src"
    if not src_root.exists():
        print(f"WARNING: src/ not found under {root}; skipping")
        return 0

    all_violations: list[str] = []

    for py_file in sorted(src_root.rglob("*.py")):
        violations = check_file(py_file)
        all_violations.extend(violations)

    if not all_violations:
        print("OK: No datetime.utcnow() usage found")
        return 0

    print(f"FAIL: Found {len(all_violations)} utcnow() violation(s):\n")
    for v in all_violations:
        print(f"  {v}")
    print(
        "\ndatetime.utcnow() produces timezone-naive datetimes and must not be used."
        "\nReplace with: datetime.now(tz=timezone.utc)  or  datetime.now(UTC)"
        "\nSee CLAUDE.md repository invariant: 'emitted_at timestamps must be explicitly injected'"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
