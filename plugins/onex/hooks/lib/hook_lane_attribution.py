#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Resolve which LANE a hook event belongs to (OMN-18609).

Why this exists
---------------
The cloud hook ledger (``public.hook_events`` in ``omnidash_analytics``) held
83,067 rows when the first reader of it was built, and **not one of them could
be attributed to a lane**. The union of payload keys over every
``tool-executed`` row is ``causation_id, correlation_id, duration_ms,
emitted_at, entity_id, hook_source, interrupted, redaction_state,
schema_version, session_id, tool_name, working_directory`` -- and
``correlation_id``, ``run_id``, ``entity_id`` and ``session_id`` all carry the
*same* value, because ``post_tool_use_bus_mirror.sh`` passes the session id as
the correlation id. They are one field under four names.

That leaves ``working_directory``, which is ``basename(cwd)``: 81,658 of those
83,067 rows carry the basename of the workspace root itself. It separates
nothing.

So a ledger that is meant to be the primary record of everything we do could
not answer "which lane did this" at all. This module is the missing operand.

What it resolves against, and why not by import
-----------------------------------------------
The authority is the existing lane-identity registry written by
``scripts/lane_identity.py`` (OMN-18260): one JSON record per worktree, keyed
by ``sha256(str(worktree.resolve()))[:32]``, held outside every product
repository. This module re-implements only the **read** half of that key, and
deliberately does not import the module that owns it: hooks run under a bare
system interpreter with ``env -u PYTHONPATH``, so an import that works on a
developer's machine is a crash on the hook path. That is the same constraint
the gate-binding grammar records for its own transcription, and the same
stdlib-only rule ``hook_emit_journal`` is held to.

The two halves are pinned against each other by a drift test, which imports
``lane_identity`` (where importing it is safe) and asserts both compute the
same key and read the same record.

The fail direction, which is the whole point
--------------------------------------------
Every failure resolves to an explicit marker, never to a lane name:

* ``registry``   -- a record was found for this path or one of its parents
* ``unresolved`` -- the registry is readable and holds no record for this path
* ``unavailable``-- the registry root itself could not be resolved or read

A hook event that says ``unresolved`` is honest. A hook event that inherited a
neighbouring lane's name would be worse than one carrying no lane at all,
because a drop detector cannot tell a wrong attribution from a right one, and
would report the wrong lane alive on the strength of another lane's work.

Why ``cwd`` alone was not enough, measured
------------------------------------------
The cwd chain below is correct and, on this fleet, never fires. A dispatched
lane does not make its tool calls from its own worktree: the harness reports
the SESSION's directory as ``cwd``, which is the workspace root itself. So the
upward walk's first candidate is the root, the "stop below the root" guard
trips immediately, and every record resolves ``unresolved``. Measured over
4,720 live journal records on 2026-09-18: every one carried ``lane: ""``,
``lane_source: "unresolved"``, ``workspace_path: "."``. The registry is keyed
by worktree; nothing on the emit path ever supplied a worktree.

The operand that DOES identify a lane at emit time is the one OMN-18690 uses
at close time. The harness writes ``agent-<agent id>.meta.json`` beside each
subagent transcript and its ``name`` is the dispatch-time lane name, the same
string :func:`lane_registry.extract_lane_name` records when the lane opens.
The PostToolUse payload carries ``agent_id`` and ``transcript_path``, which is
enough to find it. That is a fact the harness authored, not one the agent can
assert, so it is checked FIRST -- ahead of a worktree registration, which
outlives the lane that wrote it.

**The upward walk stops below the workspace root.** ``lane_identity.resolve``
walks to the filesystem root so a lane working in a subdirectory of its own
worktree still resolves. That is right for a commit trailer and wrong here: if
any lane ever registers the workspace root as its worktree, every tool call on
the machine would attribute to it. This module walks parents only while they
are strictly *below* the workspace root, so the shared root can never become
one lane's answer for the whole fleet.

Refs: OMN-18609; lane registry OMN-18260; the capture path OMN-17224.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

__all__ = [
    "LANE_SOURCE_REGISTRY",
    "LANE_SOURCE_SIDECAR",
    "LANE_SOURCE_UNAVAILABLE",
    "LANE_SOURCE_UNRESOLVED",
    "REGISTRY_SUBDIR",
    "SIDECAR_NAME_KEYS",
    "WORKSPACE_ENV",
    "attribution_fields",
    "record_key",
    "registry_base",
    "resolve_lane",
    "sidecar_lane_name",
    "workspace_relative",
]

#: Environment variable naming the workspace root. Read as a required key by
#: :func:`registry_base` -- a silent default would scatter lookups into an
#: unrelated directory, which reads exactly like "no lane is registered".
WORKSPACE_ENV = "OMNI_HOME"

#: Overrides :data:`WORKSPACE_ENV` when set. Same precedence as
#: ``lane_identity.registry_root_from_env``.
REGISTRY_ROOT_ENV = "ONEX_LANE_REGISTRY_ROOT"

#: The registry lives under ``<workspace>/.onex_state/lane_identity``.
STATE_SUBDIR = ".onex_state"
REGISTRY_SUBDIR = "lane_identity"

LANE_SOURCE_REGISTRY = "registry"
LANE_SOURCE_SIDECAR = "sidecar"
LANE_SOURCE_UNRESOLVED = "unresolved"
LANE_SOURCE_UNAVAILABLE = "unavailable"

#: Keys of the harness's ``agent-<agent id>.meta.json`` sidecar, in the
#: precedence :func:`lane_registry.extract_lane_name` uses at dispatch, so the
#: name a tool call is attributed to is the name the lane was opened and closed
#: under. Read a different key here and one lane's tool calls land under one
#: name while its CLAIM and TERMINAL rows land under another -- which reads to
#: a drop detector as one silent lane plus one unclaimed one. Pinned against
#: ``lane_termination_guard._META_NAME_KEYS`` by a test.
SIDECAR_NAME_KEYS = ("name", "agentType", "description")

#: Where the harness keeps per-project session transcripts. Only consulted when
#: the hook payload carried no ``transcript_path`` to derive the location from.
CLAUDE_PROJECTS_ENV = "CLAUDE_PROJECTS_DIR"

#: Longest lane name carried onto an event, matching the close-time guard.
_LANE_NAME_CHARS = 120

#: Length of the hex digest prefix used as a record filename. Must match
#: ``lane_identity._key``; the drift test asserts it.
_KEY_CHARS = 32


def record_key(worktree: Path) -> str:
    """The registry filename stem for *worktree*.

    Mirrors ``lane_identity._key``. Kept as a separate implementation on
    purpose (see the module docstring) and pinned to it by a drift test.
    """
    return hashlib.sha256(str(worktree.resolve()).encode("utf-8")).hexdigest()[
        :_KEY_CHARS
    ]


def registry_base() -> Path | None:
    """The directory holding lane records, or ``None`` when unresolvable.

    ``None`` rather than an exception: this runs on the hook path, where a
    raise is an operator-visible failure of an unrelated tool call.
    """
    explicit = os.environ.get(REGISTRY_ROOT_ENV)
    if explicit:
        return Path(explicit) / REGISTRY_SUBDIR
    workspace = os.environ.get(WORKSPACE_ENV)
    if not workspace:
        return None
    return Path(workspace) / STATE_SUBDIR / REGISTRY_SUBDIR


def _workspace_root() -> Path | None:
    """The workspace root the upward walk must stay strictly below."""
    explicit = os.environ.get(REGISTRY_ROOT_ENV)
    if explicit:
        # An explicit registry root is a test or alternate-workspace shape;
        # its parent is the workspace it describes.
        try:
            return Path(explicit).resolve().parent
        except OSError:
            return None
    workspace = os.environ.get(WORKSPACE_ENV)
    if not workspace:
        return None
    try:
        return Path(workspace).resolve()
    except OSError:
        return None


def workspace_relative(path: Path) -> str:
    """*path* expressed relative to the workspace root, or its basename.

    Never returns an absolute local path. A hook event travels to a shared
    cloud table that collaborators read, and ``/Users/<someone>`` in it is both
    unresolvable for them and a CLAUDE.md rule 6 violation. A path outside the
    workspace degrades to its basename rather than leaking its parents.
    """
    root = _workspace_root()
    try:
        resolved = path.resolve()
    except OSError:
        return path.name
    if root is not None:
        try:
            return str(resolved.relative_to(root))
        except ValueError:
            pass
    return resolved.name


def _sidecar_candidates(
    transcript_path: str | Path | None,
    session_id: str | None,
    agent_id: str,
) -> list[Path]:
    """Every place this lane's sidecar could be, most authoritative first.

    ``transcript_path`` on a ``PostToolUse`` payload is the PARENT session's
    transcript (``<project>/<session>.jsonl``), and the lane's sidecar sits in
    ``<project>/<session>/subagents/``. Deriving the directory from the
    transcript rather than reconstructing it means this never has to know the
    harness's project-slug rule, which is not a documented contract.

    The second candidate covers a payload whose transcript path is already the
    agent's own, and the third is the fallback when no transcript path was
    supplied at all.
    """
    name = f"agent-{agent_id}.meta.json"
    candidates: list[Path] = []
    if transcript_path:
        transcript = Path(transcript_path)
        # <project>/<session>.jsonl -> <project>/<session>/subagents/
        candidates.append(transcript.with_suffix("") / "subagents" / name)
        # already inside a session directory
        candidates.append(transcript.parent / "subagents" / name)
    if session_id:
        root = os.environ.get(CLAUDE_PROJECTS_ENV)
        base = Path(root) if root else Path.home() / ".claude" / "projects"
        try:
            candidates.extend(base.glob(f"*/{session_id}/subagents/{name}"))
        except OSError:
            pass
    return candidates


def sidecar_lane_name(
    transcript_path: str | Path | None,
    session_id: str | None,
    agent_id: str | None,
) -> str:
    """The dispatch-time lane name from the harness sidecar, or ``""``.

    Returns ``""`` -- never a guess -- when there is no agent id, no sidecar,
    or a sidecar carrying no name. In particular it never falls back to *some*
    sidecar in the session directory: an un-agented tool call is the operator's
    own, and attributing it to whichever lane sorted first would be worse than
    leaving it unattributed. Never raises.
    """
    if not agent_id:
        return ""
    # The id is interpolated into a filename. A value carrying separators would
    # read a file outside the directory this lookup is scoped to, so it is
    # refused rather than sanitised -- a legitimate harness agent id has none.
    if "/" in agent_id or "\\" in agent_id or agent_id in (".", ".."):
        return ""
    for candidate in _sidecar_candidates(transcript_path, session_id, agent_id):
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        for key in SIDECAR_NAME_KEYS:
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[:_LANE_NAME_CHARS]
    return ""


def resolve_lane(
    cwd: str | Path | None,
    *,
    transcript_path: str | Path | None = None,
    session_id: str | None = None,
    agent_id: str | None = None,
) -> tuple[str, str, str]:
    """Return ``(lane, lane_source, ticket)`` for one tool call.

    Two operands, tried in order. The harness sidecar names the lane the
    harness itself dispatched and is checked first; the worktree registry is
    the fallback, and answers for a process that really does work from a
    registered directory. ``lane`` is empty whenever ``lane_source`` is
    :data:`LANE_SOURCE_UNRESOLVED` or :data:`LANE_SOURCE_UNAVAILABLE`.

    ``ticket`` is carried only by the registry operand, which stores one. A
    sidecar does not, so a sidecar-resolved row names its lane and leaves the
    ticket empty rather than inferring one from the lane's spelling -- an
    inference would be indistinguishable, to a reader, from a recorded fact.

    Never raises: this runs on the hook path, where an exception is a visible
    failure of an unrelated tool call.
    """
    lane = sidecar_lane_name(transcript_path, session_id, agent_id)
    if lane:
        return lane, LANE_SOURCE_SIDECAR, ""
    if not cwd:
        return "", LANE_SOURCE_UNRESOLVED, ""
    base = registry_base()
    if base is None:
        return "", LANE_SOURCE_UNAVAILABLE, ""
    try:
        current = Path(cwd).resolve()
    except OSError:
        return "", LANE_SOURCE_UNRESOLVED, ""

    root = _workspace_root()
    for candidate in [current, *current.parents]:
        # Stop below the workspace root. A record registered AT the root would
        # otherwise answer for every directory on the machine.
        if root is not None and candidate == root:
            break
        try:
            record_file = base / f"{record_key(candidate)}.json"
            if not record_file.is_file():
                continue
            data = json.loads(record_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError):
            # An unreadable or malformed record is not a licence to keep
            # walking into a parent's lane: stop and report unresolved.
            return "", LANE_SOURCE_UNRESOLVED, ""
        if not isinstance(data, dict):
            return "", LANE_SOURCE_UNRESOLVED, ""
        lane = data.get("lane")
        if not isinstance(lane, str) or not lane:
            return "", LANE_SOURCE_UNRESOLVED, ""
        ticket = data.get("ticket")
        return lane, LANE_SOURCE_REGISTRY, ticket if isinstance(ticket, str) else ""
    return "", LANE_SOURCE_UNRESOLVED, ""


def attribution_fields(
    cwd: str | Path | None,
    *,
    transcript_path: str | Path | None = None,
    session_id: str | None = None,
    agent_id: str | None = None,
) -> dict[str, str]:
    """The lane fields to merge into a hook-event payload.

    Always returns all four keys. A key that is present-but-empty is readable
    by a projection as "asked and unresolved"; a key that is absent is
    indistinguishable from an emitter that predates this change, and telling
    those apart is what lets a reader know which rows it may key on.
    """
    lane, source, ticket = resolve_lane(
        cwd,
        transcript_path=transcript_path,
        session_id=session_id,
        agent_id=agent_id,
    )
    return {
        "lane": lane,
        "lane_source": source,
        "lane_ticket": ticket,
        "workspace_path": workspace_relative(Path(cwd)) if cwd else "",
    }
