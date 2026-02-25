# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Shared diff-extraction utilities for Tier 1 AST detectors.

Provides a single canonical implementation of added-line extraction from
unified diffs, used by both ``AstStubCodeDetector`` and
``HallucinatedApiDetector``.

Related:
    - OMN-2548: Tier 1 AST-based detectors
    - OMN-2360: Quirks Detector epic
"""

from __future__ import annotations

import re

# Matches lines added in a unified diff (leading ``+`` but not ``+++``).
_ADDED_LINE_RE = re.compile(r"^\+(?!\+\+)")


def extract_added_source(diff: str) -> tuple[str, dict[int, int]]:
    """Extract added lines from a diff and build a source-to-diff line mapping.

    Args:
        diff: Unified diff string.

    Returns:
        A 2-tuple of:
        - ``source``: concatenated added lines (without the leading ``+``),
          suitable for ``ast.parse``.
        - ``line_map``: mapping from 1-based line number *in the extracted
          source* to 1-based line number *in the original diff*.
    """
    source_lines: list[str] = []
    line_map: dict[int, int] = {}
    for diff_lineno, raw in enumerate(diff.splitlines(), start=1):
        if _ADDED_LINE_RE.match(raw):
            source_lines.append(raw[1:])  # strip leading '+'
            line_map[len(source_lines)] = diff_lineno
    return "\n".join(source_lines), line_map
