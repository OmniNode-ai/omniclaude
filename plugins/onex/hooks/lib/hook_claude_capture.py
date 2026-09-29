#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""All-hooks capture producer: one lineage-carrying event per Claude Code hook.

OMN-19513, the producer half of the all-hooks ruling (ledger RULING row by
lane all-hooks-capture-83-ruling, operator: "we need all hooks captured").

What this does, per hook call
-----------------------------
It reads the hook's stdin, finds the harness's spawn sidecar when the hook
fired inside a subagent, and maps the input through the capture contract
(``src/omniclaude/hooks/model_claude_hook_event.py``,
``contract_hook_claude_capture.yaml``) into one ``ModelClaudeHookEvent``. That
event is journalled as a ``hook.event`` record through the existing emit
journal, and the singleton drainer publishes it to
``onex.evt.omniclaude.hook-event.v1``. The topic is read from the emit
registry by the drainer, never named here.

Every event carries the lineage the four legacy topics lack: ``session_id``,
``agent_id`` (null on the main thread), ``agent_type``, ``is_subagent``,
``parent_tool_use_id``, ``spawn_depth`` and ``workflow_run_id`` from the
sidecar, ``tool_use_id``, ``prompt_id``, ``turn_id``, and the deterministic
correlation and causation ids. Subagents share their parent's ``session_id``,
so ``agent_id`` is the only discriminator between a subagent's tool calls and
the main thread's.

Content never rides this event. Each content field is scrubbed by the
capture-redaction contract's span scrub FIRST, and the event carries only its
reference: the field name, the scrubbed value's sha256 and length, and a
deterministic content-record id. The full content itself is the restricted
``content.captured`` family's job (OMN-19550/OMN-19551).

The refusals, each fail-closed
------------------------------
Nothing is journalled, and the hook log says why, when:

1. The operator opted out: ``OMNICLAUDE_HOOK_CAPTURE`` is ``0``, ``off``,
   ``false`` or ``no``.
2. The local drainer does not list ``hook.event`` as publishable. A record the
   drainer cannot resolve holds the journal head until it is dead-lettered
   (the OMN-19074 outage shape), so an older drainer, or one on an omnimarket
   without the registry entry, leaves capture off.
3. The capture contract or the redaction resolver cannot be loaded, or the
   resolver has no span scrub. No hash on the bus may come from unscrubbed
   text.
4. The hook is one this module must never observe: see ``NEVER_REGISTERED``.

Why the contract is loaded by file path
---------------------------------------
``import omniclaude.hooks...`` runs the package ``__init__``, which imports
``omnibase_infra`` and ``aiokafka`` (22 s cold, measured under OMN-19551).
The contract module needs only ``pydantic``: loaded straight from its file it
costs about 0.16 s, in a process the hook has already backgrounded, so the
session never waits on it.

Fail-open like every hook on this path: always exits 0, never writes stdout.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hook_content_capture as content_capture  # noqa: E402
import hook_emit_append as appender  # noqa: E402
import hook_emit_health as health  # noqa: E402
import hook_emit_journal as journal  # noqa: E402
import hook_lane_attribution as lane_attribution  # noqa: E402
import hook_turn_id  # noqa: E402

#: The semantic event type journalled for every hook. The emit registry routes
#: it to the metadata topic; the topic string lives in the contracts only.
HOOK_EVENT_TYPE = "hook.event"

#: Opt-out switch. Unset means capture (the ruling); these values turn it off.
OPT_OUT_ENV = "OMNICLAUDE_HOOK_CAPTURE"
_OFF_VALUES = frozenset({"0", "off", "false", "no"})

#: Hook events this producer is never registered for, with the reason. The
#: coverage test holds hooks.json to exactly the contract's 33 minus these.
#:
#: WorktreeCreate and WorktreeRemove have REPLACE semantics in Claude Code
#: 2.1.283: a registered WorktreeCreate command hook must print the new
#: worktree's path, and the harness otherwise fails with "hook succeeded but
#: returned no worktree path". An observer registered there would break every
#: ``isolation: worktree`` agent and ``--worktree`` session on the machine.
#:
#: MessageDisplay fires once per streamed flush of every assistant message. A
#: process per flush is the OMN-17224 fan-out this journal exists to prevent,
#: and its only content (the display delta) is already captured whole by the
#: Stop and SubagentStop ``last_assistant_message`` reference.
NEVER_REGISTERED: Mapping[str, str] = {
    "WorktreeCreate": "replace semantics: an observer breaks worktree creation",
    "WorktreeRemove": "replace semantics: an observer takes over worktree removal",
    "MessageDisplay": "fires per streamed flush; the reply is captured at Stop",
}

#: Hooks that sit outside any turn: their events carry a null turn id.
_OUTSIDE_A_TURN = frozenset({"SessionStart", "SessionEnd", "Setup"})

_CONTRACT_MODULE_NAME = "omniclaude_claude_hook_capture_contract_by_path"
_SIDECAR_KEYS = frozenset(
    {
        "agentType",
        "description",
        "model",
        "requestNonInteractive",
        "requestShape",
        "spawnDepth",
        "toolUseId",
        "workflowPhase",
    }
)
_VERSION_RE = re.compile(r"(\d+)[.-](\d+)[.-](\d+)")


def _log(message: str) -> None:
    print(f"hook_claude_capture: {message}", file=sys.stderr)


# ---------------------------------------------------------------------------
# refusals
# ---------------------------------------------------------------------------


def capture_enabled_by_operator() -> bool:
    return os.environ.get(OPT_OUT_ENV, "").strip().lower() not in _OFF_VALUES


def drainer_can_publish(status_path: Path) -> bool:
    """True only when the drainer's status names ``hook.event`` as publishable."""
    status = health.read_status(status_path)
    if status is None or status.publishable_event_types is None:
        return False
    return HOOK_EVENT_TYPE in status.publishable_event_types


def _contract_candidates() -> list[Path]:
    candidates = [
        Path(__file__).resolve().parents[4]
        / "src"
        / "omniclaude"
        / "hooks"
        / "model_claude_hook_event.py"
    ]
    # find_spec on a TOP-LEVEL name locates the package without executing it.
    spec = importlib.util.find_spec("omniclaude")
    if spec is not None and spec.submodule_search_locations:
        for location in spec.submodule_search_locations:
            candidates.append(Path(location) / "hooks" / "model_claude_hook_event.py")
    return candidates


def load_contract() -> ModuleType | None:
    """Load the capture contract module by file path, or return ``None``."""
    loaded = sys.modules.get(_CONTRACT_MODULE_NAME)
    if loaded is not None:
        return loaded
    for candidate in _contract_candidates():
        if not candidate.is_file():
            continue
        spec = importlib.util.spec_from_file_location(_CONTRACT_MODULE_NAME, candidate)
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        # Registered before exec: pydantic resolves postponed annotations
        # through the module's entry in sys.modules.
        sys.modules[_CONTRACT_MODULE_NAME] = module
        try:
            spec.loader.exec_module(module)
        except Exception as exc:  # noqa: BLE001 -- try the next candidate
            sys.modules.pop(_CONTRACT_MODULE_NAME, None)
            _log(f"contract at {candidate} did not load: {type(exc).__name__}")
            continue
        return module
    return None


def make_scrubber(
    resolver: ModuleType, contract: ModuleType
) -> Callable[[str], Any] | None:
    """The production span scrub, shaped as the contract's ``ContentScrubber``.

    ``None`` when the loaded resolver predates the span scrub (OMN-19551): a
    whole-value hash is not the scrub the contract requires, and no hash on
    the metadata topic may be derived from unscrubbed text.
    """
    scrub_text = getattr(resolver, "scrub_text", None)
    if scrub_text is None:
        return None
    result_model = contract.ModelContentScrubResult

    def scrub(value: str) -> Any:
        scrubbed, hits = scrub_text(value)
        names = tuple(sorted(name for name, count in hits.items() if count))
        return result_model(
            value=scrubbed,
            redaction_state="secret_detected" if names else "clean",
            matched_pattern_names=names,
        )

    return scrub


# ---------------------------------------------------------------------------
# lineage inputs the hook stdin does not carry
# ---------------------------------------------------------------------------


def _sidecar_paths(
    transcript_path: str | None, session_id: str | None, agent_id: str
) -> list[Path]:
    """Where the harness writes ``agent-<agent id>.meta.json``, best first.

    A Task/Agent spawn writes it to ``<session>/subagents/``; a Workflow agent
    writes it to ``<session>/subagents/workflows/<run id>/``, and that run id
    is the event's ``workflow_run_id``. The session directory is derived from
    the transcript path (``<project>/<session>.jsonl``) so this never depends
    on the harness's undocumented project-slug rule.
    """
    name = f"agent-{agent_id}.meta.json"
    session_dirs: list[Path] = []
    if transcript_path:
        transcript = Path(transcript_path)
        session_dirs.append(transcript.with_suffix(""))
        # A payload whose transcript is already inside the session directory.
        if transcript.parent.name == "subagents":
            session_dirs.append(transcript.parent.parent)
    if session_id and not session_dirs:
        root = os.environ.get(lane_attribution.CLAUDE_PROJECTS_ENV)
        base = Path(root) if root else Path.home() / ".claude" / "projects"
        try:
            session_dirs.extend(p for p in base.glob(f"*/{session_id}") if p.is_dir())
        except OSError:
            pass
    paths: list[Path] = []
    for session_dir in session_dirs:
        subagents = session_dir / "subagents"
        paths.append(subagents / name)
        try:
            paths.extend(sorted((subagents / "workflows").glob(f"*/{name}")))
        except OSError:
            continue
    return paths


def read_sidecar(
    contract: ModuleType,
    *,
    transcript_path: str | None,
    session_id: str | None,
    agent_id: str | None,
) -> Any | None:
    """The parsed sidecar for a subagent event, or ``None`` when unreadable.

    ``None`` becomes ``parent_tool_use_id: null``, which the projection reads
    as ``parent_resolution: unknown``, never as "main thread": the contract
    keeps the two apart. Keys the harness adds later are dropped before
    validation so a new sidecar field cannot turn every parent unknown.
    """
    if not agent_id:
        return None
    for path in _sidecar_paths(transcript_path, session_id, agent_id):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(raw, dict):
            continue
        fields = {k: v for k, v in raw.items() if k in _SIDECAR_KEYS}
        if path.parent.parent.name == "workflows":
            fields["workflow_run_id"] = path.parent.name
        try:
            return contract.ModelSubagentSidecar.model_validate(fields)
        except ValueError as exc:
            _log(f"sidecar {path.name} did not validate: {type(exc).__name__}")
            return None
    return None


def claude_code_version(environ: Mapping[str, str] | None = None) -> str | None:
    """The harness version, from its exec path or its agent tag, else ``None``."""
    env = os.environ if environ is None else environ
    for key in ("CLAUDE_CODE_EXECPATH", "AI_AGENT"):
        match = _VERSION_RE.search(Path(env.get(key, "")).name)
        if match:
            return ".".join(match.groups())
    return None


# ---------------------------------------------------------------------------
# the capture
# ---------------------------------------------------------------------------


def build_event_payload(
    hook_input: Mapping[str, object],
    *,
    contract: ModuleType,
    scrubber: Callable[[str], Any],
    turn_dir: Path,
    emitted_at: datetime,
    version: str | None,
) -> dict[str, Any]:
    """Map one hook's stdin to the journal payload of its ``hook.event``.

    The payload is the contract event serialised to JSON, plus a top-level
    ``session_id``: the emit registry's partition key and required field are
    top-level names, and partitioning by session keeps every hook type of one
    session in order, which the lineage fold requires.

    Raises the contract's ``InvalidHookInputError`` or ``UnknownHookEventError``
    for input the mapper refuses; :func:`capture` logs and drops those.
    """
    hook_name = hook_input.get("hook_event_name")
    session_id = hook_input.get("session_id")
    turn_id = None
    if hook_name not in _OUTSIDE_A_TURN and isinstance(session_id, str):
        turn_id = hook_turn_id.peek_turn_id(turn_dir, session_id)
    agent_id = hook_input.get("agent_id")
    transcript = hook_input.get("transcript_path")
    sidecar = read_sidecar(
        contract,
        transcript_path=transcript if isinstance(transcript, str) else None,
        session_id=session_id if isinstance(session_id, str) else None,
        agent_id=agent_id if isinstance(agent_id, str) else None,
    )
    result = contract.map_hook_stdin(
        hook_input,
        emitted_at=emitted_at,
        sidecar=sidecar,
        claude_code_version=version,
        turn_id=turn_id,
        content_scrubber=scrubber,
    )
    payload: dict[str, Any] = result.event.model_dump(mode="json")
    payload["session_id"] = result.event.lineage.session_id
    return payload


def capture(
    hook_input: dict[str, Any],
    *,
    journal_dir: Path,
    cwd: str | None = None,
    actor: str | None = None,
    now: datetime | None = None,
) -> int:
    """Journal the ``hook.event`` record for one hook call. Returns 0 or 1."""
    hook_name = hook_input.get("hook_event_name")
    if not isinstance(hook_name, str) or not hook_name:
        _log("skipped: stdin carries no hook_event_name")
        return 0
    if hook_name in NEVER_REGISTERED:
        _log(f"skipped: {hook_name} is never observed ({NEVER_REGISTERED[hook_name]})")
        return 0
    if not capture_enabled_by_operator():
        return 0
    if not drainer_can_publish(content_capture.status_path_for(journal_dir)):
        _log(
            f"skipped {hook_name}: the local drainer does not list "
            f"{HOOK_EVENT_TYPE} as publishable (update its omnimarket and restart it)"
        )
        return 0
    contract = load_contract()
    if contract is None:
        _log("skipped: the capture contract could not be loaded")
        return 0
    resolver = content_capture.load_resolver()
    scrubber = make_scrubber(resolver, contract) if resolver is not None else None
    if scrubber is None:
        _log("skipped: no capture-redaction span scrub could be loaded")
        return 0

    target = journal_dir
    try:
        payload = build_event_payload(
            hook_input,
            contract=contract,
            scrubber=scrubber,
            turn_dir=hook_turn_id.turn_dir_for(target),
            emitted_at=now or datetime.now(UTC),
            version=claude_code_version(),
        )
    except (contract.InvalidHookInputError, contract.UnknownHookEventError) as exc:
        # The error names a field, never its value: hook stdin is content.
        _log(f"skipped {hook_name}: the contract refused the input: {exc}")
        return 0
    lineage = payload["lineage"]
    appender.append_event(
        event_type=HOOK_EVENT_TYPE,
        payload=payload,
        correlation_id=lineage["session_id"],
        cwd=cwd or _str(hook_input.get("cwd")),
        actor=actor,
        # Stamped verbatim, so the appender's top-level turn_id is the same
        # turn the lineage carries and never a second allocation.
        host_turn_id=lineage["turn_id"],
        agent_id=lineage["agent_id"],
        transcript_path=_str(hook_input.get("transcript_path")),
        session_id=lineage["session_id"],
        journal_dir=str(target),
    )
    return 1


def _str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Journal one lineage-carrying hook event (OMN-19513)."
    )
    parser.add_argument("--actor", default=None)
    parser.add_argument("--journal-dir", default=None)
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return 0
    try:
        raw = sys.stdin.read()
        parsed = json.loads(raw) if raw.strip() else {}
        hook_input = parsed if isinstance(parsed, dict) else {}
        journal_dir = (
            Path(args.journal_dir)
            if args.journal_dir
            else journal.default_journal_dir()
        )
        if capture(hook_input, journal_dir=journal_dir, actor=args.actor or None):
            lineage_note = "subagent" if hook_input.get("agent_id") else "main"
            _log(
                f"journalled {HOOK_EVENT_TYPE} "
                f"{hook_input.get('hook_event_name')} ({lineage_note})"
            )
    except Exception as exc:  # noqa: BLE001 -- outermost fail-open boundary
        # The type only: a pydantic error message quotes the input, and hook
        # stdin is content.
        _log(f"unexpected error: {type(exc).__name__}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
