#!/usr/bin/env python3
"""
CI check: No LinearClient or direct Linear API calls outside *effect* files.

Task 3 from OMN-2592:
  Python grep check — no `LinearClient` / direct Linear API calls outside `*effect*` files
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

# Symbols that indicate direct Linear API usage
FORBIDDEN_SYMBOLS: tuple[str, ...] = (
    "LinearClient",
    "LinearAPI",
    "linear_client",
    "linear_api",
    "LinearGraphQLClient",
    "LinearSDK",
)

FORBIDDEN_MODULE_PREFIXES: tuple[str, ...] = (
    "linear_sdk",
    "linearpy",
    "linear_client",
    "linear_api",
)


def is_effect_file(path: Path) -> bool:
    return "effect" in path.name.lower()


class LinearUsageVisitor(ast.NodeVisitor):
    def __init__(self, filepath: Path) -> None:
        self.filepath = filepath
        self.violations: list[str] = []

    def visit_Import(self, node: ast.Import) -> None:  # noqa: N802
        for alias in node.names:
            for prefix in FORBIDDEN_MODULE_PREFIXES:
                if alias.name.lower().startswith(prefix):
                    self.violations.append(
                        f"{self.filepath}:{node.lineno}: Linear SDK import '{alias.name}'"
                    )
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
        module = (node.module or "").lower()
        for prefix in FORBIDDEN_MODULE_PREFIXES:
            if module.startswith(prefix):
                self.violations.append(
                    f"{self.filepath}:{node.lineno}: Linear SDK from-import from '{node.module}'"
                )
                return
        # Also flag importing named Linear symbols from anywhere
        for alias in node.names:
            if alias.name in FORBIDDEN_SYMBOLS:
                self.violations.append(
                    f"{self.filepath}:{node.lineno}: "
                    f"import of Linear symbol '{alias.name}' from '{node.module}'"
                )
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:  # noqa: N802
        if node.id in FORBIDDEN_SYMBOLS:
            self.violations.append(
                f"{self.filepath}:{node.lineno}: usage of Linear symbol '{node.id}'"
            )
        self.generic_visit(node)


def check_file(filepath: Path) -> list[str]:
    try:
        source = filepath.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError as exc:
        return [f"{filepath}: SyntaxError: {exc}"]

    visitor = LinearUsageVisitor(filepath)
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
        if is_effect_file(py_file):
            continue
        violations = check_file(py_file)
        all_violations.extend(violations)

    if not all_violations:
        print("OK: No LinearClient/Linear API usage found outside *effect* files")
        return 0

    print(f"FAIL: Found {len(all_violations)} Linear API violation(s):\n")
    for v in all_violations:
        print(f"  {v}")
    print(
        "\nLinear API calls must be confined to *effect* files."
        "\nMove LinearClient usage to an effect node."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
