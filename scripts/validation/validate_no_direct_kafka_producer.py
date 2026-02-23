#!/usr/bin/env python3
"""
CI check: Kafka producer bypass CI.

Task 10 from OMN-2592:
  grep/AST check blocks `AIOKafkaProducer`, `KafkaProducer`, `confluent_kafka`
  usage outside the shared publisher implementation.

The shared publisher lives in src/omniclaude/publisher/ and src/omniclaude/lib/.
All other modules must go through the shared publisher abstraction, never
instantiating Kafka producer clients directly.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

# Forbidden direct Kafka producer symbols
FORBIDDEN_SYMBOLS: tuple[str, ...] = (
    "AIOKafkaProducer",
    "KafkaProducer",
    "confluent_kafka",
    "aiokafka",
)

# Modules that are allowed to use these symbols (the shared publisher layer)
ALLOWED_PATHS: tuple[str, ...] = (
    "publisher",
    "kafka_publisher_base",
    "kafka_producer_utils",
    "action_event_publisher",
    "embedded_publisher",
    "emit_client",
)


def is_allowed_path(path: Path) -> bool:
    """Return True if the file is part of the shared publisher layer.

    Checks only the filename and immediate parent directory name — not the full
    absolute path — so pytest temporary directories don't cause false positives.
    """
    name_lower = path.name.lower()
    parent_lower = path.parent.name.lower()
    for allowed in ALLOWED_PATHS:
        if allowed in name_lower or allowed in parent_lower:
            return True
    return False


class DirectKafkaVisitor(ast.NodeVisitor):
    def __init__(self, filepath: Path) -> None:
        self.filepath = filepath
        self.violations: list[str] = []

    def _check_name(self, name: str, lineno: int, context: str) -> None:
        for sym in FORBIDDEN_SYMBOLS:
            if sym in name:
                self.violations.append(
                    f"{self.filepath}:{lineno}: "
                    f"{context} uses direct Kafka producer symbol '{sym}'"
                )
                return

    def visit_Import(self, node: ast.Import) -> None:  # noqa: N802
        for alias in node.names:
            self._check_name(alias.name, node.lineno, f"import '{alias.name}'")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
        module = node.module or ""
        self._check_name(module, node.lineno, f"from '{module}' import")
        for alias in node.names:
            self._check_name(alias.name, node.lineno, f"imported name '{alias.name}'")
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:  # noqa: N802
        for sym in FORBIDDEN_SYMBOLS:
            if node.id == sym:
                self.violations.append(
                    f"{self.filepath}:{node.lineno}: "
                    f"direct usage of Kafka producer symbol '{sym}'"
                )
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:  # noqa: N802
        # Catch attribute access like `kafka.KafkaProducer` where the module
        # is imported as a bare name (e.g., `import kafka; kafka.KafkaProducer(...)`)
        if node.attr in FORBIDDEN_SYMBOLS:
            self.violations.append(
                f"{self.filepath}:{node.lineno}: "
                f"direct usage of Kafka producer symbol '{node.attr}' via attribute access"
            )
        self.generic_visit(node)


def check_file(filepath: Path) -> list[str]:
    try:
        source = filepath.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError as exc:
        return [f"{filepath}: SyntaxError: {exc}"]

    visitor = DirectKafkaVisitor(filepath)
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
        if is_allowed_path(py_file):
            continue
        violations = check_file(py_file)
        all_violations.extend(violations)

    if not all_violations:
        print(
            "OK: No direct Kafka producer usage found outside the shared publisher layer"
        )
        return 0

    print(f"FAIL: Found {len(all_violations)} direct Kafka producer violation(s):\n")
    for v in all_violations:
        print(f"  {v}")
    print(
        "\nDirect Kafka producer usage (AIOKafkaProducer, KafkaProducer, confluent_kafka)"
        " must only occur in the shared publisher layer"
        " (src/omniclaude/publisher/ or src/omniclaude/lib/)."
        "\nUse emit_via_daemon() or the shared publisher abstraction instead."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
