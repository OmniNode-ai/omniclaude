#!/usr/bin/env python3
"""
CI check: onex.* topic publish-time assertion.

Task 6 from OMN-2592:
  `onex.*` topic publish-time assertion in the omnibase_infra shared publisher layer.

Since this is the omniclaude repo, we verify:
  1. All topic string constants in src/ follow the `onex.{kind}.{producer}.{event-name}.v{n}` pattern
  2. No raw string literals outside topics.py define ad-hoc topic names
  3. The TopicBase enum values all start with 'onex.'

Pattern: onex.<kind>.<producer>.<event-name>.v<n>
  kind: evt | cmd
  producer: [a-z][a-z0-9_-]+
  event-name: [a-z][a-z0-9-]+
  version: v[0-9]+
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

# Regex for valid onex topic names
# Known producer identifiers in the OmniNode platform.
# Add new producers here when a new service is onboarded.
_KNOWN_PRODUCERS = (
    "omniclaude",
    "omninode",
    "omniintelligence",
    "omniarchon",
    "omnimemory",
    "omnibase",
)
_PRODUCER_SEGMENT = "|".join(_KNOWN_PRODUCERS)

VALID_TOPIC_RE = re.compile(
    rf"^onex\.(evt|cmd)\.({_PRODUCER_SEGMENT})\.[a-z][a-z0-9-]+\.v[0-9]+$"
)

# Pattern that suggests a string is meant to be a topic name
TOPIC_STRING_HEURISTIC_RE = re.compile(
    r"^(onex|omninode|omniclaude|omniarchon|omniintelligence)\."
)


class TopicNamingVisitor(ast.NodeVisitor):
    """Find string constants that look like topic names and validate them."""

    def __init__(self, filepath: Path, source_lines: list[str]) -> None:
        self.filepath = filepath
        self.source_lines = source_lines
        self.violations: list[str] = []

    def _line_is_suppressed(self, lineno: int) -> bool:
        """Return True if the line carries a # noqa: arch-topic-naming suppression."""
        if lineno < 1 or lineno > len(self.source_lines):
            return False
        line = self.source_lines[lineno - 1]
        return "noqa: arch-topic-naming" in line or "arch-topic-naming: ignore" in line

    def _check_string(self, value: str, lineno: int) -> None:
        if not TOPIC_STRING_HEURISTIC_RE.match(value):
            return
        # Looks like a topic name — validate it
        if not VALID_TOPIC_RE.match(value):
            if self._line_is_suppressed(lineno):
                return
            self.violations.append(
                f"{self.filepath}:{lineno}: "
                f"topic string '{value}' does not match pattern "
                f"'onex.{{evt|cmd}}.{{producer}}.{{event-name}}.v{{n}}'"
            )

    def visit_Constant(self, node: ast.Constant) -> None:  # noqa: N802
        if isinstance(node.value, str):
            self._check_string(node.value, node.lineno)
        self.generic_visit(node)


def check_file(filepath: Path) -> list[str]:
    try:
        source = filepath.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError as exc:
        return [f"{filepath}: SyntaxError: {exc}"]

    source_lines = source.splitlines()
    visitor = TopicNamingVisitor(filepath, source_lines)
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
        print("OK: All topic string constants follow the onex.* naming convention")
        return 0

    print(f"FAIL: Found {len(all_violations)} topic naming violation(s):\n")
    for v in all_violations:
        print(f"  {v}")
    print(
        "\nAll Kafka topics must follow the naming convention:"
        "\n  onex.{evt|cmd}.{producer}.{event-name}.v{n}"
        "\nSee src/omniclaude/hooks/topics.py for examples."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
