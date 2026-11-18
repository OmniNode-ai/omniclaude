# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Sprint-project admission for ticket creates (OMN-25623).

RULING 2026-11-18T12:17:41Z (lane=orchestrator-31d9-swarm, ticket=OMN-24562)
amends the 2026-09-30T14:30:05Z default for lane creates: the tickets being
closed are the actual sprint's, because that sprint is the work being pulled
from. By 2026-11-18T12:17:41Z there were 250+ lane-minted tickets in
Backlog with no project while the current sprint went unworked, because the
create gate's rule 2 (project_set) refused every project on every create
and so re-created that backlog on every mint. A create from a lane or node
context therefore lands in the sprint project that holds today's date, with
its milestone and a due date inside the sprint window; a person's create keeps
the 2026-09-30 default (Backlog, no project) unchanged.

What this module refuses, for a lane or node create (an admission):

* ``sprint_missing`` -- the create carries neither ``project`` nor ``projectId``;
* ``sprint_project_not_today`` -- it carries a project that is not the sprint
  project holding today's date: the tracker resolved the sprint and this is
  neither its id nor its name, or the project names its own ``Sprint <start>
  to <end>`` window and today falls outside it;
* ``sprint_unverified`` -- the project does not describe a sprint window and
  the tracker did not answer, so nothing can tell whether it is today's
  sprint. Fail-closed on purpose, the module boundary's own rule for creates:
  an unverifiable create is refused, never assumed clean. A machine with no
  read credential can still mint with the self-describing project name;
* ``sprint_milestone_missing`` / ``sprint_due_date_missing`` -- a create that
  carries the sprint project but no milestone, or no parseable due date;
* ``sprint_due_date_outside`` -- a due date outside the sprint window.

For a person's create (no admission) this module keeps the old rule 2 exactly:
project_set when a project is named.

Stdlib only: the guard loads this module by path under a bare interpreter
with no ``omniclaude`` package, like ``handler_lane_intake``. The decisions
are pure functions of what they are handed; the network lives only in
:func:`fetch_sprint_project`.
"""

from __future__ import annotations

import datetime as _dt
import http.client
import json
import re
import urllib.parse
from collections.abc import Mapping
from typing import NamedTuple

#: The tracker's single documented GraphQL endpoint, read-only project lookups
#: from a PreToolUse decision core that is standard-library-only by
#: construction (same endpoint and same reasoning as the guard's rule 9).
_PROJECTS_QUERY = (
    "query{projects(first:100,orderBy:updatedAt){nodes{id name startDate targetDate}}}"
)

#: The sprint projects' self-describing name form. The board's sprints are
#: named ``Sprint 2026-11-16 to 2026-11-22``, so the name itself carries the
#: window and a guard with no tracker answer can still read it.
_SPRINT_NAME = re.compile(
    r"^\s*sprint\s+(?P<start>\d{4}-\d{2}-\d{2})\s+to\s+(?P<end>\d{4}-\d{2}-\d{2})\s*$",
    re.IGNORECASE,
)

_FIELD_SPELLINGS = (("project", "projectId"), ("milestone", "milestoneId"))

_RULING = (
    "RULING 2026-11-18T12:17:41Z (ledger RULING lane=orchestrator-31d9-swarm "
    "ticket=OMN-24562): lanes pull from and close the sprint's tickets, so a "
    "lane create lands in the sprint project holding today's date"
)
_OLD_RULING = (
    "the operator ruled (2026-09-30T14:30:05Z, ledger RULING lane=orchestrator-0c2f "
    "ticket=OMN-17427) that every new ticket is created in the Backlog with NO project"
)


class SprintProject(NamedTuple):
    """The sprint project holding today's date, as the tracker reports it."""

    id: str
    name: str
    start: _dt.date
    end: _dt.date


def _present(value: object) -> str:
    """A field counts as present only when it carries a non-blank string."""
    return value.strip() if isinstance(value, str) and value.strip() else ""


def _carried(tool_input: Mapping[str, object], spellings: tuple[str, ...]) -> str:
    """The first present spelling of one logical field, or ``""``."""
    for field in spellings:
        carried = _present(tool_input.get(field))
        if carried:
            return carried
    return ""


def _parse_day(text: str) -> _dt.date | None:
    try:
        return _dt.date.fromisoformat(text.strip()[:10])
    except (ValueError, AttributeError, TypeError):
        return None


def _window(
    name: str, start: object = None, end: object = None
) -> tuple[_dt.date, _dt.date] | None:
    """A project's ``[start, end]`` window, from its dates or its name.

    The explicit ``startDate``/``targetDate`` win; a project with neither still
    resolves through the ``Sprint <start> to <end>`` name form, so the name a
    lane carries in the create itself can be read without the tracker.
    """
    first = _parse_day(start) if isinstance(start, str) else None
    last = _parse_day(end) if isinstance(end, str) else None
    if first is None or last is None:
        match = _SPRINT_NAME.match(name or "")
        if match is None:
            return None
        first = _parse_day(match.group("start"))
        last = _parse_day(match.group("end"))
    if first is None or last is None or last < first:
        return None
    return (first, last)


def sprint_from_projects(
    nodes: list[Mapping[str, object]], today: _dt.date
) -> SprintProject | None:
    """The project whose window holds ``today``, latest end first.

    Zero matches resolves to ``None``. Overlapping windows should not exist;
    when they do, the latest-ending one wins so the answer is deterministic
    and says one project, never a coin flip between two.
    """
    best: SprintProject | None = None
    for node in nodes:
        carried = _window(
            str(node.get("name") or ""),
            node.get("startDate"),
            node.get("targetDate"),
        )
        if carried is None or not (carried[0] <= today <= carried[1]):
            continue
        candidate = SprintProject(
            id=str(node.get("id") or ""),
            name=str(node.get("name") or ""),
            start=carried[0],
            end=carried[1],
        )
        if best is None or candidate.end > best.end:
            best = candidate
    return best


def fetch_sprint_project(
    api_key: str, url: str, timeout: float
) -> SprintProject | None:
    """Today's sprint project from the tracker, or ``None`` when it will not say.

    The caller hands in the endpoint and the timeout: the baselined guard
    owns those literals. Every failure collapses to ``None`` on purpose (the
    guard's rule 9 precedent): a transport error, a non-200, a GraphQL error
    body and an unparseable response are all "the tracker did not tell us".
    """
    if not api_key:
        return None
    target = urllib.parse.urlsplit(url)
    body = json.dumps({"query": _PROJECTS_QUERY})
    headers = {"Authorization": api_key, "Content-Type": "application/json"}
    try:
        connection = http.client.HTTPSConnection(target.netloc, timeout=timeout)
        try:
            connection.request("POST", target.path or "/", body, headers)
            response = connection.getresponse()
            if response.status != 200:
                return None
            raw = response.read()
        finally:
            connection.close()
    except (http.client.HTTPException, OSError):
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if payload.get("errors"):
        return None
    nodes = (payload.get("data") or {}).get("projects", {}).get("nodes")
    if not isinstance(nodes, list):
        return None
    return sprint_from_projects(nodes, _dt.datetime.now(_dt.UTC).date())


def resolve_sprint_project(
    api_key: str, override: str | None, url: str, timeout: float
) -> SprintProject | None:
    """The sprint project: a test's declared one, else the tracker's answer.

    ``override`` is the guard's ``--sprint-project`` (tests only): a JSON
    object with ``name`` and optional ``startDate``/``targetDate``/``id``, or
    the word ``none`` for "the tracker will not answer".
    """
    if override is None:
        return fetch_sprint_project(api_key, url, timeout)
    if override.strip().lower() == "none":
        return None
    raw = json.loads(override)
    window = _window(
        str(raw.get("name") or ""),
        raw.get("startDate"),
        raw.get("targetDate"),
    )
    if window is None:
        raise ValueError(f"--sprint-project {override!r} names no sprint window")
    return SprintProject(
        id=str(raw.get("id") or ""),
        name=str(raw.get("name") or ""),
        start=window[0],
        end=window[1],
    )


def _finding(code: str, field: str, reason: str, fix: str) -> dict[str, str]:
    return {"code": code, "field": field, "reason": reason, "fix": fix}


def project_findings(
    tool_input: Mapping[str, object],
    admission: object,
    sprint: SprintProject | None,
    today: _dt.date | None = None,
) -> list[dict[str, str]]:
    """Rule 2's verdict on one create: the sprint rules for a lane, the old
    no-project rule for a person. ``admission`` is the lane-intake admission
    (``None`` for a person's interactive session); ``sprint`` is the resolved
    sprint project or ``None`` when the tracker did not answer."""
    carried = _carried(tool_input, _FIELD_SPELLINGS[0])
    if admission is None:
        if not carried:
            return []
        return [
            _finding(
                "project_set",
                "project",
                f"the create sets a project, but {_OLD_RULING}",
                "remove project and projectId from the create; leave the state "
                "at Backlog. A parent epic link is fine. Moving a person's "
                "ticket into a sprint project is the operator's call, made "
                "later with an update, never at creation",
            )
        ]
    today = today or _dt.datetime.now(_dt.UTC).date()
    out: list[dict[str, str]] = []
    if not carried:
        out.append(
            _finding(
                "sprint_missing",
                "project",
                f"this lane create names no sprint project, but {_RULING}. "
                "Every lane mint with no project re-creates the 250+-ticket "
                "unprojected backlog this rule closed",
                "resolve the sprint project holding today's date from the "
                "project list (the projects are named 'Sprint <start> to "
                "<end>') and pass it as project or projectId, with its "
                "milestone and a due date inside the sprint window",
            )
        )
    else:
        window = _window(carried)
        if sprint is not None and carried not in (sprint.id, sprint.name):
            out.append(
                _finding(
                    "sprint_project_not_today",
                    "project",
                    f"the tracker resolves today's sprint project to "
                    f"'{sprint.name}' ({sprint.start} to {sprint.end}), and "
                    f"this create carries {carried!r}, which is not it. "
                    f"{_RULING}",
                    f"pass the sprint project holding today's date: id "
                    f"{sprint.id!r} or the name {sprint.name!r}",
                )
            )
        elif sprint is None:
            if window is None:
                out.append(
                    _finding(
                        "sprint_unverified",
                        "project",
                        f"this lane create carries {carried!r}, which names no "
                        "'Sprint <start> to <end>' window, and the tracker did "
                        "not answer, so nothing can tell whether it is today's "
                        "sprint project. An unverifiable create is refused, "
                        "never assumed clean",
                        "pass the sprint project by its self-describing name "
                        "('Sprint <start> to <end>' holding today's date) or "
                        "retry where the tracker answers",
                    )
                )
            elif not (window[0] <= today <= window[1]):
                out.append(
                    _finding(
                        "sprint_project_not_today",
                        "project",
                        f"this create carries {carried!r}, whose window "
                        f"({window[0]} to {window[1]}) does not hold today "
                        f"({today}). {_RULING}",
                        "pass the sprint project whose window holds today's date",
                    )
                )
    if not carried:
        # AC2's field rules read only a create that carries a project at all.
        return out
    milestone = _carried(tool_input, _FIELD_SPELLINGS[1])
    if not milestone:
        out.append(
            _finding(
                "sprint_milestone_missing",
                "milestone",
                f"this lane create carries the sprint project but no milestone, "
                f"so the sprint's milestone field stays empty. {_RULING}",
                "pass the sprint project's milestone (milestone or milestoneId) "
                "with the project",
            )
        )
    due = _carried(tool_input, ("dueDate",))
    due_day = _parse_day(due) if due else None
    if due_day is None:
        out.append(
            _finding(
                "sprint_due_date_missing",
                "dueDate",
                "this lane create carries the sprint project but no parseable "
                "due date, so nothing ties the ticket to the sprint's window",
                "pass dueDate as an ISO date inside the sprint window",
            )
        )
    else:
        window = _window(carried) or (
            (sprint.start, sprint.end) if sprint is not None else None
        )
        if window is not None and not (window[0] <= due_day <= window[1]):
            out.append(
                _finding(
                    "sprint_due_date_outside",
                    "dueDate",
                    f"the due date {due_day} falls outside the sprint window "
                    f"({window[0]} to {window[1]})",
                    f"pass a due date between {window[0]} and {window[1]}",
                )
            )
    return out


__all__ = [
    "SprintProject",
    "fetch_sprint_project",
    "project_findings",
    "resolve_sprint_project",
    "sprint_from_projects",
]
