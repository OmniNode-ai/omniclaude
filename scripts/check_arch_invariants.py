#!/usr/bin/env python3
"""
CI check: Architectural invariants for ONEX nodes.

CDQA-07 (OMN-2977): AST-based import scanning for reducer and orchestrator modules.

Validates that reducer and orchestrator modules do not import I/O packages directly.
Uses ast.parse() to handle all Python import forms:
  - import x
  - from x import y
  - import x as y
  - multi-line imports (parenthesized)

Exit codes:
  0 — no violations found
  1 — one or more violations found
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

IO_PACKAGES = frozenset(
    [
        "kafka",
        "aiokafka",
        "confluent_kafka",
        "psycopg",
        "psycopg2",
        "asyncpg",
        "httpx",
        "aiohttp",
        "requests",
        "aiofiles",
        "boto3",
        "botocore",
    ]
)

REDUCER_GLOBS = ["src/**/reducer_*.py", "src/**/reducers/*.py"]
ORCHESTRATOR_GLOBS = ["src/**/orchestrator_*.py", "src/**/orchestrators/*.py"]


# ---------------------------------------------------------------------------
# Import extraction using AST
# ---------------------------------------------------------------------------


def _is_io_import(module_name: str) -> bool:
    """Return True if module_name matches any IO_PACKAGES prefix."""
    # Normalise: take only the top-level package (everything before the first dot)
    top_level = module_name.split(".")[0]
    return top_level in IO_PACKAGES


def extract_io_imports(path: Path) -> list[tuple[int, str]]:
    """Parse *path* with ast.parse() and return (lineno, description) for each
    I/O import found.  Handles all Python import statement forms."""
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        # Treat parse errors as a single "violation" so CI fails visibly
        return [(0, f"SyntaxError while parsing {path}: {exc}")]

    hits: list[tuple[int, str]] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            # import x, import x as y, import x, y
            for alias in node.names:
                if _is_io_import(alias.name):
                    hits.append(
                        (
                            node.lineno,
                            f"import {alias.name}",
                        )
                    )

        elif isinstance(node, ast.ImportFrom):
            # from x import y, from x.y import z
            module = node.module or ""
            if _is_io_import(module):
                imported_names = ", ".join(alias.name for alias in node.names)
                hits.append(
                    (
                        node.lineno,
                        f"from {module} import {imported_names}",
                    )
                )

    return hits


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------


def _collect_files(src_root: Path, globs: list[str]) -> list[Path]:
    """Return sorted list of Python files matching any of *globs* under *src_root*."""
    files: list[Path] = []
    for pattern in globs:
        # Strip leading "src/" because we already start from src_root
        relative_pattern = pattern.removeprefix("src/")
        files.extend(src_root.glob(relative_pattern))
    return sorted(set(files))


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def main(src_dir: Path | None = None) -> int:
    """Check architectural invariants.

    Args:
        src_dir: Path to the ``src/`` directory to scan.  When *None*, the
                 function walks up from the script's location to find
                 ``pyproject.toml`` / ``src/``.

    Returns:
        0 on success (no violations), 1 on failure.
    """
    if src_dir is None:
        # Auto-discover project root
        root = Path(__file__).resolve().parent
        for _ in range(10):
            if (root / "pyproject.toml").exists() or (root / "src").exists():
                break
            root = root.parent
        src_dir = root / "src"

    if not src_dir.exists():
        print(f"WARNING: src/ directory not found at {src_dir}; skipping check")
        return 0

    all_violations: list[str] = []

    # Check reducers
    reducer_files = _collect_files(src_dir, REDUCER_GLOBS)
    for path in reducer_files:
        hits = extract_io_imports(path)
        for lineno, description in hits:
            all_violations.append(
                f"{path}:{lineno}: [reducer] forbidden I/O import: {description}"
            )

    # Check orchestrators
    orchestrator_files = _collect_files(src_dir, ORCHESTRATOR_GLOBS)
    for path in orchestrator_files:
        hits = extract_io_imports(path)
        for lineno, description in hits:
            all_violations.append(
                f"{path}:{lineno}: [orchestrator] forbidden I/O import: {description}"
            )

    if not all_violations:
        total = len(reducer_files) + len(orchestrator_files)
        print(
            f"OK: No I/O import violations found in {total} reducer/orchestrator file(s)"
        )
        return 0

    print(f"FAIL: Found {len(all_violations)} architectural invariant violation(s):\n")
    for v in all_violations:
        print(f"  {v}")
    print(
        "\nReducer and orchestrator nodes must not import I/O packages directly."
        "\nMove all I/O to *effect* nodes."
    )
    return 1


if __name__ == "__main__":
    # Allow an optional positional argument: path to the src/ directory
    # e.g.: uv run python scripts/check_arch_invariants.py src/
    target: Path | None = None
    if len(sys.argv) > 1:
        target = Path(sys.argv[1]).resolve()
        if not target.exists():
            print(f"ERROR: path does not exist: {target}", file=sys.stderr)
            sys.exit(1)
        # If a "src/" sub-directory exists inside the given path, use it
        candidate = target / "src"
        if candidate.is_dir():
            target = candidate

    sys.exit(main(target))
