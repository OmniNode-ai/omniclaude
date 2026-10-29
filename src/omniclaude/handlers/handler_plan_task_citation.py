# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Plan-task citation of the ticket-creation guard (OMN-17942, lane intake).

A create that cites a task of an approved plan is admitted without spending the
lane- and node-created daily budget (``lane_intake.daily_budget``). The
exemption is *verifiable*, not asserted: the create's description carries one
line of its own naming a plan file in the plan repository and a task id,
and this module confirms, from the local clone's ``origin/main`` ref with no
network call, that the plan file is there and that the task id opens a task line
in it. Where the clone is comes from a contract overlay, never from this public
module, the policy or the environment: the policy names the overlay and the key,
the existing overlay resolver (``resolve_skill_overlay``) finds the overlay file,
and the key holds the clone's location relative to the workspace root. A citation that cannot be confirmed is refused with a message naming what
was missing, and is not silently treated as a create that spends the budget.

The vocabulary (the citation line, the path shape, the task-line shapes, the
ref, the overlay and its keys, the reason and the ruling that granted the exemption)
is ``ticket_creation_policy.json``'s ``lane_intake.plan_task_exemption`` object;
this module spells none of it. There is no wildcard and no 'exempt' marker: the
only way into the exemption is a plan task that exists at the ref.

Like its sibling ``handler_lane_intake`` this module is loaded by path by a hook
that runs under a bare interpreter, so it imports the standard library at module
level; the overlay file is read with PyYAML, imported where it is read, and a
hook interpreter without it refuses naming that. The decisions are pure functions
of what they are handed; the filesystem, the overlay and ``git`` are touched only
by :func:`verify`.
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from types import ModuleType
from typing import NamedTuple

#: ``git show`` of one plan file is a local object read; this bounds a wedged one.
_GIT_TIMEOUT_SECONDS = 15
#: How many of a plan's task ids a refusal lists, so the author can see the shape.
_TASKS_SHOWN = 12
#: The one overlay resolver every overlay-configured skill shares, from
#: ``src/omniclaude/handlers/<this file>`` to the plugin's ``scripts``. Found
#: beside the checkout this module is loaded from, as ``handler_lane_intake``
#: finds the hook library; a miss refuses rather than searching elsewhere.
_OVERLAY_RESOLVER_PY = (
    Path(__file__).resolve().parents[3]
    / "plugins/onex/scripts/resolve_skill_overlay.py"
)


class PlanTaskExemption(NamedTuple):
    """The ``lane_intake.plan_task_exemption`` object of the ticket-creation policy."""

    reason: str
    ruling_stamp: str
    ref: str
    overlay: str
    plan_repo_key: str
    workspace_root_key: str
    citation_line: re.Pattern[str]
    path_pattern: re.Pattern[str]
    task_line_patterns: tuple[re.Pattern[str], ...]


class PlanCitation(NamedTuple):
    """The plan file and task id a create cites."""

    path: str
    task: str


def _text(raw: Mapping[str, object], key: str, source: str) -> str:
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


def load(raw: object, source: str) -> PlanTaskExemption:
    """Read the ``plan_task_exemption`` object, or raise ``ValueError``.

    Raised rather than defaulted: a policy that cannot be read is an unknown
    policy, and an unknown policy that admits everything is a gate reporting
    green while enforcing nothing.
    """
    if not isinstance(raw, dict):
        raise ValueError(f"{source}: lane_intake.plan_task_exemption must be an object")
    where = raw.get("plan_repo_overlay")
    if not isinstance(where, dict):
        raise ValueError(
            f"{source}: plan_task_exemption.plan_repo_overlay must be an object "
            "naming the overlay and the keys that locate the plan repository"
        )
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
        overlay=_text(where, "overlay", f"{source}: plan_repo_overlay"),
        plan_repo_key=_text(where, "plan_repo_key", f"{source}: plan_repo_overlay"),
        workspace_root_key=_text(
            where, "workspace_root_key", f"{source}: plan_repo_overlay"
        ),
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


def _resolver() -> ModuleType:
    """The shared overlay resolver, loaded by path; ``OSError``/``ImportError`` if it cannot be."""
    spec = importlib.util.spec_from_file_location(
        "resolve_skill_overlay", _OVERLAY_RESOLVER_PY
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"overlay resolver not loadable: {_OVERLAY_RESOLVER_PY}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _one_line(text: str) -> str:
    return "; ".join(part.strip() for part in text.splitlines() if part.strip())


def _overlay_value(overlay: Mapping[str, object], key: str, where: str) -> str:
    value = overlay.get(key)
    if not isinstance(value, str) or not value.strip():
        raise LookupError(f"{where} has no non-blank '{key}' key")
    return value.strip()


def _locate(
    exemption: PlanTaskExemption, environ: Mapping[str, str]
) -> tuple[str, str]:
    """``(clone, "")`` for the plan repository, else ``("", what is missing)``.

    The overlay named by the policy is found by the shared resolver, and its
    ``plan_repo_key`` holds the clone relative to the directory its
    ``workspace_root_key`` names an environment variable for. There is no
    environment fallback and no default path: a missing overlay, key or root
    refuses, naming the overlay key that would supply it.
    """
    key = f"'{exemption.plan_repo_key}' key of the '{exemption.overlay}' overlay"
    try:
        resolver = _resolver()
    except (OSError, ImportError, SyntaxError) as exc:
        return (
            "",
            f"the {key} cannot be read, the overlay resolver is unavailable ({exc})",
        )
    try:
        overlay_path = resolver.resolve_overlay_path(exemption.overlay)
    except resolver.OverlayNotResolved as exc:
        return "", f"the {key} cannot be read: {_one_line(str(exc))}"
    try:
        import yaml

        document = yaml.safe_load(overlay_path.read_text(encoding="utf-8"))
    except ImportError as exc:
        return "", f"the {key} cannot be read, PyYAML is not importable ({exc})"
    except (OSError, yaml.YAMLError) as exc:
        return "", f"the {key} cannot be read from {overlay_path} ({exc})"
    if not isinstance(document, dict):
        return "", f"{overlay_path} is not a mapping, so it holds no {key}"
    try:
        relative = _overlay_value(document, exemption.plan_repo_key, str(overlay_path))
        root_env = _overlay_value(
            document, exemption.workspace_root_key, str(overlay_path)
        )
    except LookupError as exc:
        return "", f"the {key} is missing: {exc}"
    root = environ.get(root_env, "").strip()
    if not root.startswith("/"):
        return "", (
            f"the {key} is relative to the workspace root, but {root_env} (named by "
            f"'{exemption.workspace_root_key}' in {overlay_path}) is not set to an "
            "absolute path"
        )
    if relative.startswith("/"):
        return "", f"the {key} in {overlay_path} must be relative to the workspace root"
    clone = str(Path(root) / relative)
    # No GIT_DIR and friends: a stray variable would point git at another repository.
    clean = {k: v for k, v in environ.items() if not k.startswith("GIT_")}
    try:
        probe = subprocess.run(
            ["git", "-C", clone, "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT_SECONDS,
            env=clean,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return "", f"the {key} names {clone}, which git could not probe ({exc})"
    if probe.returncode != 0 or probe.stdout.strip() != "true":
        return "", f"the {key} names {clone}, which is not a git work tree"
    return clone, ""


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
    clone, missing = _locate(exemption, environ)
    if not clone:
        return (
            f"no plan-repository clone resolves to check the plan against ({missing}), "
            f"so '{path}' cannot be confirmed at the ref"
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
