# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Consumer group startup guard for F5 rules enforcement.

Implements F5.3: Any offset reset (auto.offset.reset=earliest / --from-beginning)
requires an explicit version bump in the consumer group ID.

Raises FatalStartupError at consumer startup if:
  - auto_offset_reset is configured as "earliest" AND
  - The consumer group ID does not contain a version component suffix ('.v{n}')

Bypass: The guard is skipped if the consumer has no committed offsets yet
(initial cluster bootstrap / first run). This is safe because on first
run there is nothing to drift from.

Usage:
    from omniclaude.lib.consumer_group_guard import (
        FatalStartupError,
        validate_consumer_group_config,
        SKILL_NODE_CONSUMER_GROUPS,
    )

    # At consumer startup:
    validate_consumer_group_config(
        group_id="omniclaude-git-effect.v1",
        auto_offset_reset="latest",  # OK
    )

    validate_consumer_group_config(
        group_id="omniclaude-git-effect",   # missing version
        auto_offset_reset="earliest",        # triggers guard
    )  # raises FatalStartupError
"""

from __future__ import annotations

import re

# Pattern for valid consumer group ID with version suffix (F5.2)
# Format: <prefix>-<name>.v<N>
# Example: omniclaude-git-effect.v1
_VERSION_SUFFIX_PATTERN = re.compile(r"\.v\d+$")

# F5.4 — Consumer group IDs for the 6 skill node consumers from OMN-2593
SKILL_NODE_CONSUMER_GROUPS: dict[str, str] = {
    "NodeGitEffect": "omniclaude-git-effect.v1",
    "NodeClaudeCodeSessionEffect": "omniclaude-claude-code-session-effect.v1",
    "NodeLocalLlmInferenceEffect": "omniclaude-local-llm-inference-effect.v1",
    "NodeLinearEffect": "omniclaude-linear-effect.v1",
    "NodeTicketingEffect": "omniclaude-ticketing-effect.v1",
    "NodeLocalCodingOrchestrator": "omniclaude-local-coding-orchestrator.v1",
}


class FatalStartupError(Exception):
    """Fatal error raised when consumer startup violates F5 rules.

    This error is non-recoverable. The consumer must be reconfigured
    before restarting.

    Attributes:
        group_id: The consumer group ID that violated the rule.
        auto_offset_reset: The configured offset reset value.
        rule: The F5 rule that was violated (e.g., 'F5.3').
    """

    def __init__(self, *, group_id: str, auto_offset_reset: str, rule: str) -> None:
        """Initialize FatalStartupError.

        Args:
            group_id: The consumer group ID that violated the rule.
            auto_offset_reset: The configured offset reset value.
            rule: The F5 rule that was violated.
        """
        self.group_id = group_id
        self.auto_offset_reset = auto_offset_reset
        self.rule = rule
        super().__init__(
            f"F5.3 violation: consumer group '{group_id}' uses "
            f"auto_offset_reset='{auto_offset_reset}' but the group ID has no "
            f"version component suffix (.v{{N}}). "
            f"Bump the version in the group ID to resolve. "
            f"Rule: {rule} — any offset reset requires an explicit version bump."
        )


def has_version_suffix(group_id: str) -> bool:
    """Check whether a consumer group ID has a version suffix.

    A valid version suffix matches the pattern '.v{N}' at the end of the string.

    Args:
        group_id: The consumer group ID to check.

    Returns:
        True if the group_id ends with a version suffix like '.v1', '.v2', etc.

    Examples:
        >>> has_version_suffix("omniclaude-git-effect.v1")
        True
        >>> has_version_suffix("omniclaude-git-effect")
        False
        >>> has_version_suffix("omniclaude-compliance-subscriber.v1")
        True
    """
    return bool(_VERSION_SUFFIX_PATTERN.search(group_id))


def validate_consumer_group_config(
    *,
    group_id: str,
    auto_offset_reset: str,
    has_committed_offsets: bool = False,
) -> None:
    """Validate consumer group configuration against F5 rules at startup.

    Raises FatalStartupError (F5.3) if:
      - auto_offset_reset is 'earliest' AND
      - group_id does not have a version suffix AND
      - has_committed_offsets is True (skip check on first run)

    Args:
        group_id: The consumer group ID to validate.
        auto_offset_reset: The configured auto.offset.reset value.
            Should be 'earliest', 'latest', or 'none'.
        has_committed_offsets: Whether committed offsets already exist for
            this group. If False (first run), the guard is bypassed.
            Default: False (safe default — always validate unless explicitly
            told offsets exist).

    Raises:
        FatalStartupError: If F5.3 is violated.

    Examples:
        >>> validate_consumer_group_config(
        ...     group_id="omniclaude-git-effect.v1",
        ...     auto_offset_reset="earliest",  # OK: has version suffix
        ... )
        >>> validate_consumer_group_config(
        ...     group_id="omniclaude-git-effect",
        ...     auto_offset_reset="latest",  # OK: not earliest
        ... )
        >>> validate_consumer_group_config(
        ...     group_id="omniclaude-git-effect",
        ...     auto_offset_reset="earliest",  # FAIL: missing version
        ...     has_committed_offsets=True,
        ... )  # raises FatalStartupError
    """
    if auto_offset_reset != "earliest":
        # F5.3 only applies to offset reset (earliest)
        return

    if not has_committed_offsets:
        # First run / bootstrap: no prior offsets to drift from, skip guard
        return

    if not has_version_suffix(group_id):
        raise FatalStartupError(
            group_id=group_id,
            auto_offset_reset=auto_offset_reset,
            rule="F5.3",
        )


__all__ = [
    "FatalStartupError",
    "SKILL_NODE_CONSUMER_GROUPS",
    "has_version_suffix",
    "validate_consumer_group_config",
]
