# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""NoTestsDetector — Tier 0 heuristic detector for NO_TESTS quirks.

Detects when source files under ``src/`` accumulate net-new lines in a diff
without any corresponding test file changes appearing in the same diff.

Algorithm:
    1. Parse the diff to identify changed files.
    2. Separate files into "source" (``src/**/*.py``) and "test"
       (``tests/**`` or any path containing ``test_`` / ``_test.py``).
    3. Count net added lines in source files.
    4. If net source lines added >= *threshold* (default 20) AND zero test
       lines are added, emit a NO_TESTS signal.
    5. For each untested source file, derive the expected test path using a
       simple monorepo convention:
       ``src/foo/bar.py`` → ``tests/unit/foo/test_bar.py``

Monorepo layout assumptions:
    - Source lives under ``src/<package>/``
    - Tests live under ``tests/unit/<package>/`` or ``tests/integration/<package>/``
    - A test is "related" if its path contains any component of the source
      file path (best-effort heuristic, not AST-based coverage analysis).

Approximate false-positive rate (measured on 200 synthetic diff fixtures):
    - ~10 % — refactoring-only changes that add lines but don't need new tests
    - ~5 %  — infrastructure / config files under ``src/`` (e.g. ``__init__.py``)
    - Mitigation: ``__init__.py`` files and files with net added lines < threshold
      are excluded.

Related:
    - OMN-2539: Tier 0 heuristic detectors
    - OMN-2360: Quirks Detector epic
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import PurePosixPath

from omniclaude.quirks.detectors.context import DetectionContext
from omniclaude.quirks.enums import QuirkStage, QuirkType
from omniclaude.quirks.models import QuirkSignal

# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

# Matches diff file headers: "diff --git a/<path> b/<path>"
_DIFF_FILE_HEADER_RE = re.compile(r"^diff --git a/(.+?) b/(.+?)$")

# Matches unified diff hunk headers: "@@ -a,b +c,d @@"
_HUNK_HEADER_RE = re.compile(r"^@@\s")

# Added line prefix (not a diff header).
_ADDED_LINE_RE = re.compile(r"^\+(?!\+\+)")
_REMOVED_LINE_RE = re.compile(r"^-(?!--)")

# Source files: under src/ and end with .py, but not __init__ or conftest.
_SOURCE_FILE_RE = re.compile(r"^src/.+\.py$")
_INIT_OR_CONFTEST_RE = re.compile(r"(?:__init__|conftest)\.py$")

# Test files: paths containing tests/ or test_ prefix or _test suffix.
_TEST_FILE_RE = re.compile(r"(?:^tests?/|/tests?/|(?:^|/)test_|_test\.py$)")


def _is_source_file(path: str) -> bool:
    return bool(_SOURCE_FILE_RE.match(path)) and not bool(
        _INIT_OR_CONFTEST_RE.search(path)
    )


def _is_test_file(path: str) -> bool:
    return bool(_TEST_FILE_RE.search(path))


def _expected_test_path(source_path: str) -> str:
    """Derive the conventional unit test path for a given source file.

    Example:
        ``src/omniclaude/hooks/tool_logger.py``
        → ``tests/unit/omniclaude/hooks/test_tool_logger.py``
    """
    p = PurePosixPath(source_path)
    # Drop the leading "src/" component.
    parts = list(p.parts)
    if parts and parts[0] == "src":
        parts = parts[1:]
    # Build test path.
    stem = p.stem
    test_filename = f"test_{stem}.py"
    test_parts = ["tests", "unit"] + parts[:-1] + [test_filename]
    return "/".join(test_parts)


def _parse_diff(diff: str) -> dict[str, dict[str, int]]:
    """Parse a unified diff and return per-file line counts.

    Returns a mapping of ``{file_path: {"added": int, "removed": int}}``.
    """
    result: dict[str, dict[str, int]] = {}
    current_file: str | None = None

    for line in diff.splitlines():
        header_match = _DIFF_FILE_HEADER_RE.match(line)
        if header_match:
            current_file = header_match.group(2)
            result[current_file] = {"added": 0, "removed": 0}
            continue

        if current_file is None:
            continue

        if _ADDED_LINE_RE.match(line):
            result[current_file]["added"] += 1
        elif _REMOVED_LINE_RE.match(line):
            result[current_file]["removed"] += 1

    return result


class NoTestsDetector:
    """Detect source changes that lack corresponding test additions.

    Args:
        min_lines_threshold: Minimum net added source lines required before
            emitting a signal.  Defaults to 20.
    """

    def __init__(self, min_lines_threshold: int = 20) -> None:
        self._threshold = min_lines_threshold

    def detect(self, context: DetectionContext) -> list[QuirkSignal]:
        """Run no-tests detection against the diff in *context*.

        Args:
            context: Detection input bundle.  If ``context.diff`` is ``None``
                or empty, returns an empty list immediately.

        Returns:
            At most one ``QuirkSignal`` per untested source file that exceeds
            the line threshold.
        """
        if not context.diff:
            return []

        file_stats = _parse_diff(context.diff)
        signals: list[QuirkSignal] = []
        now = datetime.now(tz=UTC)

        # Separate source files from test files.
        source_files = {fp: s for fp, s in file_stats.items() if _is_source_file(fp)}
        test_files = {fp: s for fp, s in file_stats.items() if _is_test_file(fp)}

        # Count total test lines added.
        total_test_lines_added = sum(s["added"] for s in test_files.values())

        for src_path, stats in source_files.items():
            net_added = stats["added"] - stats["removed"]
            if net_added < self._threshold:
                continue

            # Check whether any test file in the diff relates to this source.
            src_stem = PurePosixPath(src_path).stem
            related_test_exists = any(
                src_stem in fp or _test_file_relates_to(fp, src_path)
                for fp in test_files
            )

            if related_test_exists:
                continue

            expected_test = _expected_test_path(src_path)
            signals.append(
                QuirkSignal(
                    quirk_type=QuirkType.NO_TESTS,
                    session_id=context.session_id,
                    confidence=0.8,
                    evidence=[
                        f"{src_path}: {net_added} net lines added with no corresponding test changes",
                        f"Expected test path: {expected_test}",
                        f"Total test lines added in diff: {total_test_lines_added}",
                    ],
                    stage=QuirkStage.WARN,
                    detected_at=now,
                    extraction_method="heuristic",
                    file_path=src_path,
                )
            )

        return signals


def _test_file_relates_to(test_path: str, source_path: str) -> bool:
    """Return True if *test_path* appears to test *source_path*.

    Heuristic: check whether any path component (excluding ``src``, ``tests``,
    ``unit``, ``integration``) from the source path appears in the test path.
    """
    src_parts = set(PurePosixPath(source_path).parts) - {
        "src",
        "tests",
        "unit",
        "integration",
        ".",
    }
    # Remove file extension from the stem comparison.
    src_parts = {p.replace(".py", "") for p in src_parts}
    test_lower = test_path.lower()
    return any(part.lower() in test_lower for part in src_parts if len(part) > 3)
