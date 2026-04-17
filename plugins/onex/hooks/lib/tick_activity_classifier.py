# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Idle-watchdog tick activity classifier [OMN-9053].

Replaces the OMN-9036 stub emission-on-every-tick behavior with classification
of observational vs mutating tool calls. A tick is "idle" when the mutating
ratio falls below ``min_ratio`` (default 0.1 per plan Task 9 spec).

The classifier decides whether a tick should emit a friction event; it does
not persist anything itself. Callers (e.g. ``scripts/cron-idle-watchdog.sh``)
must route emission through ``/onex:record_friction`` so persistence, taxonomy,
and downstream escalation flow through ``node_friction_observer_compute``.

Refs:
    * Plan: ``docs/plans/2026-04-17-overnight-process-hardening.md`` Task 9
    * Retro §4.4: silence-as-compliance anti-pattern this prevents
"""

from __future__ import annotations

from enum import StrEnum


class ActivityKind(StrEnum):
    """Binary classification of a tool call for idle-watchdog purposes."""

    OBSERVATIONAL = "observational"
    MUTATING = "mutating"


_OBSERVATIONAL_BASH_PREFIXES: tuple[str, ...] = (
    "gh pr view",
    "gh pr checks",
    "gh pr list",
    "gh run view",
    "gh run list",
    "gh api repos/",
    "gh search",
    "cat ",
    "ls ",
    "grep ",
    "rg ",
    "head ",
    "tail ",
    "awk ",
    "jq ",
    "sed -n",
    "find ",
)

_MUTATING_TOOLS: frozenset[str] = frozenset(
    {
        "Write",
        "Edit",
        "Agent",
        "NotebookEdit",
        "TaskCreate",
        "TaskUpdate",
        "SendMessage",
    }
)


def classify_tool_call(call: dict) -> ActivityKind:
    """Classify a single tool-call record as observational or mutating.

    A call is MUTATING when the tool name is in ``_MUTATING_TOOLS`` or when
    it's a Bash call whose command does not begin with a known read-only
    prefix (``gh pr view``, ``cat``, ``grep``, etc.). Any other tool (Read,
    Grep, Glob, etc.) is OBSERVATIONAL by default.
    """
    name = call.get("name", "")
    if name in _MUTATING_TOOLS:
        return ActivityKind.MUTATING
    if name == "Bash":
        cmd = (call.get("input") or {}).get("command", "")
        if cmd.startswith(_OBSERVATIONAL_BASH_PREFIXES):
            return ActivityKind.OBSERVATIONAL
        return ActivityKind.MUTATING
    return ActivityKind.OBSERVATIONAL


def is_idle_tick(calls: list[dict], min_ratio: float = 0.1) -> bool:
    """Return True when the tick's mutating ratio is below ``min_ratio``.

    An empty call list is treated as idle — nothing happened, so the tick
    should emit friction if the backlog warrants it.
    """
    total = len(calls)
    if total == 0:
        return True
    mutating = sum(1 for c in calls if classify_tool_call(c) == ActivityKind.MUTATING)
    return (mutating / total) < min_ratio
