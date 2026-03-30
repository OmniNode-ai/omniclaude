# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Quality gate for agentic work products (OMN-5729).

Validates that an agentic loop result represents genuine work rather than
a refusal, empty output, or trivial response. If the gate fails, the work
product is discarded and the prompt falls through to Claude.

Checks:
1. Minimum tool calls (>=1) — the model actually used tools
2. Minimum output length (>=100 chars) — non-trivial output
3. No refusal indicators — the model didn't refuse the task
4. Minimum iterations (>=2) — the model did multi-step work
5. Evidence of grounding — the output references files, code, or search hits

Evidence-of-grounding doctrine: The quality gate requires evidence of grounding
in repository-derived artifacts. A 500-word response that names zero files from
the codebase fails the gate regardless of length or iteration count.

Ticket: OMN-5729, OMN-6961
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Minimum number of tool calls for the gate to pass.
_MIN_TOOL_CALLS = 1

# Minimum character length of the final content.
_MIN_CONTENT_LENGTH = 100

# Minimum loop iterations (model must have done multi-step work).
_MIN_ITERATIONS = 2

# Refusal indicators in the first 300 chars (case-insensitive).
_REFUSAL_INDICATORS: tuple[str, ...] = (
    "i cannot",
    "i'm unable",
    "i apologize",
    "as an ai",
    "i don't have",
    "i can't",
    "i am unable",
    "i'm not able",
    "i do not have",
    "sorry, i",
    "unfortunately, i",
)

# Evidence-of-grounding patterns
_GROUNDING_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"(?:[a-zA-Z0-9_./\\-]+\.(?:py|ts|js|yaml|yml|md|json|sh|toml|cfg|txt))\b"
    ),
    re.compile(r"\b(?:class|def|import|from)\s+[A-Za-z_]\w+"),
    re.compile(r"`[A-Za-z_]\w+(?:\.\w+)*`"),
    re.compile(r"(?:line\s+\d+|L\d+|:\d+:)"),
)
_MIN_GROUNDING_HITS = 1


@dataclass
class AgenticQualityResult:
    """Result of the agentic quality gate check.

    Attributes:
        passed: Whether all quality checks passed.
        reason: Human-readable failure reason (empty when passed).
    """

    passed: bool
    reason: str = ""


def check_agentic_quality(
    content: str | None,
    tool_calls_count: int,
    iterations: int,
) -> AgenticQualityResult:
    """Run quality checks on an agentic loop work product.

    Args:
        content: The final text output from the agentic loop.
        tool_calls_count: Total number of tool calls dispatched.
        iterations: Number of loop iterations executed.

    Returns:
        AgenticQualityResult indicating pass/fail and reason.
    """
    # Check 1: Minimum tool calls
    if tool_calls_count < _MIN_TOOL_CALLS:
        reason = (
            f"insufficient tool calls: {tool_calls_count} < {_MIN_TOOL_CALLS} "
            f"(model did not use tools)"
        )
        logger.debug("Agentic quality gate failed: %s", reason)
        return AgenticQualityResult(passed=False, reason=reason)

    # Check 2: Content must be present and non-trivial
    if not content or len(content.strip()) < _MIN_CONTENT_LENGTH:
        actual_len = len(content.strip()) if content else 0
        reason = f"content too short: {actual_len} < {_MIN_CONTENT_LENGTH} chars"
        logger.debug("Agentic quality gate failed: %s", reason)
        return AgenticQualityResult(passed=False, reason=reason)

    # Check 3: No refusal indicators
    preview = content[:300].lower()
    for indicator in _REFUSAL_INDICATORS:
        if indicator in preview:
            reason = f"refusal detected: {indicator!r}"
            logger.debug("Agentic quality gate failed: %s", reason)
            return AgenticQualityResult(passed=False, reason=reason)

    # Check 4: Minimum iterations
    if iterations < _MIN_ITERATIONS:
        reason = (
            f"insufficient iterations: {iterations} < {_MIN_ITERATIONS} "
            f"(model did not perform multi-step work)"
        )
        logger.debug("Agentic quality gate failed: %s", reason)
        return AgenticQualityResult(passed=False, reason=reason)

    # Check 5: Evidence of grounding
    grounding_hits = sum(
        1 for pattern in _GROUNDING_PATTERNS if pattern.search(content)
    )
    if grounding_hits < _MIN_GROUNDING_HITS:
        reason = (
            f"no evidence of grounding: output references {grounding_hits} "
            f"file paths or code identifiers (minimum: {_MIN_GROUNDING_HITS})"
        )
        logger.debug("Agentic quality gate failed: %s", reason)
        return AgenticQualityResult(passed=False, reason=reason)

    logger.debug(
        "Agentic quality gate passed: %d tool calls, %d iterations, %d chars, %d grounding",
        tool_calls_count,
        iterations,
        len(content),
        grounding_hits,
    )
    return AgenticQualityResult(passed=True)


__all__ = [
    "AgenticQualityResult",
    "check_agentic_quality",
]
