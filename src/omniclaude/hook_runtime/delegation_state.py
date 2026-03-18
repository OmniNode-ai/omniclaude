# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Hook runtime delegation state reducer. [OMN-5305]

Pure Python state manager — no ONEX/Kafka/DB dependencies.
Extracted from shell scripts into testable Python.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Tools that always count as write operations
_WRITE_TOOLS: frozenset[str] = frozenset(
    {
        "Write",
        "Edit",
        "NotebookEdit",
        "MultiEdit",
    }
)

# Tools that always count as read operations
_READ_TOOLS: frozenset[str] = frozenset(
    {
        "Read",
        "Glob",
        "Grep",
        "LS",
        "WebSearch",
        "WebFetch",
        "TodoRead",
        "TaskList",
        "TaskGet",
    }
)


@dataclass
class DelegationConfig:
    """Configuration for delegation enforcement thresholds and patterns."""

    write_warn_threshold: int = 3
    write_block_threshold: int = 5
    read_warn_threshold: int = 8
    read_block_threshold: int = 12
    total_block_threshold: int = 15
    skill_loaded_write_block: int = 2
    skill_loaded_read_block: int = 3
    skill_loaded_total_block: int = 4
    delegation_rule_tool_threshold: int = 2
    bash_readonly_patterns: list[str] = field(default_factory=list)
    bash_compound_deny_patterns: list[str] = field(default_factory=list)


@dataclass
class SessionState:
    """Per-session counter and flag state."""

    read_count: int = 0
    write_count: int = 0
    delegated: bool = False
    skill_loaded: bool = False
    write_warned: bool = False
    read_warned: bool = False


@dataclass
class ThresholdDecision:
    """Result of a threshold check."""

    decision: str  # pass | warn | block
    message: str | None = None
    counter_type: str | None = None  # read | write | total


class DelegationState:
    """Per-session delegation enforcement state machine.

    Thread-unsafe by design — the daemon runs single-threaded via asyncio.
    """

    def __init__(self, config: DelegationConfig) -> None:
        self._config = config
        self._sessions: dict[str, SessionState] = {}
        self._compiled_readonly: list[re.Pattern[str]] = [
            re.compile(p) for p in config.bash_readonly_patterns
        ]
        self._compiled_deny: list[re.Pattern[str]] = [
            re.compile(p) for p in config.bash_compound_deny_patterns
        ]

    def _session(self, session_id: str) -> SessionState:
        if session_id not in self._sessions:
            self._sessions[session_id] = SessionState()
        return self._sessions[session_id]

    def classify_tool(self, tool_name: str, tool_input: dict[str, object]) -> str:
        """Classify a tool call as 'read' or 'write'.

        Returns 'read' or 'write'.
        """
        if tool_name in _WRITE_TOOLS:
            return "write"
        if tool_name in _READ_TOOLS:
            return "read"

        if tool_name == "Bash":
            command = str(tool_input.get("command", ""))
            return self._classify_bash(command)

        # Unknown tools default to write (conservative)
        return "write"

    def _classify_bash(self, command: str) -> str:
        """Classify a Bash command as 'read' or 'write'."""
        # Check compound deny patterns first (e.g. &&, |, ;)
        for pattern in self._compiled_deny:
            if pattern.search(command):
                return "write"

        # Check if it matches a readonly pattern
        for pattern in self._compiled_readonly:
            if pattern.search(command):
                return "read"

        # Default bash to write (conservative)
        return "write"

    def record_tool(self, session_id: str, classification: str) -> None:
        """Increment the appropriate counter for a session."""
        s = self._session(session_id)
        if classification == "read":
            s.read_count += 1
        else:
            s.write_count += 1

    def check_thresholds(self, session_id: str) -> ThresholdDecision:
        """Check all thresholds and return a pass/warn/block decision."""
        s = self._session(session_id)
        total = s.read_count + s.write_count

        if s.skill_loaded:
            # Tightened thresholds when a skill was loaded without delegation
            if s.write_count >= self._config.skill_loaded_write_block:
                return ThresholdDecision(
                    decision="block",
                    message=(
                        f"DELEGATION ENFORCER [HARD BLOCK]: skill loaded, "
                        f"{s.write_count} write tool calls exceed threshold "
                        f"{self._config.skill_loaded_write_block}. "
                        "Dispatch via onex:polymorphic-agent."
                    ),
                    counter_type="write",
                )
            if s.read_count >= self._config.skill_loaded_read_block:
                return ThresholdDecision(
                    decision="block",
                    message=(
                        f"DELEGATION ENFORCER [HARD BLOCK]: skill loaded, "
                        f"{s.read_count} read tool calls exceed threshold "
                        f"{self._config.skill_loaded_read_block}. "
                        "Dispatch via onex:polymorphic-agent."
                    ),
                    counter_type="read",
                )
            if total >= self._config.skill_loaded_total_block:
                return ThresholdDecision(
                    decision="block",
                    message=(
                        f"DELEGATION ENFORCER [HARD BLOCK]: skill loaded, "
                        f"{total} total tool calls exceed threshold "
                        f"{self._config.skill_loaded_total_block}. "
                        "Dispatch via onex:polymorphic-agent."
                    ),
                    counter_type="total",
                )
        else:
            # Normal thresholds
            if s.write_count >= self._config.write_block_threshold:
                return ThresholdDecision(
                    decision="block",
                    message=(
                        f"DELEGATION ENFORCER [HARD BLOCK]: "
                        f"{s.write_count} write tool calls exceed threshold "
                        f"{self._config.write_block_threshold}. "
                        "Dispatch via onex:polymorphic-agent."
                    ),
                    counter_type="write",
                )
            if s.read_count > self._config.read_block_threshold:
                return ThresholdDecision(
                    decision="block",
                    message=(
                        f"DELEGATION ENFORCER [HARD BLOCK]: "
                        f"{s.read_count} read-only tool calls exceed threshold "
                        f"{self._config.read_block_threshold}. "
                        "Dispatch via onex:polymorphic-agent."
                    ),
                    counter_type="read",
                )
            if total >= self._config.total_block_threshold:
                return ThresholdDecision(
                    decision="block",
                    message=(
                        f"DELEGATION ENFORCER [HARD BLOCK]: "
                        f"{total} total tool calls exceed threshold "
                        f"{self._config.total_block_threshold}. "
                        "Dispatch via onex:polymorphic-agent."
                    ),
                    counter_type="total",
                )
            # Warn thresholds
            if (
                s.write_count >= self._config.write_warn_threshold
                and not s.write_warned
            ):
                s.write_warned = True
                return ThresholdDecision(
                    decision="warn",
                    message=(
                        f"DELEGATION ENFORCER [WARNING]: "
                        f"{s.write_count} write tool calls. Consider delegating."
                    ),
                    counter_type="write",
                )
            if s.read_count >= self._config.read_warn_threshold and not s.read_warned:
                s.read_warned = True
                return ThresholdDecision(
                    decision="warn",
                    message=(
                        f"DELEGATION ENFORCER [WARNING]: "
                        f"{s.read_count} read tool calls. Consider delegating."
                    ),
                    counter_type="read",
                )

        return ThresholdDecision(decision="pass")

    def mark_delegated(self, session_id: str) -> None:
        """Mark that delegation occurred for a session, resetting counters."""
        s = self._session(session_id)
        s.read_count = 0
        s.write_count = 0
        s.delegated = True
        s.write_warned = False
        s.read_warned = False

    def set_skill_loaded(self, session_id: str) -> None:
        """Mark that a skill was loaded without delegation (tightens thresholds)."""
        self._session(session_id).skill_loaded = True

    def reset_session(self, session_id: str) -> None:
        """Reset all state for a session (called on UserPromptSubmit)."""
        self._sessions[session_id] = SessionState()

    def get_counters(self, session_id: str) -> dict[str, int]:
        """Return the current counters for a session."""
        s = self._session(session_id)
        total = s.read_count + s.write_count
        return {"read": s.read_count, "write": s.write_count, "total": total}
