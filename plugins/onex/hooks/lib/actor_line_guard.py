#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Actor-line guard for agent-posted Linear comments [OMN-13856].

RULING (docs/tracking/ROLLING_WORK_LEDGER.md:4344, 2026-09-25T15:29:22Z, item
(4), operator verbatim "yes on each"): "agent-posted Linear comments begin
with an actor line naming the posting agent, enforced rather than advised."

This closes the gap the sealed-review audit found (ledger:4259, OMN-13856):
35 seal/review/approve comments on 11 tickets were posted through the Linear
MCP on the operator's own credential (author shows the operator's name,
``onBehalfOf`` null) by Codex CLI subagents, with nothing in the comment text
naming which agent, model or lane actually wrote it. A prose convention
("comments should be signed") is not a control -- it was already the prose
convention and 35 comments crossed it unattributed. The tool seam is the only
place the omission is observable before the comment is posted.

Decision (fail-closed for the tools this guard covers):

1. Not one of the covered Linear comment-posting tools -> ALLOW (nothing to
   check).
2. No ``body`` (or a body that is empty/whitespace-only) -> BLOCK. A
   comment-posting call with no body is not a real posted comment either way,
   and the actor-line requirement cannot be evaluated against nothing.
3. The body's OWN FIRST LINE matches the fixed actor-line shape
   (``actor: <lane or agent> (<model>)``, case-insensitive on the ``actor:``
   token) -> ALLOW.
4. Otherwise -> BLOCK, naming the exact shape and the first line it found.

This is a SHAPE check, not a truth check -- exactly like the rule-18
OPERATOR-CONSENT ledger-row guard: it proves an actor line is present and
well-formed, not that the named actor is the one actually posting. That is
the same posture every other shape-only admission gate in this tree takes
(ticket_creation_guard, done_flip_guard's receipt-field checks).

Covered tools (Linear MCP; see module docstring below for what stays
unenforced): ``mcp__linear-server__save_comment`` (issue / project /
initiative / document / milestone / status-update comments and replies) and
``mcp__linear-server__save_diff_comment`` (PR/diff review comments and
drafts). Both tools' ``id``/``draftId``/``commentId`` edit paths are covered
too -- an edited comment's current body must carry the actor line the same as
a freshly created one; there is no separate "editing an existing comment"
carve-out.

NOT covered by this guard (posting paths that remain unenforced at the tool
seam, surveyed for OMN-13856 item 4 and reported to the operator rather than
silently left open):

* Codex CLI's own Linear MCP tool calls. Codex sessions do not go through
  this Claude Code PreToolUse hook pipeline at all -- ``hooks.json`` in this
  repo is read by the Claude Code plugin runtime only. Codex's equivalent
  surface is its own hook/wrapper config (see ``plugins/onex/hooks/codex/``
  in this repo for what Codex-side hook support exists today) plus the
  ``AGENTS.md`` prose rule this same ruling asks for; there is no committed
  Codex-side enforcement analogous to this file as of this ticket.
* Any script that calls the Linear GraphQL/REST API directly with a raw HTTP
  client (bypassing the MCP tool surface entirely) -- there is no tool-call
  seam for this guard to sit on, and no repo-wide inventory of every such
  script exists.
* ``mcp__linear-server__save_status_update`` / other non-comment Linear
  writes that can carry free-text bodies but are not "comments" in the
  ruling's sense -- out of scope for this ticket, not silently exempted by
  oversight.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from typing import Any

_COMMENT_TOOLS = frozenset(
    {
        "mcp__linear-server__save_comment",
        "mcp__linear-server__save_diff_comment",
    }
)

# "actor: <lane or agent> (<model>)" -- the fixed shape the ruling specifies.
# Case-insensitive on the leading token only; the name and model segments are
# free text (no nested parentheses), matched against the body's first line
# alone so a well-formed actor line anywhere else in the body does not count.
_ACTOR_LINE_RE = re.compile(r"^actor:\s*[^\n()]+\([^\n()]+\)\s*$", re.IGNORECASE)

_ACTOR_LINE_SHAPE_HELP = (
    'actor: <lane or agent> (<model>) -- e.g. "actor: guard-fp-fix (claude-opus-5-5)"'
)


@dataclass(frozen=True)
class Decision:
    """Result of the guard: allow (exit 0) or block (exit 2)."""

    allowed: bool
    reason: str


def first_line(text: str) -> str:
    """Return ``text``'s first line, stripped. Pure function."""
    return (text or "").split("\n", 1)[0].strip()


def has_actor_line(body: str) -> bool:
    """Return True iff ``body``'s first line is a well-formed actor line."""
    return bool(_ACTOR_LINE_RE.match(first_line(body)))


def decide(call: dict[str, Any]) -> Decision:
    """Return the guard decision for a PreToolUse tool call.

    Pure function, no I/O -- the whole check is over the tool-call payload
    already on stdin.
    """
    tool_name = call.get("tool_name", "")
    if tool_name not in _COMMENT_TOOLS:
        return Decision(True, "not_comment_tool")

    params = call.get("tool_input") or {}
    if not isinstance(params, dict):
        return Decision(True, "no_tool_input")

    body = params.get("body")
    body_text = str(body) if body is not None else ""
    if not body_text.strip():
        return Decision(
            False,
            "empty_body: a Linear comment call needs a body, and this guard "
            f"cannot evaluate an actor line against nothing. Required shape: "
            f"{_ACTOR_LINE_SHAPE_HELP}",
        )

    if has_actor_line(body_text):
        return Decision(True, "actor_line_present")

    return Decision(
        False,
        "missing_actor_line: a Linear comment posted by an agent must open "
        f"with an actor line naming the posting agent. Required shape: "
        f"{_ACTOR_LINE_SHAPE_HELP}. First line found: {first_line(body_text)!r}",
    )


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def _load_stdin_call() -> dict[str, Any]:
    try:
        parsed = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def main() -> int:
    """Read a PreToolUse tool call on stdin; exit 0 (allow) or 2 (block)."""
    call = _load_stdin_call()
    decision = decide(call)
    if decision.allowed:
        return 0
    payload = {
        "decision": "block",
        "reason": f"[OMN-13856 actor-line comment guard] {decision.reason}",
    }
    sys.stderr.write(json.dumps(payload) + "\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
