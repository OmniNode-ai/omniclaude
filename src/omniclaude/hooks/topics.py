"""Topic base names and helper for OmniClaude events.

Topic names do NOT include environment prefix.
Final topic = f"{prefix}.{base_name}"
"""

from __future__ import annotations


class TopicBase:
    """Base topic names (without environment prefix)."""

    SESSION_STARTED = "omniclaude.session.started.v1"
    SESSION_ENDED = "omniclaude.session.ended.v1"
    PROMPT_SUBMITTED = "omniclaude.prompt.submitted.v1"
    TOOL_EXECUTED = "omniclaude.tool.executed.v1"

    # Future (OMN-1402)
    LEARNING_PATTERN = "omniclaude.learning.pattern.v1"


def build_topic(prefix: str, base: str) -> str:
    """Build full topic name from prefix and base.

    Args:
        prefix: Environment prefix (e.g., "dev", "staging", "prod")
        base: Base topic name from TopicBase

    Returns:
        Full topic name (e.g., "dev.omniclaude.session.started.v1")

    Raises:
        ValueError: If prefix is empty or contains only whitespace
    """
    if not prefix or not prefix.strip():
        raise ValueError("prefix must be a non-empty string")
    return f"{prefix.strip()}.{base}"
