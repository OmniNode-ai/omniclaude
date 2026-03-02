#!/usr/bin/env python3
"""
CI check: Architectural invariants for ONEX nodes.

CDQA-07 (OMN-2977): AST-based import scanning for reducer and orchestrator modules.
OMN-3342: Raw topic literal scanning for production code.

Validates that:
1. Reducer and orchestrator modules do not import I/O packages directly.
2. Production code does not contain raw topic literal strings (onex.evt.* / onex.cmd.*).
   All topic references must go through the canonical topics.py constants file.
   Suppress with: # noqa: arch-topic-naming

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
import re
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
# Raw topic literal check (OMN-3342)
# ---------------------------------------------------------------------------

# Pattern that catches raw topic literals: onex.evt.* or onex.cmd.*
_RAW_TOPIC_PATTERN = re.compile(r"""["']onex\.(evt|cmd)\.[a-z]""")

# Suppress marker — same convention as existing arch-topic-naming noqa
_TOPIC_SUPPRESS_MARKER = "noqa: arch-topic-naming"

# Scan these trees for raw topic literals
TOPIC_SCAN_GLOBS = [
    "src/**/*.py",
    "plugins/**/*.py",
]

# Files that are allowed to define canonical topic literals
TOPIC_ALLOWLIST_PATTERNS = [
    "topics.py",
    "topic_constants.py",
    "contract.yaml",
]


def _is_in_docstring(source_lines: list[str], lineno: int) -> bool:
    """Return True if *lineno* (1-based) is inside a docstring or comment.

    Heuristic: the line is in a docstring if the stripped line starts with
    a string delimiter (``'``, ``"``) with no assignment operator before it,
    or if the previous non-blank line ends with ``\"\"\"`` or ``'''``.
    A simpler proxy: check if AST detects the node as a string constant that
    is not an assignment target.  We use a lightweight approach here because
    the full AST docstring check is expensive; false-negatives are acceptable
    (they result in extra allowed literals, not false alarms).
    """
    line = source_lines[lineno - 1] if lineno <= len(source_lines) else ""
    stripped = line.strip()
    # Lines that are pure comments
    if stripped.startswith("#"):
        return True
    return False


def extract_raw_topic_literals(path: Path) -> list[tuple[int, str]]:
    """Scan *path* for raw topic literal strings outside the allowlist.

    Returns a list of (lineno, description) tuples for each violation.
    Lines containing ``# noqa: arch-topic-naming`` are suppressed.
    Lines inside docstrings or comments are skipped.
    """
    # Skip allowlisted filenames
    if any(path.name == name for name in TOPIC_ALLOWLIST_PATTERNS):
        return []

    try:
        source = path.read_text(encoding="utf-8")
    except OSError:
        return []

    source_lines = source.splitlines()
    hits: list[tuple[int, str]] = []

    # Use AST to find string literals, then filter by pattern and location
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        # If we can't parse, skip — the existing check will catch the syntax error
        return []

    # Collect line numbers of all docstring nodes so we can exclude them
    docstring_lines: set[int] = set()
    for node in ast.walk(tree):
        # Module/class/function docstrings are Expr(value=Constant(str)) at the start
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            if isinstance(node.value.value, str):
                # Mark all lines of this string as docstring lines
                start = node.value.col_offset
                # Use lineno and end_lineno (Python 3.8+)
                for ln in range(
                    node.value.lineno, (node.value.end_lineno or node.value.lineno) + 1
                ):
                    docstring_lines.add(ln)

    for lineno, line in enumerate(source_lines, start=1):
        # Skip suppressed lines
        if _TOPIC_SUPPRESS_MARKER in line:
            continue
        # Skip pure comment lines
        if line.strip().startswith("#"):
            continue
        # Skip docstring lines
        if lineno in docstring_lines:
            continue
        # Check for raw topic literal
        match = _RAW_TOPIC_PATTERN.search(line)
        if match:
            literal_preview = match.group(0)
            hits.append((lineno, f"raw topic literal: {literal_preview}..."))

    return hits


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


def _collect_files_from_root(project_root: Path, globs: list[str]) -> list[Path]:
    """Return sorted list of files matching *globs* relative to *project_root*.

    Unlike ``_collect_files``, this does NOT strip leading path components —
    globs are applied relative to *project_root* as-is.
    """
    files: list[Path] = []
    for pattern in globs:
        files.extend(project_root.glob(pattern))
    # Exclude test/fixture/docs directories
    excluded = {"tests", "test_", ".venv", "__pycache__", "fixtures", "docs"}
    return sorted(p for p in set(files) if not any(ex in str(p) for ex in excluded))


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

    # Derive project root from src_dir (one level up)
    project_root = src_dir.parent if src_dir.name == "src" else src_dir

    if not src_dir.exists():
        print(f"WARNING: src/ directory not found at {src_dir}; skipping check")
        return 0

    all_violations: list[str] = []

    # -------------------------------------------------------------------------
    # Check 1: I/O imports in reducers / orchestrators (CDQA-07, OMN-2977)
    # -------------------------------------------------------------------------
    reducer_files = _collect_files(src_dir, REDUCER_GLOBS)
    for path in reducer_files:
        hits = extract_io_imports(path)
        for lineno, description in hits:
            all_violations.append(
                f"{path}:{lineno}: [reducer] forbidden I/O import: {description}"
            )

    orchestrator_files = _collect_files(src_dir, ORCHESTRATOR_GLOBS)
    for path in orchestrator_files:
        hits = extract_io_imports(path)
        for lineno, description in hits:
            all_violations.append(
                f"{path}:{lineno}: [orchestrator] forbidden I/O import: {description}"
            )

    io_import_total = len(reducer_files) + len(orchestrator_files)
    io_import_violations = len(all_violations)
    if io_import_violations == 0:
        print(
            f"OK [check 1]: No I/O import violations in {io_import_total} "
            "reducer/orchestrator file(s)"
        )
    else:
        print(f"FAIL [check 1]: {io_import_violations} I/O import violation(s) found:")
        for v in all_violations:
            print(f"  {v}")
        print(
            "\nReducer and orchestrator nodes must not import I/O packages directly."
            "\nMove all I/O to *effect* nodes."
        )

    # -------------------------------------------------------------------------
    # Check 2: Raw topic literals in production code (OMN-3342)
    # -------------------------------------------------------------------------
    topic_violations: list[str] = []
    topic_files = _collect_files_from_root(project_root, TOPIC_SCAN_GLOBS)
    for path in topic_files:
        hits = extract_raw_topic_literals(path)
        for lineno, description in hits:
            topic_violations.append(
                f"{path}:{lineno}: [topic-governance] {description}"
            )

    if not topic_violations:
        print(
            f"OK [check 2]: No raw topic literal violations in {len(topic_files)} "
            "production file(s)"
        )
    else:
        print(
            f"\nFAIL [check 2]: {len(topic_violations)} raw topic literal violation(s):\n"
        )
        for v in topic_violations:
            print(f"  {v}")
        print(
            "\nRaw topic literals bypass the contract system. Use the canonical"
            "\ntopics.py constants instead, or suppress with:"
            "\n  # noqa: arch-topic-naming"
        )

    all_violations.extend(topic_violations)

    if not all_violations:
        return 0

    print(f"\nTotal: {len(all_violations)} architectural invariant violation(s)")
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
