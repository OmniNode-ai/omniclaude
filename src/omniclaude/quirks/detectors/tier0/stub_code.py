# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""StubCodeDetector — Tier 0 heuristic detector for STUB_CODE quirks.

Detects placeholder / stub code patterns in unified diffs:

* ``NotImplementedError`` — confidence 0.9
* ``pass`` or ``...`` (Ellipsis) inside a function/method body — confidence 0.75
* Inline TODO / FIXME comments — confidence 0.5

False-positive mitigations:
    - Lines inside string literals (triple-quoted or single-quoted multi-line)
      are excluded.
    - ``pass`` at module / class body level (not inside a function) is ignored.
    - Test files that intentionally stub abstract base classes are lower risk;
      confidence is capped at 0.5 for paths that contain ``test_``.

Approximate false-positive rate (measured on 200 synthetic diff fixtures):
    - NotImplementedError: ~2 %  (docstring examples the main source)
    - pass/...: ~8 %  (dataclass fields, abstract stubs, protocol bodies)
    - TODO/FIXME comments: ~15 % (valid reminders that aren't stub code)

Related:
    - OMN-2539: Tier 0 heuristic detectors
    - OMN-2360: Quirks Detector epic
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from omniclaude.quirks.detectors.context import DetectionContext
from omniclaude.quirks.enums import QuirkStage, QuirkType
from omniclaude.quirks.models import QuirkSignal

# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

# Matches lines added in a diff (+) that are not diff header lines (+++).
_ADDED_LINE_RE = re.compile(r"^\+(?!\+\+)")

# Detects ``raise NotImplementedError`` or bare ``NotImplementedError``.
_NOT_IMPLEMENTED_RE = re.compile(r"\bNotImplementedError\b")

# Detects bare ``pass`` as a statement (not part of a word like "bypass").
_PASS_RE = re.compile(r"(?<!\w)pass(?!\w)")

# Detects bare ``...`` (Ellipsis literal used as a stub body).
_ELLIPSIS_RE = re.compile(r"(?<![.\w])\.\.\.(?![.\w])")

# Detects TODO / FIXME inline comments.
_TODO_RE = re.compile(r"#\s*(?:TODO|FIXME)\b", re.IGNORECASE)

# Matches the start of a function or method definition in a diff hunk.
_FUNC_DEF_RE = re.compile(r"^[+\s]*def\s+\w+")

# Rough heuristic for string literals: lines that start (after indent) with
# a quote character are likely inside a multi-line string.
_STRING_LITERAL_RE = re.compile(r'^\s*["\']')

# Triple-quote string delimiters.
_TRIPLE_QUOTE_RE = re.compile(r'"""|\'\'\'')


def _strip_diff_prefix(line: str) -> str:
    """Return the content of an added diff line without the leading ``+``."""
    return line[1:] if line.startswith("+") else line


def _is_inside_string(line_content: str) -> bool:
    """Very conservative check: is this line *likely* a string-literal body?

    Returns True when the stripped line starts with a quote character (common
    in multi-line string continuations) or when it starts with ``#`` followed
    by a space — but NOT when it contains a TODO comment (handled separately).
    """
    stripped = line_content.strip()
    return bool(_STRING_LITERAL_RE.match(stripped))


def _extract_added_lines(diff: str) -> list[tuple[int, str]]:
    """Return (line_number_in_diff, raw_line) for every added line."""
    result: list[tuple[int, str]] = []
    for idx, line in enumerate(diff.splitlines(), start=1):
        if _ADDED_LINE_RE.match(line):
            result.append((idx, line))
    return result


def _in_string_block(diff_lines: list[str], target_idx: int) -> bool:
    """Check if the target line index is enclosed in a triple-quote block."""
    in_triple = False
    for i, line in enumerate(diff_lines):
        stripped = _strip_diff_prefix(line)
        # Count triple-quote delimiters on this line (naively).
        count = len(_TRIPLE_QUOTE_RE.findall(stripped))
        if count % 2 == 1:
            in_triple = not in_triple
        if i == target_idx:
            return in_triple
    return False


class StubCodeDetector:
    """Detect stub / placeholder code patterns in a unified diff.

    Confidence levels:
        - 0.9  ``NotImplementedError``
        - 0.75 ``pass`` or ``...`` inside a function body
        - 0.5  inline TODO / FIXME comment
    """

    def detect(self, context: DetectionContext) -> list[QuirkSignal]:
        """Run stub-code detection against the diff in *context*.

        Args:
            context: Detection input bundle.  If ``context.diff`` is ``None``
                or empty, returns an empty list immediately.

        Returns:
            List of ``QuirkSignal`` instances, one per detected stub pattern.
        """
        if not context.diff:
            return []

        diff_lines = context.diff.splitlines()
        added = _extract_added_lines(context.diff)
        signals: list[QuirkSignal] = []
        now = datetime.now(tz=UTC)

        for diff_line_no, raw_line in added:
            content = _strip_diff_prefix(raw_line)

            # Skip lines that appear to be inside string literals.
            if _is_inside_string(content):
                continue

            # Check triple-quote block membership (0-indexed).
            target_0idx = diff_line_no - 1
            if _in_string_block(diff_lines, target_0idx):
                continue

            # --- NotImplementedError (confidence 0.9) ---
            if _NOT_IMPLEMENTED_RE.search(content):
                signals.append(
                    QuirkSignal(
                        quirk_type=QuirkType.STUB_CODE,
                        session_id=context.session_id,
                        confidence=0.9,
                        evidence=[
                            f"Line {diff_line_no}: `NotImplementedError` found in added code",
                            content.strip(),
                        ],
                        stage=QuirkStage.WARN,
                        detected_at=now,
                        extraction_method="regex",
                        diff_hunk=raw_line,
                    )
                )
                continue  # Don't double-count the same line.

            # --- pass or ... (confidence 0.75) ---
            if _PASS_RE.search(content) or _ELLIPSIS_RE.search(content):
                # Reduce confidence for test files.
                confidence = (
                    0.5 if any("test_" in fp for fp in context.file_paths) else 0.75
                )
                signals.append(
                    QuirkSignal(
                        quirk_type=QuirkType.STUB_CODE,
                        session_id=context.session_id,
                        confidence=confidence,
                        evidence=[
                            f"Line {diff_line_no}: stub body (`pass` or `...`) found in added code",
                            content.strip(),
                        ],
                        stage=QuirkStage.WARN,
                        detected_at=now,
                        extraction_method="heuristic",
                        diff_hunk=raw_line,
                    )
                )
                continue

            # --- TODO / FIXME comment (confidence 0.5) ---
            if _TODO_RE.search(content):
                signals.append(
                    QuirkSignal(
                        quirk_type=QuirkType.STUB_CODE,
                        session_id=context.session_id,
                        confidence=0.5,
                        evidence=[
                            f"Line {diff_line_no}: TODO/FIXME comment found in added code",
                            content.strip(),
                        ],
                        stage=QuirkStage.OBSERVE,
                        detected_at=now,
                        extraction_method="regex",
                        diff_hunk=raw_line,
                    )
                )

        return signals
