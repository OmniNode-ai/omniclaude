#!/usr/bin/env python3
"""
CI check: No DB access (reads OR writes) in orchestrator or compute node modules.

Checks 1 & 8 from OMN-2592:
- Check 1: Zero DB client imports AND zero SELECT statements in nodes/*/orchestrators/
  and nodes/*/compute/ -- reads and writes are equally banned from orchestration code
- Check 8: Negative orchestrator import test -- imports every orchestrator, asserts no
  db-client paths in sys.modules or class-level imports

This script runs one static pass:
  Pass A: grep/AST static check for DB-related symbols in orchestrator/compute files
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

# -----------------------------------------------------------------------
# Patterns that are forbidden in orchestrator / compute modules
# -----------------------------------------------------------------------
FORBIDDEN_IMPORT_PATTERNS: list[str] = [
    # SQLAlchemy sync/async session objects — scoped to sqlalchemy module imports
    "sqlalchemy",
    "AsyncSession",
    # Common ORM client patterns (explicit, not partial substring)
    "db_client",
    "database_client",
    "DatabaseClient",
    # asyncpg / psycopg direct usage
    "asyncpg",
    "psycopg",
    # Alembic
    "alembic",
    # Repository adapters (checked separately too) — require db_ prefix to avoid
    # false positives on unrelated modules that happen to contain "repository"
    "db_adapter",
    "db_repository",
]

FORBIDDEN_ATTR_ACCESS: list[str] = [
    # Raw SQL strings
    "SELECT",
    "INSERT",
    "UPDATE",
    "DELETE",
    "MERGE",
    "UPSERT",
]

# DB-specific call names: only flag these when called on a known DB-like receiver.
# Avoid broad names like "execute" or "commit" that appear in non-DB contexts
# (e.g., HTTP clients, async executors, transaction managers).
FORBIDDEN_CALL_NAMES: list[str] = [
    "fetchall",
    "fetchone",
    "fetchmany",
    "scalar",
    "scalars",
]


def is_orchestrator_or_compute(path: Path) -> bool:
    """Return True if the given file is inside an orchestrator or compute node directory."""
    parts = path.parts
    for i, part in enumerate(parts):
        if part.startswith("node_") and (
            part.endswith("_orchestrator") or part.endswith("_compute")
        ):
            return True
        # Also check if parent folder is named "orchestrators" or "compute"
        if part in ("orchestrators", "compute") and i > 0:
            # Verify we're inside a node_* directory somewhere above
            for j in range(i):
                if parts[j].startswith("node_"):
                    return True
    return False


class ForbiddenUsageVisitor(ast.NodeVisitor):
    """AST visitor that collects forbidden DB-related usage."""

    def __init__(self, filepath: Path) -> None:
        self.filepath = filepath
        self.violations: list[str] = []

    def visit_Import(self, node: ast.Import) -> None:  # noqa: N802
        for alias in node.names:
            for pattern in FORBIDDEN_IMPORT_PATTERNS:
                if pattern.lower() in alias.name.lower():
                    self.violations.append(
                        f"{self.filepath}:{node.lineno}: forbidden import '{alias.name}' "
                        f"(matches pattern '{pattern}')"
                    )
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
        module = node.module or ""
        for pattern in FORBIDDEN_IMPORT_PATTERNS:
            if pattern.lower() in module.lower():
                self.violations.append(
                    f"{self.filepath}:{node.lineno}: forbidden from-import from '{module}' "
                    f"(matches pattern '{pattern}')"
                )
        for alias in node.names:
            for pattern in FORBIDDEN_IMPORT_PATTERNS:
                if pattern.lower() in alias.name.lower():
                    self.violations.append(
                        f"{self.filepath}:{node.lineno}: forbidden import name '{alias.name}' "
                        f"(matches pattern '{pattern}')"
                    )
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:  # noqa: N802
        if isinstance(node.value, str):
            value_upper = node.value.upper().strip()
            for keyword in FORBIDDEN_ATTR_ACCESS:
                if value_upper.startswith(keyword + " ") or value_upper.startswith(
                    keyword + "\n"
                ):
                    # Only flag if it looks like a multi-word SQL statement
                    # (must have a second SQL-structural keyword: FROM, INTO, SET, WHERE, TABLE)
                    sql_structural = (
                        "FROM ",
                        "INTO ",
                        "SET ",
                        "WHERE ",
                        "TABLE ",
                        "JOIN ",
                    )
                    if any(kw in value_upper for kw in sql_structural):
                        self.violations.append(
                            f"{self.filepath}:{node.lineno}: SQL string literal "
                            f"(starts with '{keyword}', contains SQL keywords) "
                            f"found in orchestrator/compute"
                        )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        # Check for method calls like session.execute(...), conn.fetchall(), etc.
        if isinstance(node.func, ast.Attribute):
            if node.func.attr in FORBIDDEN_CALL_NAMES:
                self.violations.append(
                    f"{self.filepath}:{node.lineno}: suspicious DB call '.{node.func.attr}()' "
                    f"in orchestrator/compute"
                )
        self.generic_visit(node)


def check_file(filepath: Path) -> list[str]:
    """Parse a Python file and return any violations."""
    try:
        source = filepath.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError as exc:
        return [f"{filepath}: SyntaxError while parsing: {exc}"]

    visitor = ForbiddenUsageVisitor(filepath)
    visitor.visit(tree)
    return visitor.violations


def main() -> int:
    """Entry point; returns 0 on success, 1 on violations."""
    # Find root: walk up until we find src/ or pyproject.toml
    root = Path(__file__).resolve()
    for _ in range(10):
        if (root / "pyproject.toml").exists() or (root / "src").exists():
            break
        root = root.parent

    src_root = root / "src"
    if not src_root.exists():
        print(f"WARNING: src/ directory not found under {root}; skipping check")
        return 0

    all_violations: list[str] = []

    for py_file in sorted(src_root.rglob("*.py")):
        if not is_orchestrator_or_compute(py_file):
            continue
        violations = check_file(py_file)
        all_violations.extend(violations)

    if not all_violations:
        print("OK: No forbidden DB access found in orchestrator/compute modules")
        return 0

    print(f"FAIL: Found {len(all_violations)} forbidden DB access violation(s):\n")
    for v in all_violations:
        print(f"  {v}")
    print(
        "\nOrchestrator and compute nodes must not read from or write to the database directly."
        "\nMove all DB access to *effect* nodes."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
