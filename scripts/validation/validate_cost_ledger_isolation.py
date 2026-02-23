#!/usr/bin/env python3
"""
CI check: BudgetEvaluator-only ledger CI.

Task 5 from OMN-2592:
  Fail if any module outside `nodes/**/effects/**` imports `ModelCostLedger`,
  `*ledger*repository*`, or `*cost*ledger*`

The cost ledger is a sensitive financial record and must only be accessed via
BudgetEvaluator effect nodes.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

FORBIDDEN_SYMBOLS: tuple[str, ...] = (
    "ModelCostLedger",
    "CostLedger",
    "cost_ledger",
)

FORBIDDEN_MODULE_PATTERNS: tuple[str, ...] = (
    "ledger_repository",
    "ledgerrepository",
    "ledger.repository",
    "cost_ledger",
    "costledger",
    "cost.ledger",
)


def _has_node_ancestor(parts: tuple[str, ...], up_to_index: int) -> bool:
    """Return True if any directory component before *up_to_index* starts with 'node_'."""
    return any(parts[j].startswith("node_") for j in range(up_to_index))


def is_effect_module(path: Path) -> bool:
    """Return True if path is an *effect* file inside a node_* tree, or inside an
    effects/ subdirectory within a node_* tree.

    A bare ``*_effect.py`` outside a ``node_*`` ancestor is NOT whitelisted, to
    prevent non-node modules from bypassing the ledger isolation check by
    naming themselves ``*_effect.py``.
    """
    parts = path.parts
    # Allow files named *_effect.py only when a node_* ancestor exists
    if path.name.endswith("_effect.py"):
        if _has_node_ancestor(parts, len(parts) - 1):
            return True
    # Allow files inside an effects/ subdirectory beneath a node_* folder
    for i, part in enumerate(parts):
        if part == "effects" and i > 0 and _has_node_ancestor(parts, i):
            return True
    # Allow files inside a directory named *effects* that is under a node_* folder
    for i, part in enumerate(parts):
        if "effect" in part.lower() and part != path.name and i > 0:
            if _has_node_ancestor(parts, i):
                return True
    return False


class LedgerImportVisitor(ast.NodeVisitor):
    def __init__(self, filepath: Path) -> None:
        self.filepath = filepath
        self.violations: list[str] = []

    def _check_symbol(self, name: str, lineno: int, context: str) -> None:
        lower = name.lower()
        for sym in FORBIDDEN_SYMBOLS:
            sym_lower = sym.lower()
            # Exact match or the forbidden symbol is a substring of the name
            # (but not the other way: don't flag 'os' because 'cost_ledger' contains 'os')
            if lower == sym_lower or sym_lower in lower:
                self.violations.append(
                    f"{self.filepath}:{lineno}: "
                    f"{context} references ledger symbol '{name}'"
                )
                return
        for pat in FORBIDDEN_MODULE_PATTERNS:
            if pat in lower:
                self.violations.append(
                    f"{self.filepath}:{lineno}: "
                    f"{context} references ledger module pattern '{pat}' in '{name}'"
                )
                return

    def visit_Import(self, node: ast.Import) -> None:  # noqa: N802
        for alias in node.names:
            self._check_symbol(alias.name, node.lineno, "import")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
        module = node.module or ""
        self._check_symbol(module, node.lineno, "from-import module")
        for alias in node.names:
            self._check_symbol(alias.name, node.lineno, "imported name")
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:  # noqa: N802
        for sym in FORBIDDEN_SYMBOLS:
            if node.id == sym:
                self.violations.append(
                    f"{self.filepath}:{node.lineno}: usage of ledger symbol '{node.id}'"
                )
        self.generic_visit(node)


def check_file(filepath: Path) -> list[str]:
    try:
        source = filepath.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError as exc:
        return [f"{filepath}: SyntaxError: {exc}"]

    visitor = LedgerImportVisitor(filepath)
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
        if is_effect_module(py_file):
            continue
        violations = check_file(py_file)
        all_violations.extend(violations)

    if not all_violations:
        print("OK: ModelCostLedger/ledger access confined to effect modules")
        return 0

    print(f"FAIL: Found {len(all_violations)} cost ledger isolation violation(s):\n")
    for v in all_violations:
        print(f"  {v}")
    print(
        "\nModelCostLedger and ledger repository access must only occur in effect nodes."
        "\nMove cost ledger access to a BudgetEvaluator effect node."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
