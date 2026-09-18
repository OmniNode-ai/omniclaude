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
    "LANE_SOURCE_UNAVAILABLE",
    "LANE_SOURCE_UNRESOLVED",
    "REGISTRY_SUBDIR",
    "WORKSPACE_ENV",
    "attribution_fields",
    "record_key",
    "registry_base",
    "resolve_lane",
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
LANE_SOURCE_UNRESOLVED = "unresolved"
LANE_SOURCE_UNAVAILABLE = "unavailable"

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


def resolve_lane(cwd: str | Path | None) -> tuple[str, str, str]:
    """Return ``(lane, lane_source, ticket)`` for a tool call made in *cwd*.

    ``lane`` and ``ticket`` are empty strings whenever ``lane_source`` is not
    :data:`LANE_SOURCE_REGISTRY`. Never raises.
    """
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


def attribution_fields(cwd: str | Path | None) -> dict[str, str]:
    """The lane fields to merge into a hook-event payload.

    Always returns all four keys. A key that is present-but-empty is readable
    by a projection as "asked and unresolved"; a key that is absent is
    indistinguishable from an emitter that predates this change, and telling
    those apart is what lets a reader know which rows it may key on.
    """
    lane, source, ticket = resolve_lane(cwd)
    return {
        "lane": lane,
        "lane_source": source,
        "lane_ticket": ticket,
        "workspace_path": workspace_relative(Path(cwd)) if cwd else "",
    }
