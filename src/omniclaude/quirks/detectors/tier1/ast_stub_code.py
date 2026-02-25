# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""AstStubCodeDetector — Tier 1 AST-based detector for STUB_CODE quirks.

Parses added lines from a unified diff as Python source and uses the stdlib
``ast`` module to detect function/method definitions whose body contains only
stub-like nodes:

* ``ast.Pass`` — bare ``pass`` statement
* ``ast.Expr`` wrapping ``ast.Constant(...)`` (Ellipsis literal)
* ``ast.Raise`` of ``NotImplementedError``

Confidence: 0.95 (higher than Tier 0 regex, 0.9).
Extraction method: ``"AST"``

On parse failure (partial diffs, syntax errors), the detector emits no signal
and logs a warning so Tier 0 results remain the authoritative fallback.

Related:
    - OMN-2548: Tier 1 AST-based detectors
    - OMN-2539: Tier 0 heuristic detectors (regex fallback)
    - OMN-2360: Quirks Detector epic
"""

from __future__ import annotations

import ast
import logging
import warnings
from datetime import UTC, datetime

from omniclaude.quirks.detectors.context import DetectionContext
from omniclaude.quirks.detectors.tier1._diff_utils import extract_added_source
from omniclaude.quirks.enums import QuirkStage, QuirkType
from omniclaude.quirks.models import QuirkSignal

__all__ = ["AstStubCodeDetector"]

logger = logging.getLogger(__name__)


def _is_stub_body(body: list[ast.stmt]) -> bool:
    """Return True if *body* consists entirely of stub-like statements.

    A body is considered stub-like when every statement is one of:
    - ``ast.Pass``
    - ``ast.Expr`` wrapping ``ast.Constant(...)`` (Ellipsis)
    - ``ast.Raise`` of ``NotImplementedError`` (bare raise or
      ``raise NotImplementedError(...)`` / ``raise NotImplementedError``)

    A body with any real implementation statement is NOT considered a stub.
    """
    if not body:
        return False
    for stmt in body:
        if isinstance(stmt, ast.Pass):
            continue
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
            if stmt.value.value is ...:
                continue
        if isinstance(stmt, ast.Raise):
            exc = stmt.exc
            if exc is None:
                # bare ``raise`` — treat as stub
                continue
            # ``raise NotImplementedError`` or ``raise NotImplementedError(...)``
            if isinstance(exc, ast.Name) and exc.id == "NotImplementedError":
                continue
            if (
                isinstance(exc, ast.Call)
                and isinstance(exc.func, ast.Name)
                and exc.func.id == "NotImplementedError"
            ):
                continue
        # Any other statement means this is not purely a stub body.
        return False
    return True


def _collect_stub_functions(
    tree: ast.AST,
) -> list[tuple[str, int, int]]:
    """Walk *tree* and collect stub function/method definitions.

    Returns:
        List of ``(name, start_lineno, end_lineno)`` tuples for each
        function/method definition whose body is entirely stub-like.
    """
    stubs: list[tuple[str, int, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if _is_stub_body(node.body):
                end_line = getattr(node, "end_lineno", node.lineno)
                stubs.append((node.name, node.lineno, end_line))
    return stubs


class AstStubCodeDetector:
    """Detect stub function/method bodies using AST analysis.

    This detector is the Tier 1 upgrade of ``StubCodeDetector``.  It parses
    the added lines extracted from a unified diff using Python's stdlib ``ast``
    module and emits a ``STUB_CODE`` signal at confidence 0.95 for every
    function or method definition whose body contains only stub-like nodes.

    On parse failure (e.g. partial diff that is not valid Python), it emits
    no signal and logs a ``WARNING`` so Tier 0 results remain the fallback.
    """

    def detect(self, context: DetectionContext) -> list[QuirkSignal]:
        """Run AST stub-code detection against the diff in *context*.

        Args:
            context: Detection input bundle.  If ``context.diff`` is ``None``
                or empty, returns an empty list immediately.

        Returns:
            List of ``QuirkSignal`` instances, one per detected stub function
            or method.  Returns an empty list if the diff cannot be parsed or
            if no stubs are found.
        """
        if not context.diff:
            return []

        source, line_map = extract_added_source(context.diff)
        if not source.strip():
            return []

        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", SyntaxWarning)
                tree = ast.parse(source)
        except SyntaxError as exc:
            logger.warning(
                "AstStubCodeDetector: parse failure — falling back to Tier 0. "
                "session_id=%s error=%s",
                context.session_id,
                exc,
            )
            return []

        stubs = _collect_stub_functions(tree)
        if not stubs:
            return []

        now = datetime.now(tz=UTC)
        signals: list[QuirkSignal] = []
        for func_name, start_src, end_src in stubs:
            # Map source line numbers back to diff line numbers.
            diff_start = line_map.get(start_src, start_src)
            diff_end = line_map.get(end_src, end_src)

            signals.append(
                QuirkSignal(
                    quirk_type=QuirkType.STUB_CODE,
                    session_id=context.session_id,
                    confidence=0.95,
                    evidence=[
                        f"AST: stub function `{func_name}` at diff lines "
                        f"{diff_start}-{diff_end} has only stub-like body",
                        f"Function name: {func_name}",
                    ],
                    stage=QuirkStage.WARN,
                    detected_at=now,
                    extraction_method="AST",
                    ast_span=(diff_start, diff_end),
                )
            )

        return signals
