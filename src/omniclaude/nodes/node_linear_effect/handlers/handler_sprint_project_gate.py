# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Rule 2 of the ticket-creation guard: no project, except the current sprint's.

A new ticket is created in the Backlog with no project unless it is placed in the current sprint:
the project whose name starts with ``Sprint <start> -> <end>`` and whose window holds today (operator
rulings 2026-09-30T14:30:05Z and 2026-11-20T13:52:49Z). The name shape is ``ticket_creation_policy.json``'s
``sprint_project.name_pattern``; this module spells none of it. A project that is not the current sprint's,
and every ``projectId`` (an id carries no window to judge), is still refused with the project_set finding.

Lifted out of ``plugins/onex/hooks/lib/ticket_creation_guard.py``, a baselined mod file that may only shrink
under the canonical-file-shape ratchet. The guard loads this module by path and runs it under a bare
interpreter, so it imports the standard library only. The decision is a pure function of what it is handed;
the date is the UTC day of the call unless a test hands one in.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class SprintProjectPolicy:
    """The shape of a sprint project's name, with its start and end dates as groups."""

    name_pattern: re.Pattern[str]


def load_policy(
    raw: object, source: Path, error: type[Exception]
) -> SprintProjectPolicy:
    """Read the ``sprint_project`` object, or raise ``error``.

    No default: a missing or malformed object refuses every create until it is repaired, rather than
    quietly retiring the rule.
    """
    pattern = raw.get("name_pattern") if isinstance(raw, dict) else None
    if not isinstance(pattern, str) or not pattern:
        raise error(
            f"{source}: 'sprint_project.name_pattern' must be a non-empty regex string, got {raw!r}"
        )
    try:
        compiled = re.compile(pattern)
    except re.error as exc:
        raise error(
            f"{source}: 'sprint_project.name_pattern' {pattern!r} is not a regex ({exc})"
        ) from exc
    if not {"start", "end"} <= set(compiled.groupindex):
        raise error(
            f"{source}: 'sprint_project.name_pattern' declares no 'start' and 'end' group, "
            "so a matching name carries no window to judge"
        )
    return SprintProjectPolicy(name_pattern=compiled)


def is_current_sprint(
    name: str, policy: SprintProjectPolicy, today: date | None = None
) -> bool:
    """True when ``name`` is a sprint project whose own window holds ``today`` (UTC day of the call)."""
    found = policy.name_pattern.match(name.strip())
    if found is None:
        return False
    try:
        start = date.fromisoformat(found.group("start"))
        end = date.fromisoformat(found.group("end"))
    except ValueError:
        return False
    return start <= (today or datetime.now(UTC).date()) <= end


def project_findings(
    tool_input: Mapping[str, object],
    policy: SprintProjectPolicy,
    finding: Callable[..., object],
    today: date | None = None,
) -> list[object]:
    """The project_set finding when the create names a project other than the current sprint's."""
    project, project_id = tool_input.get("project"), tool_input.get("projectId")
    named = project not in (None, "") or project_id not in (None, "")
    if not named or (
        project_id in (None, "")
        and isinstance(project, str)
        and is_current_sprint(project, policy, today)
    ):
        return []
    return [
        finding(
            code="project_set",
            field="project",
            reason=(
                "the create sets a project that is not the current sprint's; the operator ruled "
                "(2026-09-30T14:30:05Z, ticket=OMN-17427, and 2026-11-20T13:52:49Z) that a new ticket "
                "is created in the current sprint's project or in the Backlog with NO project"
            ),
            fix=(
                "pass the current sprint's project by name (the one named 'Sprint <start> \u2192 <end>' whose "
                "dates hold today) with its milestone and due date, or remove project and projectId and "
                "leave the state at Backlog; a projectId is never admitted"
            ),
        )
    ]
