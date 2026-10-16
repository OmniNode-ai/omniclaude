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

Every content field rides this event raw (operator RULING
2026-10-15T04:24:42Z): the field name, the value exactly as the harness sent
it, its length and a deterministic content-record id. Nothing is scrubbed and
nothing is hashed.

Payload encryption is one contract setting, ``payload_encryption`` in
``contract_hook_claude_capture.yaml``, off by default; see
:func:`payload_encryption_enabled`. With it on, the payload is journalled
sealed under a key read from the secret store
(``omniclaude.handlers.handler_hook_payload_encryption``), and nothing is journalled when that
key cannot be read.

The refusals, each fail-closed
------------------------------
Nothing is journalled, and the hook log says why, when:

1. The operator opted out: ``OMNICLAUDE_HOOK_CAPTURE`` is ``0``, ``off``,
   ``false`` or ``no``.
2. The local drainer does not list ``hook.event`` as publishable. A record the
   drainer cannot resolve holds the journal head until it is dead-lettered
   (the OMN-19074 outage shape), so an older drainer, or one on an omnimarket
   without the registry entry, leaves capture off.
3. The capture contract cannot be loaded.
4. The hook is one this module must never observe: see ``NEVER_REGISTERED``.
5. The hook-edge lane contract still lists ``hook.event`` under
   ``produce_grant_pending``: the lane has no produce grant for its topic, and
   an ungranted topic at the journal head stops the drain for every record
   behind it (measured four times; see the contract). Deleting that entry is
   the activation step, after the grant.

Why the contract is loaded by file path
---------------------------------------
``import omniclaude.hooks...`` runs the package ``__init__``, which imports
``omnibase_infra`` and ``aiokafka`` (22 s cold, measured under OMN-19551).
The contract module needs only ``pydantic``: loaded straight from its file it
costs about 0.16 s, in a process the hook has already backgrounded, so the
session never waits on it.

Derived events (OMN-18946)
--------------------------
Two events ride this same topic and lineage with no harness hook behind them,
because the facts they state are in no hook's stdin:

* ``GuardRefusal``: a guard refused a call. A refused PreToolUse has no
  PostToolUse to pair with, so the only trace of the refusal was a
  rate-limited ledger FRICTION row that no event joins to. The refusal recorder
  calls :func:`capture_guard_refusal` on EVERY refusal, before its own
  rate limit, so each refused call has one event naming the guard and its
  reason class (never the refusal's text), joined to the call by
  ``tool_use_id``.
* ``AssistantUsage``: tokens and model per assistant message. Stop,
  SubagentStop and SessionEnd call :func:`capture_assistant_usage`, which reads
  the transcript the hook names (see ``hook_transcript_usage``).

A failed tool call's content is captured here too
(:func:`capture_failure_content`): PostToolUseFailure already reaches this
script, and its tool input and error text go to ``content.captured`` under the
same path as a completed call's.

Fail-open like every hook on this path: always exits 0, never writes stdout.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import socket
import sys
from collections.abc import Callable, Iterator, Mapping
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hook_content_capture as content_capture  # noqa: E402
import hook_edge_lane  # noqa: E402
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


def lane_grant_pending(contract_path: Path | None = None) -> bool:
    """True when the lane contract holds ``hook.event`` back from the journal.

    The hook-edge lane contract lists declared classes whose topic has no
    produce grant yet (``produce_grant_pending``). An ungranted topic at the
    journal head stops the drain for every record behind it, so the grant
    comes first and this call site second. An unreadable contract reads as
    pending: fail closed.
    """
    path = contract_path or (
        Path(__file__).resolve().parent.parent / "contracts" / "hook_edge_lane.yaml"
    )
    try:
        lane = hook_edge_lane.load_contract(path)
    except Exception as exc:  # noqa: BLE001 -- unreadable means not cleared
        _log(f"the hook-edge lane contract did not load: {type(exc).__name__}")
        return True
    return HOOK_EVENT_TYPE in lane.produce_grant_pending


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


def payload_encryption_enabled(contract_path: Path | None = None) -> bool:
    """The contract's ``payload_encryption.enabled`` setting (default off).

    The reader, and the sealer it turns on, live in ``hook_content_capture``
    beside the content producer that shares them (OMN-19513).
    """
    return content_capture.payload_encryption_setting(contract_path)[0]


# ---------------------------------------------------------------------------
# lineage inputs the hook stdin does not carry
# ---------------------------------------------------------------------------


#: Where a Workflow agent's run id is remembered once its sidecar is found,
#: beside the journal: ``<state>/hook_sidecar_index/<session id>/<agent id>``.
SIDECAR_INDEX_DIRNAME = "hook_sidecar_index"
#: A session's index entries are pruned once nothing has touched them for this
#: long. Pruning runs only on a lookup miss, which is once per workflow agent.
SIDECAR_INDEX_STALE_AFTER_S = 7 * 24 * 3600
_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def sidecar_index_dir_for(journal_dir: Path) -> Path:
    """The workflow-run index for a journal: a sibling, under the same state dir."""
    return journal_dir.parent / SIDECAR_INDEX_DIRNAME


def _index_entry(
    index_dir: Path | None, session_dir: Path, agent_id: str
) -> Path | None:
    if index_dir is None:
        return None
    session = session_dir.name
    if not (_SAFE_ID.match(session) and _SAFE_ID.match(agent_id)):
        return None
    return index_dir / session / agent_id


def _remember_run(entry: Path | None, run_id: str) -> None:
    """Record the run id for the next hook call of this agent. Best effort."""
    if entry is None:
        return
    try:
        entry.parent.mkdir(parents=True, exist_ok=True)
        tmp = entry.with_name(f".{entry.name}.{os.getpid()}.tmp")
        tmp.write_text(run_id, encoding="utf-8")
        tmp.replace(entry)
    except OSError as exc:
        _log(f"sidecar index not written: {type(exc).__name__}")
        return
    _prune_index(entry.parent.parent, keep=entry.parent)


def _prune_index(index_dir: Path, *, keep: Path) -> None:
    """Drop session index directories untouched for a week. Miss path only."""
    cutoff = datetime.now(UTC).timestamp() - SIDECAR_INDEX_STALE_AFTER_S
    try:
        sessions = list(os.scandir(index_dir))
    except OSError:
        return
    for session in sessions:
        try:
            if session.path == str(keep) or not session.is_dir(follow_symlinks=False):
                continue
            if session.stat(follow_symlinks=False).st_mtime >= cutoff:
                continue
            stale = Path(session.path)
            for child in stale.iterdir():
                child.unlink()
            stale.rmdir()
        except OSError:
            continue


def _workflow_sidecars(
    session_dir: Path, agent_id: str, index_dir: Path | None
) -> Iterator[Path]:
    """A Workflow agent's sidecar: the indexed run first, else one search.

    The search lists every run directory of the session
    (``subagents/workflows/*/``), one ``opendir`` each: 492 of them per hook
    call on the operator session of 2026-10-01, growing for as long as the
    session lives, and 0.5 to 0.6 s per call at 24 concurrent captures
    (OMN-20110). An agent's sidecar never moves, so the run id is recorded the
    first time it is found and every later hook call of that agent opens one
    small file instead of searching.
    """
    name = f"agent-{agent_id}.meta.json"
    workflows = session_dir / "subagents" / "workflows"
    entry = _index_entry(index_dir, session_dir, agent_id)
    if entry is not None:
        try:
            run_id = entry.read_text(encoding="utf-8").strip()
        except OSError:
            run_id = ""
        if run_id and _SAFE_ID.match(run_id):
            indexed = workflows / run_id / name
            if indexed.is_file():
                yield indexed
                return
    try:
        found = sorted(workflows.glob(f"*/{name}"))
    except OSError:
        return
    if found:
        _remember_run(entry, found[0].parent.name)
    yield from found


def _sidecar_paths(
    transcript_path: str | None,
    session_id: str | None,
    agent_id: str,
    index_dir: Path | None = None,
) -> Iterator[Path]:
    """Where the harness writes ``agent-<agent id>.meta.json``, best first.

    A Task/Agent spawn writes it to ``<session>/subagents/``; a Workflow agent
    writes it to ``<session>/subagents/workflows/<run id>/``, and that run id
    is the event's ``workflow_run_id``. The session directory is derived from
    the transcript path (``<project>/<session>.jsonl``) so this never depends
    on the harness's undocumented project-slug rule.

    A generator: the caller stops at the first sidecar that reads, so a
    Task/Agent spawn never reaches the workflow lookup at all, and a Workflow
    agent reaches it through :func:`_workflow_sidecars`' index.
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
    for session_dir in session_dirs:
        yield session_dir / "subagents" / name
    for session_dir in session_dirs:
        yield from _workflow_sidecars(session_dir, agent_id, index_dir)


def read_sidecar(
    contract: ModuleType,
    *,
    transcript_path: str | None,
    session_id: str | None,
    agent_id: str | None,
    index_dir: Path | None = None,
) -> Any | None:
    """The parsed sidecar for a subagent event, or ``None`` when unreadable.

    ``None`` becomes ``parent_tool_use_id: null``, which the projection reads
    as ``parent_resolution: unknown``, never as "main thread": the contract
    keeps the two apart. Keys the harness adds later are dropped before
    validation so a new sidecar field cannot turn every parent unknown.
    """
    if not agent_id:
        return None
    for path in _sidecar_paths(transcript_path, session_id, agent_id, index_dir):
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
    turn_dir: Path,
    emitted_at: datetime,
    version: str | None,
    sidecar_index_dir: Path | None = None,
    host: str | None = None,
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
        index_dir=sidecar_index_dir,
    )
    result = contract.map_hook_stdin(
        hook_input,
        emitted_at=emitted_at,
        sidecar=sidecar,
        claude_code_version=version,
        turn_id=turn_id,
        host=host,
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
    key_reader: Callable[[str], str | None] | None = None,
) -> int:
    """Journal the ``hook.event`` record for one hook call. Returns 0 or 1.

    ``key_reader`` reads the payload key by its secret-store reference; it is
    consulted only when the ``payload_encryption`` setting is on.
    """
    hook_name = hook_input.get("hook_event_name")
    if not isinstance(hook_name, str) or not hook_name:
        _log("skipped: stdin carries no hook_event_name")
        return 0
    if hook_name in NEVER_REGISTERED:
        _log(f"skipped: {hook_name} is never observed ({NEVER_REGISTERED[hook_name]})")
        return 0
    if not capture_enabled_by_operator():
        return 0
    if lane_grant_pending():
        _log(
            f"skipped {hook_name}: the hook-edge lane contract lists "
            f"{HOOK_EVENT_TYPE} under produce_grant_pending (no produce grant yet)"
        )
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
    try:
        sealer = content_capture.payload_sealer(key_reader=key_reader)
    except content_capture.PayloadSealRefusedError as exc:
        _log(
            f"skipped {hook_name}: payload encryption refused: {exc}; "
            "nothing crosses in the clear"
        )
        return 0

    target = journal_dir
    try:
        payload = build_event_payload(
            hook_input,
            contract=contract,
            turn_dir=hook_turn_id.turn_dir_for(target),
            emitted_at=now or datetime.now(UTC),
            version=claude_code_version(),
            sidecar_index_dir=sidecar_index_dir_for(target),
            host=socket.gethostname(),
        )
    except (contract.InvalidHookInputError, contract.UnknownHookEventError) as exc:
        health.record_contract_refusal(target)
        # The error names a field, never its value: hook stdin is content.
        _log(f"skipped {hook_name}: the contract refused the input: {exc}")
        return 0
    lineage = payload["lineage"]
    if sealer is not None:
        payload = sealer(HOOK_EVENT_TYPE, payload)
    appender.append_event(
        # The literal, not the constant: validate_hook_edge_lane.py finds the
        # classes this edge emits by scanning call sites for it.
        event_type="hook.event",
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


# ---------------------------------------------------------------------------
# derived events (OMN-18946)
# ---------------------------------------------------------------------------

#: Hooks after which a transcript is read for usage. The marker makes the three
#: idempotent: a message counted at Stop is never counted again at SessionEnd.
USAGE_HOOKS = frozenset({"Stop", "SubagentStop", "SessionEnd"})

#: Stdin keys of the refused hook that a refusal event keeps. The refused
#: command, script or prompt is content and is never among them.
_REFUSAL_LINEAGE_KEYS = (
    "agent_id",
    "agent_type",
    "prompt_id",
    "tool_use_id",
    "tool_name",
    "transcript_path",
    "cwd",
)


def capture_guard_refusal(
    hook_input: Mapping[str, Any],
    *,
    guard: str,
    reason_class: str,
    journal_dir: Path | None = None,
    cwd: str | None = None,
    actor: str | None = None,
    now: datetime | None = None,
) -> int:
    """Journal the ``GuardRefusal`` event for one refused hook call.

    ``hook_input`` is the refused hook's own stdin. Only its lineage keys are
    kept; ``guard`` and ``reason_class`` are the recorder's redacted, normalised
    tokens. Returns how many events were journalled, 0 when a refusal of the
    capture itself applies (opt-out, drainer, lane contract) or the refused
    call names no session.
    """
    session = _str(hook_input.get("session_id"))
    if session is None:
        _log("skipped GuardRefusal: the refused call names no session")
        return 0
    stdin: dict[str, Any] = {
        "hook_event_name": "GuardRefusal",
        "session_id": session,
        "guard": guard,
        "reason_class": reason_class,
    }
    for key in _REFUSAL_LINEAGE_KEYS:
        value = _str(hook_input.get(key))
        if value is not None:
            stdin[key] = value
    refused_hook = _str(hook_input.get("hook_event_name"))
    if refused_hook is not None:
        stdin["refused_hook_event_name"] = refused_hook
    return capture(
        stdin,
        journal_dir=journal_dir or journal.default_journal_dir(),
        cwd=cwd,
        actor=actor,
        now=now,
    )


#: The transcript usage node: imported at call time (the hook interpreter must
#: be able to import ``omniclaude``, as the refusal recorder's does), never at
#: module load, so a capture that does not read a transcript pays nothing.
_USAGE_NODE = "omniclaude.nodes.node_transcript_usage_read_effect"


def _usage_node() -> tuple[Any, Any, Any, Any] | None:
    """``(read handler, commit handler, read request, commit request)`` or ``None``."""
    try:
        read = importlib.import_module(
            f"{_USAGE_NODE}.handlers.handler_transcript_usage_read"
        )
        commit = importlib.import_module(
            f"{_USAGE_NODE}.handlers.handler_transcript_usage_commit"
        )
        models = importlib.import_module(f"{_USAGE_NODE}.models")
    except ImportError as exc:
        _log(f"skipped usage: {_USAGE_NODE} did not import ({type(exc).__name__})")
        return None
    return (
        read.HandlerTranscriptUsageRead(),
        commit.HandlerTranscriptUsageCommit(),
        models.ModelTranscriptUsageReadRequest,
        models.ModelTranscriptUsageCommitRequest,
    )


def capture_assistant_usage(
    hook_input: Mapping[str, Any],
    *,
    journal_dir: Path,
    actor: str | None = None,
    now: datetime | None = None,
) -> int:
    """Journal one ``AssistantUsage`` event per model the transcript shows.

    Only for the hooks in ``USAGE_HOOKS``. The read is consumed only when every
    event of it was journalled, so a capture that is off, or an append that
    failed, leaves the usage for the next Stop.
    """
    hook_name = hook_input.get("hook_event_name")
    session = _str(hook_input.get("session_id"))
    if hook_name not in USAGE_HOOKS or session is None:
        return 0
    subagent = hook_name == "SubagentStop"
    agent_id = _str(hook_input.get("agent_id")) if subagent else None
    raw_path = _str(
        hook_input.get("agent_transcript_path" if subagent else "transcript_path")
    )
    if raw_path is None or (subagent and agent_id is None):
        return 0
    node = _usage_node()
    if node is None:
        return 0
    reader, committer, read_request, commit_request = node
    read = reader.handle(
        read_request(
            transcript_path=raw_path,
            state_dir=str(hook_turn_id.turn_dir_for(journal_dir)),
            session_id=session,
            agent_id=agent_id,
            include_sidechain=subagent,
        )
    )
    written = 0
    for totals in read.totals:
        stdin: dict[str, Any] = {
            "hook_event_name": "AssistantUsage",
            "session_id": session,
            "model": totals.model,
            "message_count": totals.message_count,
            "input_tokens": totals.input_tokens,
            "output_tokens": totals.output_tokens,
            "cache_creation_input_tokens": totals.cache_creation_input_tokens,
            "cache_read_input_tokens": totals.cache_read_input_tokens,
            "usage_source_hook": hook_name,
            "partial_window": read.partial_window,
        }
        for key in ("agent_id", "agent_type", "prompt_id", "transcript_path", "cwd"):
            value = _str(hook_input.get(key))
            if value is not None:
                stdin[key] = value
        written += capture(stdin, journal_dir=journal_dir, actor=actor, now=now)
    if written == len(read.totals):
        committed = committer.handle(
            commit_request(
                marker_path=read.marker_path,
                next_offset=read.next_offset,
                seen_ids=read.seen_ids,
            )
        )
        if not committed.committed:
            _log(f"usage marker not written ({committed.reason}); usage may repeat")
    return written


def capture_failure_content(
    hook_input: Mapping[str, Any],
    *,
    journal_dir: Path,
    actor: str | None = None,
) -> int:
    """Journal a failed tool call's input and error text as content records.

    Only for PostToolUseFailure. Content was stored for completed calls only
    (the PostToolUse mirror runs ``--kind tool``); a failed call fires
    PostToolUseFailure instead, and 0 of 7,544 failed Bash calls in a week had
    their command or error stored. The redaction is the completed call's.
    """
    if hook_input.get("hook_event_name") != "PostToolUseFailure":
        return 0
    return content_capture.capture(
        dict(hook_input),
        kind="tool_failure",
        journal_dir=journal_dir,
        correlation_id=_str(hook_input.get("session_id")),
        cwd=_str(hook_input.get("cwd")),
        actor=actor,
        agent_id=_str(hook_input.get("agent_id")),
        transcript_path=_str(hook_input.get("transcript_path")),
    )


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
        actor = args.actor or None
        if capture(hook_input, journal_dir=journal_dir, actor=actor):
            lineage_note = "subagent" if hook_input.get("agent_id") else "main"
            _log(
                f"journalled {HOOK_EVENT_TYPE} "
                f"{hook_input.get('hook_event_name')} ({lineage_note})"
            )
        usage_events = capture_assistant_usage(
            hook_input, journal_dir=journal_dir, actor=actor
        )
        if usage_events:
            _log(f"journalled {usage_events} AssistantUsage event(s)")
        failure_records = capture_failure_content(
            hook_input, journal_dir=journal_dir, actor=actor
        )
        if failure_records:
            _log(f"journalled {failure_records} failed-call content record(s)")
    except Exception as exc:  # noqa: BLE001 -- outermost boundary: report, exit 1
        # The type only: a pydantic error message quotes the input, and hook
        # stdin is content. Exit 1 so hook_emit_bounded fails loud (OMN-20110).
        print(
            f"hook_claude_capture: hook.event NOT journalled: {type(exc).__name__}",
            file=sys.stderr,
        )
        return 1
    journal.emit_done()
    return 0


if __name__ == "__main__":
    sys.exit(main())
