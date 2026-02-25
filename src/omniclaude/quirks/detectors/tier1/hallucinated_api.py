# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""HallucinatedApiDetector — Tier 1 AST-based detector for HALLUCINATED_API.

Detects references in generated code (extracted from a unified diff) to
symbols that do not appear in a supplied ``symbol_index`` (a mapping of
module path → set of exported names built by ``SymbolIndexBuilder``).

Algorithm:
    1. Extract added lines from the diff (strip leading ``+``).
    2. Parse them with ``ast.parse``; on failure, return ``[]`` and warn.
    3. Walk the AST for ``ast.Attribute`` nodes whose value is an
       ``ast.Name`` matching a module in ``symbol_index``.
    4. For each such reference ``module.attr``, check if ``attr`` is in
       ``symbol_index[module]``.
    5. For missing symbols, compute the closest Levenshtein neighbour
       (distance ≤ 2) among the module's exported names as a suggestion.
    6. Emit a ``HALLUCINATED_API`` signal per missing symbol.

Levenshtein implementation is **pure Python, inline** (no third-party deps).

Evidence field includes:
    - The diff line number where the reference occurs.
    - The referenced symbol (``module.attr``).
    - The closest valid alternative (if distance ≤ 2), or ``None``.

Related:
    - OMN-2548: Tier 1 AST-based detectors
    - OMN-2360: Quirks Detector epic
"""

from __future__ import annotations

import ast
import logging
import re
import warnings
from datetime import UTC, datetime

from omniclaude.quirks.detectors.context import DetectionContext
from omniclaude.quirks.enums import QuirkStage, QuirkType
from omniclaude.quirks.models import QuirkSignal
from omniclaude.quirks.tools.build_symbol_index import SymbolIndex

logger = logging.getLogger(__name__)

# Matches lines added in a unified diff (leading ``+`` but not ``+++``).
_ADDED_LINE_RE = re.compile(r"^\+(?!\+\+)")


# ---------------------------------------------------------------------------
# Pure-Python Levenshtein (inline, no external deps)
# ---------------------------------------------------------------------------


def _levenshtein(a: str, b: str) -> int:
    """Compute the Levenshtein edit distance between *a* and *b*.

    Standard dynamic-programming implementation.  Time: O(len(a) * len(b)).
    """
    if a == b:
        return 0
    len_a, len_b = len(a), len(b)
    if len_a == 0:
        return len_b
    if len_b == 0:
        return len_a

    # Use two rows to reduce memory usage.
    prev = list(range(len_b + 1))
    curr = [0] * (len_b + 1)

    for i in range(1, len_a + 1):
        curr[0] = i
        for j in range(1, len_b + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            curr[j] = min(
                curr[j - 1] + 1,  # insertion
                prev[j] + 1,  # deletion
                prev[j - 1] + cost,  # substitution
            )
        prev, curr = curr, prev

    return prev[len_b]


def _closest_alternative(
    symbol: str, candidates: set[str], max_distance: int = 2
) -> str | None:
    """Return the closest candidate to *symbol* within *max_distance*, or ``None``."""
    best: str | None = None
    best_dist = max_distance + 1
    for candidate in candidates:
        dist = _levenshtein(symbol, candidate)
        if dist < best_dist:
            best_dist = dist
            best = candidate
    return best if best_dist <= max_distance else None


# ---------------------------------------------------------------------------
# Diff helpers
# ---------------------------------------------------------------------------


def _extract_added_source(diff: str) -> tuple[str, dict[int, int]]:
    """Extract added lines from a diff and build a source-to-diff line mapping.

    Returns:
        ``(source, line_map)`` where ``source`` is the concatenated added
        lines (without leading ``+``) and ``line_map`` maps 1-based source
        line number to 1-based diff line number.
    """
    source_lines: list[str] = []
    line_map: dict[int, int] = {}
    for diff_lineno, raw in enumerate(diff.splitlines(), start=1):
        if _ADDED_LINE_RE.match(raw):
            source_lines.append(raw[1:])
            line_map[len(source_lines)] = diff_lineno
    return "\n".join(source_lines), line_map


# ---------------------------------------------------------------------------
# AST collection
# ---------------------------------------------------------------------------


def _collect_attribute_refs(
    tree: ast.AST,
) -> list[tuple[str, str, int]]:
    """Walk *tree* and collect ``module.attr`` attribute accesses.

    Only considers ``ast.Attribute`` nodes whose value is a plain ``ast.Name``
    (i.e. single-level ``module.symbol`` references).

    Returns:
        List of ``(module_name, attr_name, lineno)`` tuples.
    """
    refs: list[tuple[str, str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            refs.append((node.value.id, node.attr, node.lineno))
    return refs


# ---------------------------------------------------------------------------
# Detector
# ---------------------------------------------------------------------------


class HallucinatedApiDetector:
    """Detect references to non-existent symbols using AST analysis.

    The detector requires a ``symbol_index`` to be injected at construction
    time.  If no index is provided (empty dict), the detector returns an
    empty list immediately (it cannot detect without a reference corpus).

    Args:
        symbol_index: Mapping of module path (dotted string) to the set of
            names exported by that module.  Built by ``SymbolIndexBuilder``.
    """

    def __init__(self, symbol_index: SymbolIndex | None = None) -> None:
        self._symbol_index: SymbolIndex = symbol_index or {}

    def detect(self, context: DetectionContext) -> list[QuirkSignal]:
        """Run hallucinated-API detection against the diff in *context*.

        Args:
            context: Detection input bundle.  If ``context.diff`` is ``None``
                or empty, or if ``symbol_index`` is empty, returns ``[]``.

        Returns:
            List of ``QuirkSignal`` instances, one per detected unrecognised
            symbol reference.
        """
        if not context.diff:
            return []
        if not self._symbol_index:
            return []

        source, line_map = _extract_added_source(context.diff)
        if not source.strip():
            return []

        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", SyntaxWarning)
                tree = ast.parse(source)
        except SyntaxError as exc:
            logger.warning(
                "HallucinatedApiDetector: parse failure — skipping. "
                "session_id=%s error=%s",
                context.session_id,
                exc,
            )
            return []

        refs = _collect_attribute_refs(tree)
        if not refs:
            return []

        now = datetime.now(tz=UTC)
        signals: list[QuirkSignal] = []

        for module_name, attr_name, src_lineno in refs:
            if module_name not in self._symbol_index:
                # Unknown module — we can't validate it, skip.
                continue

            exported = self._symbol_index[module_name]
            if attr_name in exported:
                # Symbol exists — no hallucination.
                continue

            diff_lineno = line_map.get(src_lineno, src_lineno)
            closest = _closest_alternative(attr_name, exported)

            evidence: list[str] = [
                f"Line {diff_lineno}: `{module_name}.{attr_name}` not found in "
                f"symbol index for module `{module_name}`",
                f"Referenced symbol: {module_name}.{attr_name}",
            ]
            if closest is not None:
                evidence.append(f"Closest valid alternative: {module_name}.{closest}")
            else:
                evidence.append("No close alternative found (Levenshtein > 2)")

            signals.append(
                QuirkSignal(
                    quirk_type=QuirkType.HALLUCINATED_API,
                    session_id=context.session_id,
                    confidence=0.9,
                    evidence=evidence,
                    stage=QuirkStage.WARN,
                    detected_at=now,
                    extraction_method="AST",
                    ast_span=(diff_lineno, diff_lineno),
                )
            )

        return signals
