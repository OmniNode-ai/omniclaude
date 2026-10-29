# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Plan-task citation of the ticket-creation guard (OMN-17942, lane intake).

A create that cites a task of an approved plan is admitted without spending the
lane- and node-created daily budget (``lane_intake.daily_budget``). The
exemption is *verifiable*, not asserted: the create's description carries one
line of its own naming a plan file in the plan repository and a task id,
and this module confirms, from the local clone's ``origin/main`` ref with no
network call, that the plan file is there and that the task id opens a task line
in it. A citation that cannot be confirmed is refused with a message naming what
was missing, and is not silently treated as a create that spends the budget.

The vocabulary (the citation line, the path shape, the task-line shapes, the
ref, the clone locations, the reason and the ruling that granted the exemption)
is ``ticket_creation_policy.json``'s ``lane_intake.plan_task_exemption`` object;
this module spells none of it. There is no wildcard and no 'exempt' marker: the
only way into the exemption is a plan task that exists at the ref.

Like its sibling ``handler_lane_intake`` this module is loaded by path by a hook
that runs under a bare interpreter, so it imports the standard library only.
The decisions are pure functions of what they are handed; the filesystem and
``git`` are touched only by :func:`verify`.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Mapping
from pathlib import PurePosixPath
from typing import Any, NamedTuple

#: ``git show`` of one plan file is a local object read; this bounds a wedged one.
_GIT_TIMEOUT_SECONDS = 15
#: How many of a plan's task ids a refusal lists, so the author can see the shape.
_TASKS_SHOWN = 12


class PlanTaskExemption(NamedTuple):
    """The ``lane_intake.plan_task_exemption`` object of the ticket-creation policy."""

    reason: str
    ruling_stamp: str
    ref: str
    clone_env: str
    citation_line: re.Pattern[str]
    path_pattern: re.Pattern[str]
    task_line_patterns: tuple[re.Pattern[str], ...]


class PlanCitation(NamedTuple):
    """The plan file and task id a create cites."""

    path: str
    task: str


def _text(raw: Mapping[str, Any], key: str, source: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{source}: plan_task_exemption.{key} must be non-blank text")
    return value.strip()


def _pattern(text: str, group: str | None, key: str, source: str) -> re.Pattern[str]:
    try:
        compiled = re.compile(text)
    except re.error as exc:
        raise ValueError(f"{source}: plan_task_exemption.{key} is not a regex ({exc})")
    if group is not None and group not in compiled.groupindex:
        raise ValueError(
            f"{source}: plan_task_exemption.{key} needs a (?P<{group}>...) group"
        )
    return compiled


def load(raw: Any, source: str) -> PlanTaskExemption:
    """Read the ``plan_task_exemption`` object, or raise ``ValueError``.

    Raised rather than defaulted: a policy that cannot be read is an unknown
    policy, and an unknown policy that admits everything is a gate reporting
    green while enforcing nothing.
    """
    if not isinstance(raw, dict):
        raise ValueError(f"{source}: lane_intake.plan_task_exemption must be an object")
    patterns = raw.get("task_line_patterns")
    if (
        not isinstance(patterns, list)
        or not patterns
        or not all(isinstance(p, str) and p for p in patterns)
    ):
        raise ValueError(
            f"{source}: plan_task_exemption.task_line_patterns must be a non-empty list"
        )
    return PlanTaskExemption(
        reason=_text(raw, "reason", source),
        ruling_stamp=_text(raw, "ruling_stamp", source),
        ref=_text(raw, "ref", source),
        clone_env=_text(raw, "clone_env", source),
        citation_line=_pattern(
            _text(raw, "citation_line_pattern", source), "path", "citation_line", source
        ),
        path_pattern=_pattern(
            _text(raw, "path_pattern", source), None, "path_pattern", source
        ),
        task_line_patterns=tuple(
            _pattern(p, "id", "task_line_patterns", source) for p in patterns
        ),
    )


def _normalised(text: str) -> str:
    return " ".join(text.split())


def parse(
    description: object, exemption: PlanTaskExemption
) -> tuple[PlanCitation | None, str]:
    """``(citation, error)`` for a create's description.

    ``(None, "")`` when the description cites no plan: that create spends the
    budget as before. An error is a citation line the guard cannot take (two
    citations, or a line naming no task), which refuses.
    """
    if not isinstance(description, str):
        return None, ""
    found: list[PlanCitation] = []
    for line in description.splitlines():
        match = exemption.citation_line.match(line)
        if match is None:
            continue
        task = _normalised(match.groupdict().get("task") or "")
        found.append(PlanCitation(match.group("path").strip(), task))
    if not found:
        return None, ""
    if len(found) > 1:
        return None, (
            f"the description carries {len(found)} plan-task citation lines; a "
            "create cites exactly one plan task"
        )
    if not found[0].task:
        return None, (
            f"the plan citation names the plan file '{found[0].path}' but no task id"
        )
    return found[0], ""


def task_ids(plan_text: str, exemption: PlanTaskExemption) -> list[str]:
    """The task ids a plan opens, in file order, outside fenced code blocks."""
    ids: list[str] = []
    fenced = False
    for line in plan_text.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
            continue
        if fenced:
            continue
        for pattern in exemption.task_line_patterns:
            for match in pattern.finditer(line):
                task = _normalised(match.group("id"))
                if task not in ids:
                    ids.append(task)
    return ids


def _clone(environ: Mapping[str, str], exemption: PlanTaskExemption) -> str:
    """The first candidate directory that is a git work tree, or ``""``."""
    candidates = [environ.get(exemption.clone_env, "").strip()]
    # No GIT_DIR and friends: a stray variable would point git at another repository.
    clean = {k: v for k, v in environ.items() if not k.startswith("GIT_")}
    for candidate in candidates:
        if not candidate or not candidate.startswith("/"):
            continue
        try:
            probe = subprocess.run(
                ["git", "-C", candidate, "rev-parse", "--is-inside-work-tree"],
                capture_output=True,
                text=True,
                timeout=_GIT_TIMEOUT_SECONDS,
                env=clean,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if probe.returncode == 0 and probe.stdout.strip() == "true":
            return candidate
    return ""


def verify(
    citation: PlanCitation,
    exemption: PlanTaskExemption,
    environ: Mapping[str, str],
) -> str:
    """``""`` when the plan file and the task are at the ref, else what is missing.

    Reads ``git show <ref>:<path>`` in the local clone: the ref is kept current
    by the canonical-clone sync, so no fetch and no network call is made here.
    """
    path = citation.path
    parts = PurePosixPath(path).parts
    if (
        exemption.path_pattern.fullmatch(path) is None
        or ".." in parts
        or path.startswith("/")
    ):
        return (
            f"'{path}' is not the path of a plan file in the plan repository "
            f"(it must match {exemption.path_pattern.pattern})"
        )
    clone = _clone(environ, exemption)
    if not clone:
        return (
            "no plan-repository clone resolves to check the plan against "
            f"(set {exemption.clone_env} to the absolute path of the clone), so "
            f"'{path}' cannot be "
            "confirmed at the ref"
        )
    clean = {k: v for k, v in environ.items() if not k.startswith("GIT_")}
    try:
        shown = subprocess.run(
            ["git", "-C", clone, "show", f"{exemption.ref}:{path}"],
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
            env=clean,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return f"the plan file '{path}' could not be read at {exemption.ref} ({exc})"
    if shown.returncode != 0:
        return (
            f"the plan file '{path}' is not at {exemption.ref} in the "
            "plan-repository clone (a plan on an unmerged branch does "
            "not count until it merges)"
        )
    ids = task_ids(shown.stdout, exemption)
    if citation.task not in ids:
        listed = ", ".join(ids[:_TASKS_SHOWN]) or "none"
        more = f" and {len(ids) - _TASKS_SHOWN} more" if len(ids) > _TASKS_SHOWN else ""
        return (
            f"the plan file '{path}' at {exemption.ref} has no task '{citation.task}' "
            f"(tasks it opens: {listed}{more})"
        )
    return ""


def evaluate(
    description: object,
    exemption: PlanTaskExemption,
    environ: Mapping[str, str],
) -> tuple[PlanCitation | None, str]:
    """``(citation, error)``: a confirmed citation has an empty error.

    ``(None, "")`` is a create that cites no plan. A citation that is not
    confirmed comes back as ``(citation, <what was missing>)`` and refuses.
    """
    citation, error = parse(description, exemption)
    if citation is None:
        return None, error
    return citation, verify(citation, exemption, environ)


__all__ = [
    "PlanCitation",
    "PlanTaskExemption",
    "evaluate",
    "load",
    "parse",
    "task_ids",
    "verify",
]
