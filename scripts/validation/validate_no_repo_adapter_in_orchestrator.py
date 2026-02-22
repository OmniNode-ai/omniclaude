#!/usr/bin/env python3
"""
CI check: Repository adapter import-graph CI.

Task 4 from OMN-2592:
  Fail if orchestrator/compute modules import `*repository*` or `*db_adapter*`

This extends the DB check with a more specific focus on repository adapters,
which should only be used in effect nodes.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

FORBIDDEN_PATTERNS: tuple[str, ...] = (
    "repository",
    "db_adapter",
    "dbadapter",
    "repo_adapter",
)


def is_orchestrator_or_compute_file(path: Path) -> bool:
    """Return True if path is within an orchestrator or compute node module."""
    parts = path.parts
    for i, part in enumerate(parts):
        if part.startswith("node_") and (
            part.endswith("_orchestrator") or part.endswith("_compute")
        ):
            return True
        if part in ("orchestrators", "compute"):
            for j in range(i):
                if parts[j].startswith("node_"):
                    return True
    return False


class RepoAdapterImportVisitor(ast.NodeVisitor):
    def __init__(self, filepath: Path) -> None:
        self.filepath = filepath
        self.violations: list[str] = []

    def _check_module(self, module: str, lineno: int, context: str) -> None:
        lower = module.lower()
        for pattern in FORBIDDEN_PATTERNS:
            if pattern in lower:
                self.violations.append(
                    f"{self.filepath}:{lineno}: "
                    f"{context} contains '{pattern}' — "
                    f"repository adapters must not be imported in orchestrator/compute nodes"
                )

    def visit_Import(self, node: ast.Import) -> None:  # noqa: N802
        for alias in node.names:
            self._check_module(alias.name, node.lineno, f"import '{alias.name}'")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
        module = node.module or ""
        self._check_module(module, node.lineno, f"from '{module}' import")
        for alias in node.names:
            self._check_module(alias.name, node.lineno, f"imported name '{alias.name}'")
        self.generic_visit(node)


def check_file(filepath: Path) -> list[str]:
    try:
        source = filepath.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError as exc:
        return [f"{filepath}: SyntaxError: {exc}"]

    visitor = RepoAdapterImportVisitor(filepath)
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
        if not is_orchestrator_or_compute_file(py_file):
            continue
        violations = check_file(py_file)
        all_violations.extend(violations)

    if not all_violations:
        print("OK: No repository adapter imports found in orchestrator/compute modules")
        return 0

    print(
        f"FAIL: Found {len(all_violations)} repository adapter import violation(s):\n"
    )
    for v in all_violations:
        print(f"  {v}")
    print(
        "\nOrchestrator and compute nodes must not import repository or db_adapter modules."
        "\nDelegate all persistence to effect nodes."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
