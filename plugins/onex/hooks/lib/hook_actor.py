# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Which agent host produced a hook event (OMN-18704).

One journal, two producers. Claude Code and Codex CLI both register the same
bus-mirror entrypoints, so every record now carries the host that emitted it.

Why the actor is declared and never inferred
--------------------------------------------
Measured on the operator Mac, 2026-09-18, by a probe hook registered in an
isolated ``CODEX_HOME`` that wrote its own stdin and environment to disk:

* A Codex hook process inherits the environment of whatever launched Codex.
  Started from a Claude Code session, its hooks run with ``CLAUDECODE=1``,
  ``CLAUDE_CODE_SESSION_ID`` and ``CLAUDE_CODE_ENTRYPOINT`` set -- and with no
  ``CODEX_*`` variable of Codex's own. Environment sniffing reports the wrong
  answer, confidently.
* The stdin shapes overlap where it matters. Codex's ``SessionEnd`` input
  carries neither ``model`` nor ``turn_id``, so the fields that separate the
  two hosts elsewhere are simply absent on the one event that would need them.

So the only sound signal is the registration that the host itself resolved:
the Codex ``hooks.json`` invokes the shared scripts with ``--actor codex``.
This module owns the allowlist so the shell side never has to.

An unrecognised value resolves to ``ACTOR_UNKNOWN`` rather than to the Claude
default. A record mislabelled ``claude`` is indistinguishable from a correct
one; a record labelled ``unknown`` is visibly wrong, which is the point.
"""

from __future__ import annotations

import os

__all__ = [
    "ACTOR_CLAUDE",
    "ACTOR_CODEX",
    "ACTOR_ENV_VAR",
    "ACTOR_UNKNOWN",
    "KNOWN_ACTORS",
    "resolve_actor",
]

ACTOR_CLAUDE = "claude"
ACTOR_CODEX = "codex"
ACTOR_UNKNOWN = "unknown"

#: The hosts this journal knows how to attribute a record to. Adding one means
#: shipping its registration and its row in ``hook_actor_envelope.yaml`` in the
#: same change -- a name here with no contract row is an unreadable record.
KNOWN_ACTORS = frozenset({ACTOR_CLAUDE, ACTOR_CODEX})

ACTOR_ENV_VAR = "ONEX_HOOK_ACTOR"


def resolve_actor(
    declared: str | None = None,
    env: dict[str, str] | None = None,
) -> str:
    """Resolve the emitting host from the registration that invoked the hook.

    Precedence, highest first:

    1. ``declared`` -- the ``--actor`` value on the hook's command line. This
       is what the Codex ``hooks.json`` sets, and it is the authority.
    2. ``ONEX_HOOK_ACTOR`` in the environment -- the same declaration made as a
       command prefix, which Codex also supports because it runs hook commands
       through a shell.
    3. ``claude`` -- the Claude Code registration predates this field and does
       not declare, so an absent declaration means the Claude host.

    A present-but-unrecognised value at either level yields ``unknown``. It is
    never quietly promoted to the default: an unreadable declaration is a
    different fact from an absent one.
    """
    environ = os.environ if env is None else env

    candidate = (declared or "").strip()
    if not candidate:
        candidate = (environ.get(ACTOR_ENV_VAR) or "").strip()
    if not candidate:
        return ACTOR_CLAUDE

    normalized = candidate.lower()
    return normalized if normalized in KNOWN_ACTORS else ACTOR_UNKNOWN
