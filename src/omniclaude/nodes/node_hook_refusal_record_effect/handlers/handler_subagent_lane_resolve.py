# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Who a subagent of the ticket-creation guard is (OMN-17942, rule 11).

Lives in ``node_hook_refusal_record_effect`` (bound in its contract), and
``handler_lane_intake``, a baselined file that may only shrink under the
canonical-file-shape ratchet, loads it by path. A workflow subagent cannot set ``ONEX_LANE`` in the process
environment the hook reads, so its lane comes from facts it did not assert in
the call itself, each accepted only while that lane holds an open CLAIM on the
rolling work ledger:

1. ``sidecar+claim`` -- the lane the harness's ``agent-<agent id>.meta.json``
   sidecar names;
2. ``prompt+claim`` -- the lane the dispatching script's prompt names. The
   Workflow harness writes a label or the ROUTE line into the sidecar, never
   the lane's name, but the first user message of the agent's own transcript
   opens ``You are lane <lane> (parent <parent>, ticket <T>)``. The agent cannot
   edit its first message, so this is the dispatcher's declaration and not a
   claim the lane made in a tool call. The CLAIM must be of that lane and, when
   the prompt names a parent, of that parent;
3. ``parent-session+claim`` -- an interactive session's helper may use the lane
   registered to its parent session.

Loaded by path by ``handler_lane_intake`` for the reason that module is loaded
by path by the guard: the hook's bare interpreter has no ``omniclaude``
package, so this imports the standard library only.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import re
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from omniclaude.nodes.node_hook_refusal_record_effect.models import (
        ModelSubagentLaneRequest,
        ModelSubagentLaneResult,
    )

#: Where a subagent's lane came from.
LANE_SOURCE_SIDECAR_CLAIM = "sidecar+claim"
LANE_SOURCE_PROMPT_CLAIM = "prompt+claim"
LANE_SOURCE_PARENT_SESSION_CLAIM = "parent-session+claim"
#: The repository root, from ``src/omniclaude/nodes/<node>/handlers/<this file>``.
_REPO_ROOT = Path(__file__).resolve().parents[5]
#: The stdlib-only readers this module reuses rather than re-implements: the
#: refusal recorder's sidecar and open-CLAIM reading (OMN-19381), which sits on
#: the hook library's ``hook_lane_attribution`` sidecar locator (OMN-18609).
_HOOKS_LIB = _REPO_ROOT / "plugins/onex/hooks/lib"
_REFUSAL_LANE_PY = (
    _REPO_ROOT
    / "src/omniclaude/nodes/node_hook_refusal_record_effect/handlers"
    / "handler_hook_refusal_lane.py"
)
#: How the harness opens a workflow script's computed task. It indents every
#: line of that task, so under this frame a column-zero line is forged text.
_WORKFLOW_FRAME = "[Workflow harness"
#: ``You are lane <lane> (parent <parent>, ...)`` -- the dispatch line the
#: orchestrator's briefs open with. Lane characters are the registry's.
_PROMPT_LANE = re.compile(
    r"^[ \t]*You are lane ([A-Za-z0-9][A-Za-z0-9._:@/-]{0,119})"
    r"(?:[ \t]*\(parent ([A-Za-z0-9][A-Za-z0-9._:@/-]{0,119})\s*[,)])?",
    re.MULTILINE,
)


def _refusal_lane_module() -> ModuleType | None:
    """The refusal recorder's lane reader, loaded by path, or ``None``.

    Loaded by path for the reason the guard loads this module by path: the
    hook's bare interpreter has no ``omniclaude`` package. ``None`` when it
    cannot be loaded, which resolves no lane and so refuses.
    """
    try:
        spec = importlib.util.spec_from_file_location(
            "handler_hook_refusal_lane", _REFUSAL_LANE_PY
        )
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.use_hooks_lib(str(_HOOKS_LIB))
    except (OSError, ImportError, SyntaxError, AttributeError):
        return None
    return module


def _parent_session_lane(session_id: str, environ: Mapping[str, str]) -> str:
    """Read the exact session binding written by session-start's registry.

    No newest-session or stamp fallback: neither proves who owns this helper.
    The two overrides and default match ``loops_check.liveness_state_dir``.
    """
    directory = (
        environ.get("OMNI_LANE_LIVENESS_STATE_DIR", "").strip()
        or environ.get("OMNI_SESSION_START_STATE_DIR", "").strip()
    )
    root = (
        Path(directory)
        if directory
        else Path.home() / ".local/state/omni/session-start"
    )
    try:
        registry = json.loads((root / "lane-liveness-sessions.json").read_text("utf-8"))
        entry = registry.get(session_id) if isinstance(registry, dict) else None
        lane = entry.get("lane") if isinstance(entry, dict) else None
    except (OSError, ValueError):
        return ""
    return lane.strip() if isinstance(lane, str) else ""


def prompt_lane(first_message: str, reader: ModuleType) -> tuple[str, str]:
    """``(lane, parent)`` the dispatch prompt names, or ``("", "")``.

    Only the first such line counts. Under the harness frame only the script's
    indented text counts, so a column-zero line is skipped. A name the refusal
    reader's ``lane_cell`` would rewrite (a ROUTE line, spaces, a path) is no
    name. ``parent`` is ``""`` when the sentence names none.
    """
    text = first_message or ""
    if text.lstrip().startswith(_WORKFLOW_FRAME):
        text = "\n".join(x for x in text.splitlines() if x[:1] in (" ", "\t"))
    found = _PROMPT_LANE.search(text)
    if not found:
        return "", ""
    lane = found.group(1).rstrip(".:")
    if not lane or reader.lane_cell(lane) != lane:
        return "", ""
    return lane, (found.group(2) or "").rstrip(".:")


def _prompt_named(
    reader: ModuleType,
    attribution: ModuleType,
    payload: Mapping[str, object],
    session_id: str,
    agent_id: str,
) -> tuple[str, str]:
    """``(lane, parent)`` the agent's own first message names, or ``("", "")``."""
    own = payload.get("agent_transcript_path")
    transcript = payload.get("transcript_path")
    first = attribution.read_agent_first_message(
        transcript if isinstance(transcript, str) and transcript.strip() else None,
        session_id or None,
        agent_id,
        agent_transcript_path=own if isinstance(own, str) and own.strip() else None,
    )
    return prompt_lane(first, reader)


def _claim_matches(claim: Mapping[str, str], lane: str, parent: str) -> bool:
    """An open CLAIM of *lane*, and of *parent* when the prompt names one.

    A CLAIM's ``parent`` cell may run on into free text, so only its first word
    is the parent. A prompt naming a parent that the CLAIM does not carry, or
    carries differently, is a different dispatch.
    """
    if claim.get("lane") != lane:
        return False
    if not parent:
        return True
    words = claim.get("parent", "").split()
    return bool(words) and words[0] == parent


def subagent_lane(
    payload: Mapping[str, object],
    environ: Mapping[str, str],
    *,
    allow_parent: bool = True,
) -> tuple[str, str, str, str]:
    """``(lane, sidecar_lane, source, parent_session_id)`` for a helper.

    A workflow subagent cannot set ``ONEX_LANE`` in the Claude Code process
    environment the hook reads, so its identity comes from two facts it did
    not assert in the call itself: the harness's ``agent-<agent id>.meta.json``
    sidecar, found from the payload's ``agent_id`` and transcript path, names
    the lane it was dispatched as, or, when the sidecar carries only a label,
    the dispatch prompt that opens the agent's own transcript does; and the
    rolling work ledger holds an open CLAIM for exactly that lane. Otherwise an interactive session's helper
    may use the lane registered to its parent session, with that lane's open
    CLAIM. The hook's ``session_id`` names that parent harness session; the
    helper has its own ``agent_id``. The stamp never participates in identity
    resolution. Never raises.
    """
    agent_id = payload.get("agent_id")
    if not isinstance(agent_id, str) or not agent_id.strip():
        return "", "", "", ""
    reader = _refusal_lane_module()
    if reader is None:
        return "", "", "", ""
    try:
        attribution = importlib.import_module("hook_lane_attribution")
    except ImportError:
        return "", "", "", ""
    session = payload.get("session_id")
    session_id = session.strip() if isinstance(session, str) else ""
    named = ""
    for key in ("transcript_path", "agent_transcript_path"):
        transcript = payload.get(key)
        if not isinstance(transcript, str) or not transcript.strip():
            continue
        # Both readers never raise: an unreadable sidecar names no lane.
        meta = attribution.read_sidecar(
            transcript, session_id or None, agent_id.strip()
        )
        named = reader.lane_cell(reader.sidecar_lane(meta))
        if named:
            break
    # An unreadable ledger reads as no open CLAIM, which confirms nothing.
    claims = reader.open_claims(environ)
    if named and any(claim.get("lane") == named for claim in claims):
        return named, named, LANE_SOURCE_SIDECAR_CLAIM, ""
    # The harness label of a workflow lane is a short description or the ROUTE
    # line, not its name, so the dispatch prompt names it (OMN-17942).
    prompted, parent = _prompt_named(
        reader, attribution, payload, session_id, agent_id.strip()
    )
    if prompted and any(_claim_matches(c, prompted, parent) for c in claims):
        return prompted, named or prompted, LANE_SOURCE_PROMPT_CLAIM, ""
    if not named:
        return "", prompted, "", ""
    if allow_parent and session_id:
        parent_lane = _parent_session_lane(session_id, environ)
        if parent_lane and any(claim.get("lane") == parent_lane for claim in claims):
            return parent_lane, named, LANE_SOURCE_PARENT_SESSION_CLAIM, session_id
    return "", prompted or named, "", ""


class HandlerSubagentLaneResolve:
    """Resolve the lane a subagent's create is made as, or no lane."""

    def handle(self, request: ModelSubagentLaneRequest) -> ModelSubagentLaneResult:
        """The lane, the label that named it, its source and the parent session."""
        # Imported at call time: the guard loads this module by path under a
        # bare interpreter that has no pydantic and no omniclaude package.
        models = importlib.import_module(
            "omniclaude.nodes.node_hook_refusal_record_effect.models"
        )
        lane, helper, source, parent = subagent_lane(
            {
                "agent_id": request.agent_id,
                "session_id": request.session_id,
                "transcript_path": request.transcript_path,
                "agent_transcript_path": request.agent_transcript_path,
            },
            request.environ,
            allow_parent=request.allow_parent,
        )
        result: ModelSubagentLaneResult = models.ModelSubagentLaneResult(
            lane=lane, helper=helper, source=source, parent_session_id=parent
        )
        return result


__all__ = [
    "HandlerSubagentLaneResolve",
    "LANE_SOURCE_PARENT_SESSION_CLAIM",
    "LANE_SOURCE_PROMPT_CLAIM",
    "LANE_SOURCE_SIDECAR_CLAIM",
    "prompt_lane",
    "subagent_lane",
]
