"""QPM PR Type Classifier — classify PRs as ACCELERATOR / NORMAL / BLOCKED.

Uses file-diff heuristics and CI/review status. Deterministic, no LLM.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass

from merge_planner.models import EnumPRQueueClass

# Strong accelerators: directly improve downstream pipeline reliability
STRONG_ACCELERATOR_PATTERNS: list[str] = [
    ".github/workflows/*",
    ".github/actions/*",
    ".pre-commit-config.yaml",
    "ruff.toml",
    "mypy.ini",
    ".flake8",
    "required-checks.yaml",
    "CI_CD_STANDARDS.md",
    "standards/**/*",
    "scripts/audit_*",
]

# Moderate accelerators: improve test coverage or enforcement
MODERATE_ACCELERATOR_PATTERNS: list[str] = [
    "tests/*",
    "tests/**/*",
    "*_test.py",
    "test_*.py",
    "conftest.py",
    "Makefile",
]

# Weak accelerators: low risk but not directly pipeline-improving
WEAK_ACCELERATOR_PATTERNS: list[str] = [
    "docs/**/*",
    "*.md",
    "CLAUDE.md",
]

# Excluded from accelerator patterns (Phase 1):
# - pyproject.toml: can mean dependency changes, build backend changes,
#   or runtime config. Too broad without section-aware diff classification.
#   Revisit in Phase 2 with [tool.*]-section filtering.

# Combined for classification (all tiers qualify as ACCELERATOR class)
ACCELERATOR_PATH_PATTERNS: list[str] = (
    STRONG_ACCELERATOR_PATTERNS
    + MODERATE_ACCELERATOR_PATTERNS
    + WEAK_ACCELERATOR_PATTERNS
)


@dataclass
class PRContext:
    """Raw PR data fetched via gh CLI. Mutable input, not a domain model."""

    number: int
    repo: str
    title: str
    is_draft: bool
    ci_status: str  # "success" | "failure" | "pending"
    review_state: str  # "approved" | "changes_requested" | "pending" | "none"
    changed_files: list[str]
    labels: list[str]


def _all_files_match_accelerator_patterns(files: list[str]) -> bool:
    """Return True if every changed file matches at least one accelerator pattern."""
    if not files:
        return False
    for f in files:
        if not any(fnmatch.fnmatch(f, pat) for pat in ACCELERATOR_PATH_PATTERNS):
            return False
    return True


def classify_pr(ctx: PRContext) -> EnumPRQueueClass:
    """Classify a PR for queue priority. Deterministic, no I/O."""
    # Blocked conditions (checked first)
    if ctx.is_draft:
        return EnumPRQueueClass.BLOCKED
    if ctx.ci_status == "failure":
        return EnumPRQueueClass.BLOCKED
    if ctx.review_state == "changes_requested":
        return EnumPRQueueClass.BLOCKED

    # Accelerator: ALL changed files match accelerator patterns
    if _all_files_match_accelerator_patterns(ctx.changed_files):
        return EnumPRQueueClass.ACCELERATOR

    return EnumPRQueueClass.NORMAL
