#!/usr/bin/env python3
"""
CI check: ModelCostLedger structural CI test.

Task 9 from OMN-2592:
  Asserts `run_id` field + index exist in ModelCostLedger

Searches for ModelCostLedger class definition(s) in the codebase and verifies:
  1. A `run_id` field is declared
  2. An index on `run_id` is referenced (either as SQLAlchemy Index() or via
     an index= kwarg on the Column)

If no ModelCostLedger is found the check passes (not yet implemented).
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path


class CostLedgerStructureVisitor(ast.NodeVisitor):
    """
    Inspect a ModelCostLedger class definition for required fields.
    """

    def __init__(self, filepath: Path) -> None:
        self.filepath = filepath
        self.violations: list[str] = []
        self._in_cost_ledger = False
        self._found_run_id_field = False
        self._found_run_id_index = False

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        if node.name in ("ModelCostLedger", "CostLedger"):
            self._in_cost_ledger = True
            self._found_run_id_field = False
            self._found_run_id_index = False
            self.generic_visit(node)
            self._in_cost_ledger = False

            if not self._found_run_id_field:
                self.violations.append(
                    f"{self.filepath}:{node.lineno}: "
                    f"ModelCostLedger is missing a 'run_id' field"
                )
            if not self._found_run_id_index:
                self.violations.append(
                    f"{self.filepath}:{node.lineno}: "
                    f"ModelCostLedger has no index on 'run_id' "
                    f"(use index=True on Column or an explicit Index())"
                )
        else:
            self.generic_visit(node)

    def _is_run_id_name(self, node: ast.expr) -> bool:
        """Return True if node represents the string 'run_id'."""
        if isinstance(node, ast.Constant) and node.s == "run_id":
            return True
        if isinstance(node, ast.Name) and node.id == "run_id":
            return True
        return False

    def visit_Assign(self, node: ast.Assign) -> None:  # noqa: N802
        if not self._in_cost_ledger:
            self.generic_visit(node)
            return
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "run_id":
                self._found_run_id_field = True
            if isinstance(target, ast.Attribute) and target.attr == "run_id":
                self._found_run_id_field = True
        # Check for index= kwarg in Column(index=True)
        if isinstance(node.value, ast.Call):
            self._check_column_call(node.value)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:  # noqa: N802
        if not self._in_cost_ledger:
            self.generic_visit(node)
            return
        target = node.target
        if isinstance(target, ast.Name) and target.id == "run_id":
            self._found_run_id_field = True
        if isinstance(target, ast.Attribute) and target.attr == "run_id":
            self._found_run_id_field = True
        # Check for mapped_column(index=True)
        if node.value and isinstance(node.value, ast.Call):
            self._check_column_call(node.value)
        self.generic_visit(node)

    def _check_column_call(self, call_node: ast.Call) -> None:
        """Check if a Column/mapped_column call includes index=True for run_id."""
        func_name = ""
        if isinstance(call_node.func, ast.Name):
            func_name = call_node.func.id
        elif isinstance(call_node.func, ast.Attribute):
            func_name = call_node.func.attr

        if func_name not in ("Column", "mapped_column", "Field"):
            return

        for kw in call_node.keywords:
            if kw.arg == "index":
                if isinstance(kw.value, ast.Constant) and kw.value.value is True:
                    self._found_run_id_index = True

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        if not self._in_cost_ledger:
            self.generic_visit(node)
            return

        # Check for explicit Index("ix_...", ModelCostLedger.run_id)
        func_name = ""
        if isinstance(node.func, ast.Name):
            func_name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            func_name = node.func.attr

        if func_name == "Index":
            for arg in node.args:
                if self._is_run_id_name(arg):
                    self._found_run_id_index = True
                if isinstance(arg, ast.Attribute) and arg.attr == "run_id":
                    self._found_run_id_index = True
        self.generic_visit(node)


def check_file(filepath: Path) -> tuple[bool, list[str]]:
    """
    Returns (found_ledger_class, violations).
    If found_ledger_class is False, the class was not in this file.
    """
    try:
        source = filepath.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError as exc:
        return False, [f"{filepath}: SyntaxError: {exc}"]

    visitor = CostLedgerStructureVisitor(filepath)
    visitor.visit(tree)

    # Did this file define ModelCostLedger?
    found = bool(visitor.violations) or _file_contains_ledger_class(tree)
    return found, visitor.violations


def _file_contains_ledger_class(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name in (
            "ModelCostLedger",
            "CostLedger",
        ):
            return True
    return False


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

    found_any = False
    all_violations: list[str] = []

    for py_file in sorted(src_root.rglob("*.py")):
        found, violations = check_file(py_file)
        if found:
            found_any = True
        all_violations.extend(violations)

    if not found_any:
        print(
            "OK: No ModelCostLedger class found — check skipped (not yet implemented)"
        )
        return 0

    if not all_violations:
        print("OK: ModelCostLedger has required 'run_id' field and index")
        return 0

    print("FAIL: ModelCostLedger structural violations:\n")
    for v in all_violations:
        print(f"  {v}")
    print(
        "\nModelCostLedger must declare a 'run_id' field with an index."
        "\nAdd: run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(...), index=True)"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
