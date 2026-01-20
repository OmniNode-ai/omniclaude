"""Topic base names and helper for OmniClaude events.

Topic names do NOT include environment prefix.
Final topic = f"{prefix}.{base_name}"
"""

from __future__ import annotations

import re

# Valid topic name pattern: alphanumeric segments separated by single dots
# No leading/trailing dots, no consecutive dots, no special characters except dots
_TOPIC_SEGMENT_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")


class TopicBase:
    """Base topic names (without environment prefix)."""

    SESSION_STARTED = "omniclaude.session.started.v1"
    SESSION_ENDED = "omniclaude.session.ended.v1"
    PROMPT_SUBMITTED = "omniclaude.prompt.submitted.v1"
    TOOL_EXECUTED = "omniclaude.tool.executed.v1"

    # Future (OMN-1402)
    LEARNING_PATTERN = "omniclaude.learning.pattern.v1"


def _validate_topic_segment(segment: str, name: str) -> str:
    """Validate a single topic segment (prefix or base segment).

    Args:
        segment: The segment to validate
        name: Name of the parameter for error messages

    Returns:
        The stripped segment

    Raises:
        ValueError: If segment is invalid
    """
    if segment is None:
        raise ValueError(f"{name} must not be None")

    if not isinstance(segment, str):
        raise ValueError(f"{name} must be a string, got {type(segment).__name__}")

    stripped = segment.strip()
    if not stripped:
        raise ValueError(f"{name} must be a non-empty string")

    return stripped


def _validate_topic_name(topic: str) -> None:
    """Validate that a topic name is well-formed.

    Args:
        topic: The full topic name to validate

    Raises:
        ValueError: If topic name is malformed
    """
    # Check for leading/trailing dots
    if topic.startswith("."):
        raise ValueError(f"Topic name must not start with a dot: {topic!r}")
    if topic.endswith("."):
        raise ValueError(f"Topic name must not end with a dot: {topic!r}")

    # Check for consecutive dots
    if ".." in topic:
        raise ValueError(f"Topic name must not contain consecutive dots: {topic!r}")

    # Validate each segment
    segments = topic.split(".")
    for segment in segments:
        if not segment:
            # Empty segment (shouldn't happen after above checks, but be defensive)
            raise ValueError(f"Topic name contains empty segment: {topic!r}")
        if not _TOPIC_SEGMENT_PATTERN.match(segment):
            raise ValueError(
                f"Topic segment contains invalid characters: {segment!r} in {topic!r}"
            )


def build_topic(prefix: str, base: str) -> str:
    """Build full topic name from prefix and base.

    Args:
        prefix: Environment prefix (e.g., "dev", "staging", "prod").
            Must be a non-empty string without dots.
        base: Base topic name from TopicBase (e.g., "omniclaude.session.started.v1").
            Must be a valid dotted topic name.

    Returns:
        Full topic name (e.g., "dev.omniclaude.session.started.v1")

    Raises:
        ValueError: If prefix or base is empty, None, whitespace-only,
            or if the resulting topic name is malformed (leading/trailing dots,
            consecutive dots, invalid characters).

    Examples:
        >>> build_topic("dev", TopicBase.SESSION_STARTED)
        'dev.omniclaude.session.started.v1'

        >>> build_topic("", TopicBase.SESSION_STARTED)
        Traceback (most recent call last):
            ...
        ValueError: prefix must be a non-empty string

        >>> build_topic(None, TopicBase.SESSION_STARTED)
        Traceback (most recent call last):
            ...
        ValueError: prefix must not be None
    """
    # Validate prefix
    prefix = _validate_topic_segment(prefix, "prefix")

    # Validate base
    base = _validate_topic_segment(base, "base")

    # Build the topic
    topic = f"{prefix}.{base}"

    # Validate the final topic name
    _validate_topic_name(topic)

    return topic
