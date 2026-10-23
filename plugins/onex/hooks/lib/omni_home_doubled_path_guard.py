#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Refuse a path doubled onto the registry root (OMN-18607).

``$OMNI_HOME`` IS the ``omni_home`` repository root on this fleet. A lane that
followed `$OMNI_HOME/CLAUDE.md:169` ("Run from $OMNI_HOME/omni_home (repo
root)", wrong, removed in omni_home#365) created a stray untracked
``$OMNI_HOME/omni_home/`` directory, and two lanes then wrote scratch output
into it over three weeks before anyone noticed
(``.claude_scratch/reports/scrubber-placeholder-sweep-1835.md`` 2026-09-16,
``.onex_state/omn16191-tier0-proof/`` 2026-08-19). A second, independent lane
hit the same doubling on 2026-09-16
(``docs/tracking/ROLLING_WORK_LEDGER.md:3695``). The directory was never
git-added, so no repo-scoped CI gate could see it.

Removing the wrong instruction does not stop the next lane typing the doubled
segment from stale memory or a stale doc. This core does, for the Bash command
line and for a Write/Edit/MultiEdit/NotebookEdit target path.

The check is ANCHORED, never a substring match: a path is refused only when it
resolves INSIDE ``$OMNI_HOME/omni_home``. A path that merely carries the
characters ``omni_home/omni_home`` somewhere else -- a worktree for a ticket
named after the repo, say ``$OMNI_HOME/omni_worktrees/omni_home/omni_home`` --
is a real place and is admitted. With ``OMNI_HOME`` unset there is nothing to
anchor to and nothing is refused: this core never guesses the root.

Stdlib only, like every module on the hook fast path.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

#: The segment that must not follow the registry root.
DOUBLED_SEGMENT = "omni_home"

#: Words in a Bash command that could be a path. Deliberately generous: it
#: over-collects and every candidate is then anchored, so a word that is not a
#: path under the registry root costs nothing.
_PATH_WORD = re.compile(
    r"[A-Za-z0-9_${}~./@+=:,-]*" + DOUBLED_SEGMENT + r"[A-Za-z0-9_${}~./@+=:,-]*"
)

#: The tool inputs that carry a target path, per tool.
_PATH_INPUTS: dict[str, tuple[str, ...]] = {
    "Write": ("file_path",),
    "Edit": ("file_path",),
    "MultiEdit": ("file_path",),
    "NotebookEdit": ("notebook_path", "file_path"),
}

GATE_BIT_NAME = "BASH_GUARD"
TICKET = "OMN-18607"


@dataclass(frozen=True)
class Decision:
    """The verdict on one tool call."""

    blocked: bool
    reason: str = ""
    notes: tuple[str, ...] = field(default=())


def _expand(candidate: str, omni_home: str) -> str:
    """``candidate`` with ``$OMNI_HOME`` and ``~`` resolved, textually."""
    out = candidate.strip().strip("'\"")
    for spelling in ("${OMNI_HOME}", "$OMNI_HOME"):
        out = out.replace(spelling, omni_home)
    if out.startswith("~"):
        out = os.path.expanduser(out)
    return out


def _absolute_forms(expanded: str, cwd: str) -> list[str]:
    """Every absolute spelling of ``expanded`` worth anchoring, normalised.

    A relative path is read against the tool call's working directory, which is
    what the shell would do.
    """
    forms: list[str] = []
    if expanded.startswith("/"):
        forms.append(os.path.normpath(expanded))
    elif cwd:
        forms.append(os.path.normpath(os.path.join(cwd, expanded)))
    return forms


def _is_inside(path: str, root: str) -> bool:
    """True when ``path`` is ``root`` itself or sits under it, by segments."""
    if not root:
        return False
    try:
        parts = PurePosixPath(path).parts
        root_parts = PurePosixPath(os.path.normpath(root)).parts
    except (TypeError, ValueError):
        return False
    return parts[: len(root_parts)] == root_parts


def _doubled_roots(omni_home: str) -> list[str]:
    """``$OMNI_HOME/omni_home``, in each spelling the filesystem may hand back.

    ``realpath`` is included because ``/tmp`` and ``/var`` are symlinks on
    macOS, so a fixture root reaches the guard under two names.
    """
    roots: list[str] = []
    for base in (os.path.normpath(omni_home), os.path.realpath(omni_home)):
        doubled = os.path.join(base, DOUBLED_SEGMENT)
        if doubled not in roots:
            roots.append(doubled)
    return roots


def _candidates(payload: dict, omni_home: str) -> list[str]:
    """The path-shaped strings this tool call would act on."""
    tool = payload.get("tool_name") or ""
    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return []
    out: list[str] = []
    if tool == "Bash":
        command = tool_input.get("command") or ""
        if isinstance(command, str):
            out.extend(m.group(0) for m in _PATH_WORD.finditer(command) if m.group(0))
    for key in _PATH_INPUTS.get(tool, ()):  # Write/Edit/MultiEdit/NotebookEdit
        value = tool_input.get(key)
        if isinstance(value, str) and value:
            out.append(value)
    return out


def evaluate_payload(payload: dict, environ: dict, cwd: str = "") -> Decision:
    """The verdict for one PreToolUse payload."""
    omni_home = (environ.get("OMNI_HOME") or "").strip()
    if not omni_home:
        return Decision(
            blocked=False, notes=("OMNI_HOME is unset; no root to anchor to",)
        )
    roots = _doubled_roots(omni_home)
    where = payload.get("cwd") or cwd or ""
    for candidate in _candidates(payload, omni_home):
        expanded = _expand(candidate, omni_home)
        if DOUBLED_SEGMENT not in expanded:
            continue
        for form in _absolute_forms(expanded, where):
            for root in roots:
                if not _is_inside(form, root):
                    continue
                corrected = (
                    str(
                        Path(os.path.normpath(omni_home))
                        / Path(form).relative_to(Path(os.path.normpath(root)))
                    )
                    if _is_inside(form, os.path.normpath(root))
                    else os.path.normpath(omni_home)
                )
                return Decision(
                    blocked=True,
                    reason=(
                        f"BLOCKED: this call targets {form}, which doubles the repo "
                        f"root ({TICKET}). $OMNI_HOME is already the omni_home repo "
                        "root, so drop the extra 'omni_home/' segment: the path you "
                        f"mean is {corrected}. $OMNI_HOME={os.path.normpath(omni_home)}. "
                        "A doubled path is not a worktree and nothing git-tracks it: "
                        "two lanes wrote scratch output into one for three weeks "
                        "before anyone noticed (2026-08-19 and 2026-09-16). "
                        f"To disable this guard: onex hooks disable {GATE_BIT_NAME}"
                    ),
                )
    return Decision(
        blocked=False,
        notes=("no path anchored at $OMNI_HOME/omni_home",),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        print(json.dumps({"decision": "allow", "notes": ["unparseable payload"]}))
        return 0
    if not isinstance(payload, dict):
        print(json.dumps({"decision": "allow", "notes": ["payload is not an object"]}))
        return 0
    decision = evaluate_payload(payload, dict(os.environ), os.getcwd())
    if decision.blocked:
        print(json.dumps({"decision": "block", "reason": decision.reason}))
        return 2
    print(json.dumps({"decision": "allow", "notes": list(decision.notes)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
