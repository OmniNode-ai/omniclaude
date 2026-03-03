#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""
CI check: Block hardcoded Kafka broker URL fallbacks. (OMN-3555)

Root cause of the OMN-3534 bus split: code had stale fallback addresses like
  os.getenv("KAFKA_BROKERS", "localhost:29092")
When the M2 Ultra Redpanda was decommissioned (OMN-3431), omnidash silently
defaulted to the old cloud bus address instead of the local Docker bus.

This check flags broker port literals (:29092, :19092) that appear as:
  - Default/fallback values in os.getenv() calls
  - Standalone string assignments where the LHS name contains "broker", "kafka", or "bootstrap"
  - Any string that looks like a broker address (host:port) containing these ports

Suppression:
  - Add comment `# onex-allow-kafka-broker` on the flagged line to suppress
  - Canonical broker config modules (kafka_config.py, etc.) are suppressed by filename
  - Test files (tests/*, *_test.py, test_*.py) are excluded
  - .env.example, env-example-*.txt, docs/, CLAUDE.md are excluded

Two-bus policy (OMN-3431):
  localhost:19092  — local Docker Redpanda (bus_local, always-on)
  localhost:29092  — cloud Kafka via launchd tunnel (bus_cloud, session-scoped)

Neither should appear hardcoded as a fallback in source code. Broker addresses
must always come from environment variables (KAFKA_BOOTSTRAP_SERVERS or equivalent).
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

# Broker ports that must not appear as hardcoded fallbacks
BROKER_PORT_PATTERN = re.compile(r":\b(19092|29092)\b")

# Pattern to detect broker-related variable names on the LHS of assignments
BROKER_VAR_PATTERN = re.compile(r"(kafka|broker|bootstrap)", re.IGNORECASE)

# Suppression marker
SUPPRESS_MARKER = "onex-allow-kafka-broker"

# Canonical modules that legitimately define broker defaults (excluded by filename)
ALLOWED_FILENAMES: frozenset[str] = frozenset(
    {
        "kafka_config.py",
        "kafka_broker_config.py",
        "test_kafka_config.py",
    }
)

# Directories to exclude entirely
EXCLUDED_DIRS: tuple[str, ...] = (
    "tests",
    ".git",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
)


def is_excluded_path(path: Path) -> bool:
    """Return True if the path should be excluded from checks."""
    # Exclude by filename
    if path.name in ALLOWED_FILENAMES:
        return True
    # Exclude test files
    name = path.name
    if name.startswith("test_") or name.endswith("_test.py"):
        return True
    # Exclude env-example files
    if "env-example" in name or name.endswith(".env.example"):
        return True
    # Exclude directories
    parts = set(path.parts)
    return bool(parts & set(EXCLUDED_DIRS))


def has_suppress_marker(source_lines: list[str], lineno: int) -> bool:
    """Return True if the line at lineno (1-based) contains the suppress marker."""
    idx = lineno - 1
    if 0 <= idx < len(source_lines):
        return SUPPRESS_MARKER in source_lines[idx]
    return False


class BrokerFallbackVisitor(ast.NodeVisitor):
    """Detect hardcoded broker port literals as os.getenv fallback values.

    Flags:
      1. os.getenv("KEY", "...:<port>...") — broker port as getenv default
      2. os.environ.get("KEY", "...:<port>...") — same pattern via environ.get
      3. var = "...:<port>..." where var name matches BROKER_VAR_PATTERN
    """

    def __init__(self, filepath: Path, source_lines: list[str]) -> None:
        self.filepath = filepath
        self.source_lines = source_lines
        self.violations: list[str] = []

    def _is_broker_literal(self, node: ast.expr) -> bool:
        """Return True if node is a string literal containing a broker port."""
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            return False
        return bool(BROKER_PORT_PATTERN.search(node.value))

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        """Detect os.getenv("KEY", "<broker>") and os.environ.get("KEY", "<broker>")."""
        is_getenv = False
        is_environ_get = False

        if isinstance(node.func, ast.Attribute):
            attr = node.func.attr
            if attr == "getenv" and isinstance(node.func.value, ast.Name):
                is_getenv = node.func.value.id == "os"
            elif attr == "get" and isinstance(node.func.value, ast.Attribute):
                if (
                    node.func.value.attr == "environ"
                    and isinstance(node.func.value.value, ast.Name)
                    and node.func.value.value.id == "os"
                ):
                    is_environ_get = True

        if is_getenv or is_environ_get:
            # Check the default (second positional arg or 'default' keyword)
            default_node: ast.expr | None = None
            if len(node.args) >= 2:
                default_node = node.args[1]
            else:
                for kw in node.keywords:
                    if kw.arg == "default":
                        default_node = kw.value
                        break

            if default_node is not None and self._is_broker_literal(default_node):
                if not has_suppress_marker(self.source_lines, node.lineno):
                    assert isinstance(default_node, ast.Constant)
                    self.violations.append(
                        f"{self.filepath}:{node.lineno}: "
                        f"hardcoded Kafka broker URL as getenv fallback: "
                        f'"{default_node.value}" — '
                        f"broker addresses must come from env vars only "
                        f"(add # {SUPPRESS_MARKER} to suppress)"
                    )

        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:  # noqa: N802
        """Detect broker_var = "host:<port>" assignments outside getenv context."""
        if self._is_broker_literal(node.value):
            # Only flag if at least one target looks like a broker variable
            for target in node.targets:
                if isinstance(target, ast.Name) and BROKER_VAR_PATTERN.search(
                    target.id
                ):
                    if not has_suppress_marker(self.source_lines, node.lineno):
                        assert isinstance(node.value, ast.Constant)
                        self.violations.append(
                            f"{self.filepath}:{node.lineno}: "
                            f"hardcoded Kafka broker URL assigned to "
                            f"'{target.id}': \"{node.value.value}\" — "
                            f"use KAFKA_BOOTSTRAP_SERVERS env var "
                            f"(add # {SUPPRESS_MARKER} to suppress)"
                        )
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:  # noqa: N802
        """Detect annotated assignments: broker_var: str = "host:<port>"."""
        if node.value is not None and self._is_broker_literal(node.value):
            target = node.target
            if isinstance(target, ast.Name) and BROKER_VAR_PATTERN.search(target.id):
                if not has_suppress_marker(self.source_lines, node.lineno):
                    assert isinstance(node.value, ast.Constant)
                    self.violations.append(
                        f"{self.filepath}:{node.lineno}: "
                        f"hardcoded Kafka broker URL assigned to "
                        f"'{target.id}': \"{node.value.value}\" — "
                        f"use KAFKA_BOOTSTRAP_SERVERS env var "
                        f"(add # {SUPPRESS_MARKER} to suppress)"
                    )
        self.generic_visit(node)


def check_python_file(filepath: Path) -> list[str]:
    """Run broker fallback check on a single Python file."""
    try:
        source = filepath.read_text(encoding="utf-8")
    except OSError:
        return []
    source_lines = source.splitlines()
    try:
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError as exc:
        return [f"{filepath}: SyntaxError: {exc}"]

    visitor = BrokerFallbackVisitor(filepath, source_lines)
    visitor.visit(tree)
    return visitor.violations


def collect_python_files(root: Path) -> list[Path]:
    """Recursively collect Python files under root, respecting exclusions."""
    files: list[Path] = []
    for py_file in sorted(root.rglob("*.py")):
        if not is_excluded_path(py_file):
            files.append(py_file)
    return files


def find_repo_root(start: Path) -> Path:
    """Walk up from start to find the repo root (pyproject.toml or src/)."""
    root = start.resolve()
    for _ in range(10):
        if (root / "pyproject.toml").exists() or (root / "src").exists():
            return root
        root = root.parent
    return start.resolve()


def main() -> int:
    repo_root = find_repo_root(Path(__file__))

    # Scan src/ and plugins/ (omniclaude-specific paths)
    scan_roots: list[Path] = []
    for candidate in ("src", "plugins", "shared_lib", "hooks"):
        candidate_path = repo_root / candidate
        if candidate_path.is_dir():
            scan_roots.append(candidate_path)

    if not scan_roots:
        print("WARNING: No scannable directories found; skipping")
        return 0

    all_violations: list[str] = []
    for scan_root in scan_roots:
        for py_file in collect_python_files(scan_root):
            violations = check_python_file(py_file)
            all_violations.extend(violations)

    if not all_violations:
        print("OK: No hardcoded Kafka broker URL fallbacks found")
        return 0

    print(
        f"FAIL: Found {len(all_violations)} hardcoded Kafka broker URL fallback(s):\n"
    )
    for v in all_violations:
        print(f"  {v}")
    print(
        "\nKafka broker addresses must come from environment variables only."
        "\nNever hardcode :19092, :29092 as default/fallback values in source."
        "\n"
        "\nCorrect pattern:"
        '\n  brokers = os.getenv("KAFKA_BOOTSTRAP_SERVERS")  # no fallback'
        "\n  if not brokers:"
        '\n      raise RuntimeError("KAFKA_BOOTSTRAP_SERVERS not set")'
        "\n"
        "\nOr use the shared helper: from lib.kafka_config import get_kafka_bootstrap_servers"
        "\n"
        "\nTo suppress a known-safe occurrence, add to the flagged line:"
        f"\n  # {SUPPRESS_MARKER}"
        "\n"
        "\nSee OMN-3555 and the two-bus policy in ~/.claude/CLAUDE.md."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
