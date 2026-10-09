# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Give a hook refusal a durable, readable home (OMN-18946).

THE FAILURE THIS REMOVES. A PreToolUse guard that refuses a command writes
the reason to the operator's terminal, where it is gone at the end of the
turn, and to a per-hook log file under a temporary directory that nothing
reads. Neither is durable and neither is aggregated, so a guard that refuses
the same correct command forty times in a night produces forty invisible
events: no row, no count, nobody told. The morning friction sweep reads the
rolling work ledger and finds nothing, because nothing wrote there.

That is not hypothetical, and it is not rare. The compound-line refusal class
(OMN-18335) fired three separate times on 2026-09-20 and a fourth time while
this ticket was being built, each time against a correct command, and each
occurrence was found by a person noticing it rather than by any surface
reporting it. A gate whose refusals reach no aggregated surface cannot be
told apart from a gate that never fires.

WHERE THE ROW IS DECIDED. The redaction, reason normalisation, dedupe key and
row layout are omnimarket's ``node_hook_refusal_row_compute`` (OMN-20685); this
module calls its handler in-process, as every hook reaches an omnimarket node,
and keeps only what is bound to this host: the rate-limit state, the lane
resolution and the ledger append. The handler import adds about 50 ms to a
refusal and pulls in no ``omnibase_core``; it is paid only on a refusal, never
on a tool call a guard allows.

WHERE THIS LIVES. ``node_hook_refusal_record_effect`` (OMN-20685): the
contract declares the command and terminal topics, ``HandlerHookRefusalRecord``
is the definition-B handler, and ``main`` is the one process entry the guards'
shell seam calls (``python -m`` this module). It replaced the standalone
recorder and lane-resolver scripts.

WHAT THIS DOES. One ``FRICTION``-class row per refusal, appended to the
rolling work ledger through ``onex-ledger`` — the same locked
writer every other lane uses, never a direct write — carrying the guard, a
stable reason token, the resolved lane and a redacted first line of the
refusal text. The morning friction sweep and the fleet failure sink both read
that file, so a refusal becomes a fact somebody sees.

RATE LIMITED BY DEDUPE KEY, and this is load-bearing rather than a courtesy.
A guard in a retry loop can refuse thousands of times in an hour. Thousands
of rows would not inform anyone; they would make the ledger unreadable and
would be the second silent gate, since nobody reads a surface that floods.
One row per ``(guard, reason, lane)`` per hour, and the row states how many
further refusals of that exact key were suppressed behind it — so the count
is reported rather than lost, and a looping refusal is visibly a loop.
OMN-20343 adds one exception: secret-guard retries are keyed by session,
and the fourth and subsequent refusal is emitted immediately with its safe
pattern diagnosis. The fourth row carries the two initially suppressed retries.

WHY THE COUNT IS ON THE *NEXT* ROW. The first refusal of a key is written
immediately, with ``suppressed=0``: a refusal must not wait an hour to be
recorded. Refusals inside the window increment a counter, and the next row
after the window carries it. A reader therefore sees the event at once, and
learns its volume as soon as the window turns.

FAILURES ARE LOUD. This runs behind a hook that is refusing a tool call.
An unresolved registry or failed append exits non-zero with a redacted reason
on stderr, without advancing the emission state. The calling hook already
refused the tool; the recorder reports its own failure without changing that
guard's verdict. A retry remains eligible until the row has landed.

ISOLATION. Called from ``hook_record_refusal`` in ``lib/hook_refusal.sh``, which
backgrounds and disowns it exactly as ``emit_to_journal`` does, so the
operator's refusal message is never delayed by a lock wait. The dedupe
decision is made BEFORE the ledger lock is taken, never after: that lock is
exclusive across stage-and-append, and a suppressed refusal that queued for
it would serialise every lane's tool calls behind one noisy guard.

FOR A CONSUMER OF THESE ROWS. Key on the ``dedupe=`` field, never on the
whole line. ``suppressed_since_last_row`` changes every window by design, so
a consumer hashing the line would see a new value every time and would
de-duplicate nothing — measured on a sibling reporter, whose whole-issue-set
hash bounced on every tick and never de-duplicated once across 39
consecutive ticks. Stable key, volatile facts in the detail.

RESIDUAL, STATED RATHER THAN IMPLIED. A row is written only when a refusal
happens, so "no refusals this hour" and "the hooks stopped running" render
identically to a reader, and the second is a failure of exactly the class
this module exists to surface. A hook cannot close that: it runs only when a
tool call does. Closing it needs a timer-driven heartbeat row emitted every
window regardless of whether anything was refused, which is a scheduled unit
and a separate change, not a line here.
"""

from __future__ import annotations

import argparse
import fcntl
import importlib
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO

from omniclaude.nodes.node_hook_refusal_record_effect.models import (
    DEFAULT_WINDOW_SECONDS,
    EnumHookRefusalRecordStatus,
    ModelHookRefusalRecordRequest,
    ModelHookRefusalRecordResult,
)

try:
    from omnimarket.nodes.node_hook_refusal_row_compute.handlers.handler_hook_refusal_row import (
        MAX_DETAIL_CHARS,
        HandlerHookRefusalRowCompute,
        redact,
    )
    from omnimarket.nodes.node_hook_refusal_row_compute.models import (
        ModelHookRefusalRowRequest,
        ModelHookRefusalRowResult,
    )
except ImportError as exc:
    raise SystemExit(
        "hook refusal recorder: omnimarket's node_hook_refusal_row_compute is "
        f"not importable by this interpreter ({exc}); run it with the plugin "
        "venv (PLUGIN_PYTHON_BIN)"
    ) from exc

# DEFAULT_WINDOW_SECONDS (one row per (guard, reason, lane) per hour) is the
# request model's default. An hour is the window the ticket names, and it is
# also the cadence the morning sweep reads at, so a finer window would add rows
# no reader distinguishes.
# OMN-20343: SubagentStop retries are actionable immediately after the third
# refusal. This exception applies only to the secret guard, keyed by session.
SECRET_REPEAT_THRESHOLD = 3


def state_dir() -> Path:
    """Where the per-key rate-limit state lives.

    Beside the hook-emit journal, under the same ``ONEX_STATE_DIR`` override,
    so an operator clearing hook state clears this too and does not find one
    surface remembering a window the other has forgotten.
    """
    override = os.environ.get("ONEX_HOOK_REFUSAL_STATE_DIR")
    if override:
        return Path(override)
    base = os.environ.get("ONEX_STATE_DIR")
    if base:
        return Path(base) / "hook_refusals"
    registry_root = _resolve_registry_root()
    if registry_root is None:
        raise RuntimeError("OMNI_HOME must name an absolute registry root")
    return registry_root / ".onex_state" / "hook_refusals"


def _read_state(path: Path) -> tuple[float | None, int]:
    """``(last_emitted_epoch | None, suppressed_since)``.

    ``None`` means this key has NEVER been emitted, and is distinct from a
    timestamp of zero. Collapsing the two was a real defect caught by
    ``test_the_first_refusal_is_recorded_immediately``: with ``0.0`` standing
    in for "never", the window comparison ``now - 0.0 < window`` is false
    only once the epoch exceeds the window, so the very first refusal of a
    key was SUPPRESSED under any clock a test can set. Under a real clock it
    happened to work, which is exactly the kind of bug that ships.

    An unreadable state file also returns ``None``, so the row is EMITTED.
    The failure direction matters: losing a refusal is the bug this module
    exists to fix, and an extra row is merely noise.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, 0
    if not isinstance(data, dict):
        return None, 0
    last = data.get("last_emitted")
    suppressed = data.get("suppressed")
    return (
        float(last) if isinstance(last, (int, float)) else None,
        int(suppressed) if isinstance(suppressed, int) else 0,
    )


def _write_state(
    path: Path, *, last_emitted: float, suppressed: int, attempts: int = 0
) -> None:
    payload = json.dumps(
        {"last_emitted": last_emitted, "suppressed": suppressed, "attempts": attempts}
    )
    tmp = path.with_suffix(".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(path)
    except OSError:
        # A state directory we cannot write means no rate limiting, which
        # degrades to more rows rather than to fewer. Never to silence.
        pass


def should_emit(
    key: str,
    *,
    now: float,
    window_seconds: int,
    directory: Path,
    surface_after: int | None = None,
) -> tuple[bool, int]:
    """Decide whether a row is due. Returns ``(emit, suppressed_count)``.

    ``surface_after`` limits initial suppression for the secret guard; once
    a session exceeds it every attempt emits, even across hourly windows.

    ``suppressed_count`` is the number of refusals of this key that were
    swallowed since the last emitted row, and is meaningful only when
    ``emit`` is true. Only suppression of an already recorded refusal changes
    state here; the caller commits a new emission after its append succeeds.
    """
    path = directory / f"{key}.json"
    last_emitted, suppressed = _read_state(path)
    attempts = 0
    if surface_after is not None:
        try:
            attempts = max(0, int(json.loads(path.read_text()).get("attempts", 0)))
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        attempts += 1
    if (
        last_emitted is not None
        and now - last_emitted < window_seconds
        and (surface_after is None or attempts <= surface_after)
    ):
        _write_state(
            path,
            last_emitted=last_emitted,
            suppressed=suppressed + 1,
            attempts=attempts,
        )
        return False, 0
    return True, suppressed


def decide_row(
    *,
    guard: str,
    reason: str,
    lane: str,
    lane_source: str,
    detail: str,
    session: str,
    suppressed: int,
    timestamp: str,
) -> ModelHookRefusalRowResult:
    """Ask the row-decision node for one refusal's redacted, keyed ledger row.

    The redaction, reason normalisation, dedupe key and row layout are the
    omnimarket node's (``node_hook_refusal_row_compute``, OMN-20685); this
    caller keeps only what needs this host: the rate-limit state, the lane
    resolution and the ledger append. The node's handler is called in-process,
    the way every other hook reaches an omnimarket node, so a refusal does not
    pay the runtime import that ``RuntimeLocal`` would add.
    """
    return HandlerHookRefusalRowCompute().handle(
        ModelHookRefusalRowRequest(
            guard=guard,
            reason=reason,
            detail=detail,
            lane=lane,
            lane_source=lane_source,
            session=session,
            suppressed=suppressed,
            timestamp=timestamp,
        )
    )


def append_refusal_log(row: str, registry_root: Path | None) -> None:
    """Record every attempt before ledger deduplication, including unresolved lanes.

    This is the declared guard-sweep surface. Reuse the ledger row's timestamp,
    redaction and lane resolution rather than producing an unattributed second
    account of the same refusal in each shell wrapper.
    """
    configured = os.environ.get("ONEX_STATE_DIR")
    if configured:
        base = Path(configured)
    elif registry_root is not None:
        base = registry_root / ".onex_state"
    else:
        raise ValueError("OMNI_HOME must name an absolute registry root")
    if not base.is_absolute():
        raise ValueError("ONEX_STATE_DIR must be absolute")
    log = base / "hooks" / "logs" / "hooks.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        stream.write(row + "\n")


#: Most of a hook payload read from stdin. A Workflow payload carries the
#: whole script; past this the payload is ignored rather than half-parsed.
MAX_PAYLOAD_BYTES = 4 * 1024 * 1024


def read_payload(stream: TextIO) -> dict[str, object] | None:
    """The hook's own stdin payload, or ``None`` when absent or unreadable."""
    try:
        text = stream.read(MAX_PAYLOAD_BYTES + 1)
    except (OSError, ValueError):
        return None
    if not text.strip() or len(text) > MAX_PAYLOAD_BYTES:
        return None
    try:
        data = json.loads(text)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def resolve_lane_fields(
    cwd: str | None,
    transcript_path: str | None,
    session_id: str | None,
    agent_id: str | None,
    *,
    payload: dict[str, object] | None = None,
    ledger: str | None = None,
) -> tuple[str, str]:
    """``(lane, lane_source)`` from honest operands, never a guess (OMN-19381).

    The chain -- sidecar, lane env, registry, open CLAIM, worktree label --
    lives in ``handler_hook_refusal_lane``; the payload's own fields win over the
    environment-derived arguments, which stay as fallbacks.

    Imported lazily and defensively: this module must still write a row when
    the attribution module is missing or broken, naming the lane as
    unresolved rather than dropping the refusal. A row that names no lane is
    far better than no row, and a GUESSED lane would be worse than either --
    it would attribute one lane's friction to a neighbour.
    """
    try:
        from omniclaude.nodes.node_hook_refusal_record_effect.handlers import (  # noqa: PLC0415
            handler_hook_refusal_lane as hook_refusal_lane,
        )

        lane, lane_source = hook_refusal_lane.resolve_refusal_lane(
            payload,
            cwd=cwd,
            transcript_path=transcript_path,
            session_id=session_id,
            agent_id=agent_id,
            ledger=ledger,
        )
        return str(lane), str(lane_source)
    except Exception:  # noqa: BLE001 - never raise on the refusal path
        return "", "unresolved"


def append_row(row: str, *, ledger: Path, project: Path, timeout: str) -> bool:
    """Append through packaged ``onex-ledger``. Never a direct ledger write.

    The ledger is a shared append-only file many lanes write concurrently;
    the locked writer is the only sanctioned path and it also carries the
    dedupe-on-retry behaviour this caller would otherwise need itself.
    """
    if not project.is_absolute() or not (project / "pyproject.toml").is_file():
        _say(
            "hook refusal recorder: ledger writer project is unavailable: "
            + redact(str(project)),
            err=True,
        )
        return False
    if not ledger.is_file():
        _say(
            "hook refusal recorder: ledger is unavailable: " + redact(str(ledger)),
            err=True,
        )
        return False
    try:
        completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [
                "uv",
                "run",
                "--quiet",
                "--project",
                str(project),
                "onex-ledger",
                str(ledger),
                "--append",
                row,
                "--timeout",
                timeout,
            ],
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        _say(
            "hook refusal recorder: ledger writer failed: " + redact(str(exc)), err=True
        )
        return False
    if completed.returncode != 0:
        _say(
            f"hook refusal recorder: ledger writer exited {completed.returncode}: "
            + redact(completed.stderr or "no stderr reason")[:MAX_DETAIL_CHARS],
            err=True,
        )
        return False
    return True


def _say(text: str, *, err: bool = False) -> None:
    """One line to stdout, or to stderr when *err*; the entry's only output path."""
    (sys.stderr if err else sys.stdout).write(text + "\n")


def _resolve_registry_root() -> Path | None:
    """The workspace registry root, from its env var. No default.

    An unset variable means the ledger is unreachable from here, which is a
    dropped row; a guessed default would be a row written into the wrong
    tree.
    """
    value = os.environ.get("OMNI_HOME")
    return Path(value) if value and Path(value).is_absolute() else None


def _commit_emitted(path: Path, now: float, count_attempt: bool) -> None:
    """Record an emitted row; the secret guard's attempt count carries on."""
    attempts = 0
    if count_attempt:
        try:
            attempts = max(0, int(json.loads(path.read_text()).get("attempts", 0)))
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        attempts += 1
    _write_state(path, last_emitted=now, suppressed=0, attempts=attempts)


def extract_detail(raw: str) -> str:
    """Read a guard's verdict, retaining the diagnostic ahead of boilerplate.

    Only safe rule IDs and line numbers are constructed by the secret guard.
    Other guards can cite user text, so apply both shared redactors BEFORE
    truncation. No raw payload, command or final message is a fallback.
    """
    # A plugin hook-library sibling, on sys.path through --hooks-lib.
    redact_secrets: Callable[[str], str] = importlib.import_module(
        "secret_redactor"
    ).redact_secrets

    try:
        verdict = json.loads(raw)
        envelope = verdict.get("hookSpecificOutput")
        context = None
        if isinstance(envelope, dict) and envelope.get("hookEventName"):
            context = envelope.get("additionalContext") or envelope.get(
                "permissionDecisionReason"
            )
        detail = context or verdict.get("reason") or "verdict_has_no_diagnostic"
        if not isinstance(detail, str):
            detail = "verdict_has_no_diagnostic"
    except (ValueError, AttributeError, TypeError):
        detail = "verdict_json_invalid"
    # Bound-receipt refusals explain the bar at length before stating which
    # receipt failed. Keep that evidence before the ledger's 240-char limit.
    if "What is missing: " in detail:
        rule = re.search(r"\b(no_bound_dod_receipt|ac_tick_without_receipt)\b", detail)
        ticket = re.search(r"\bOMN-\d+\b", detail)
        missing = detail.split("What is missing: ", 1)[1].split("Ticked boxes", 1)[0]
        detail = (
            f"rule={rule.group() if rule else 'bound_receipt'} "
            f"ticket={ticket.group() if ticket else 'unresolved'} "
            f"citation=contracts/{ticket.group() if ticket else 'unresolved'}.yaml {missing}"
        )
    return redact(redact_secrets(detail))[:MAX_DETAIL_CHARS]


class HandlerHookRefusalRecord:
    """Record one refusal: decide the row, rate-limit it, append it."""

    def handle(
        self, request: ModelHookRefusalRecordRequest
    ) -> ModelHookRefusalRecordResult:
        payload = request.payload
        lane, lane_source = resolve_lane_fields(
            request.cwd,
            request.transcript_path,
            request.session_id,
            request.agent_id,
            payload=payload,
            ledger=request.ledger,
        )
        # Lane attribution is a separate concern. The secret guard's retry budget
        # must not be shared by unrelated sessions, even when both have an
        # unresolved lane, so the node keys that guard by session as well.
        session = (
            request.session_id
            or (payload or {}).get("session_id")
            or request.transcript_path
            or (payload or {}).get("agent_transcript_path")
        )

        def decide(suppressed: int, timestamp: str) -> ModelHookRefusalRowResult:
            return decide_row(
                guard=request.guard,
                reason=request.reason,
                lane=lane,
                lane_source=lane_source,
                detail=request.detail,
                session=str(session) if session else "",
                suppressed=suppressed,
                timestamp=timestamp,
            )

        def failed(*messages: str) -> ModelHookRefusalRecordResult:
            return ModelHookRefusalRecordResult(
                status=EnumHookRefusalRecordStatus.FAILED,
                exit_code=1,
                key=key,
                messages=messages,
            )

        registry_root = None
        project = None
        timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        first = decide(0, timestamp)
        key = first.key
        repeated_secret = first.repeated_secret
        if not request.print_row:
            registry_root = _resolve_registry_root()
            # An explicit state root can retain the refusal even if the registry
            # needed by the aggregate writer is unavailable. Never lose both.
            try:
                append_refusal_log(first.row, registry_root)
            except (OSError, ValueError) as exc:
                return failed(
                    "hook refusal recorder: "
                    + redact(str(exc))
                    + "; dedupe state unchanged"
                )
            if registry_root is None:
                return failed(
                    "hook refusal recorder: OMNI_HOME must name an absolute registry "
                    "root; dedupe state unchanged"
                )
            # The default lives in a plugin hook-library sibling, on sys.path
            # through --hooks-lib; a declared project does not need it.
            project = Path(
                os.environ.get("OMNIBASE_INTERNAL_HOME")
                or importlib.import_module("hook_emit_bounded").ledger_writer_project(
                    registry_root
                )
            )
            if not project.is_absolute():
                return failed(
                    "hook refusal recorder: OMNIBASE_INTERNAL_HOME must be absolute; "
                    "dedupe state unchanged"
                )

        directory = state_dir()
        now = time.time()
        emit, suppressed = should_emit(
            key,
            now=now,
            window_seconds=request.window_seconds,
            directory=directory,
            surface_after=SECRET_REPEAT_THRESHOLD if repeated_secret else None,
        )
        if not emit:
            return ModelHookRefusalRecordResult(
                status=EnumHookRefusalRecordStatus.SUPPRESSED, exit_code=0, key=key
            )

        row = decide(suppressed, timestamp).row
        if request.print_row:
            if repeated_secret:
                # Inspecting the secret guard exercises its retry budget, which
                # only advances when an emitted row is committed.
                _commit_emitted(directory / f"{key}.json", now, True)
            return ModelHookRefusalRecordResult(
                status=EnumHookRefusalRecordStatus.PRINTED,
                exit_code=0,
                row=row,
                key=key,
            )
        if registry_root is None or project is None:
            return failed()
        ledger = (
            Path(request.ledger)
            if request.ledger
            else registry_root / "docs" / "tracking" / "ROLLING_WORK_LEDGER.md"
        )
        if not append_row(row, ledger=ledger, project=project, timeout=request.timeout):
            return failed(
                "hook refusal recorder: ledger append failed; dedupe state unchanged"
            )
        _commit_emitted(directory / f"{key}.json", now, repeated_secret)
        return ModelHookRefusalRecordResult(
            status=EnumHookRefusalRecordStatus.EMITTED, exit_code=0, row=row, key=key
        )


def main(argv: list[str] | None = None) -> int:
    """The guards' process entry: parse argv and stdin into a request, run it."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extract-detail", action="store_true")
    parser.add_argument("--guard", help="the refusing guard's id")
    parser.add_argument(
        "--reason",
        help="a short stable token for the refusal class, not a sentence",
    )
    parser.add_argument("--detail", default="", help="the refusal's first line")
    parser.add_argument("--cwd", default=None)
    parser.add_argument("--transcript-path", default=None)
    parser.add_argument("--session-id", default=None)
    parser.add_argument("--agent-id", default=None)
    parser.add_argument(
        "--payload-stdin",
        action="store_true",
        help="read the hook's own JSON payload from stdin (never from argv)",
    )
    parser.add_argument("--window-seconds", type=int, default=DEFAULT_WINDOW_SECONDS)
    parser.add_argument("--ledger", default=None)
    parser.add_argument("--timeout", default="120s")
    parser.add_argument(
        "--hooks-lib",
        default=None,
        help="the plugin hook library directory (its siblings are imported)",
    )
    parser.add_argument(
        "--print-row",
        action="store_true",
        help="print the row instead of appending it; for tests and inspection",
    )
    args = parser.parse_args(argv)
    if args.hooks_lib:
        sys.path.insert(0, args.hooks_lib)
        from omniclaude.nodes.node_hook_refusal_record_effect.handlers import (  # noqa: PLC0415
            handler_hook_refusal_lane,
        )

        handler_hook_refusal_lane.use_hooks_lib(args.hooks_lib)
    if args.extract_detail:
        _say(extract_detail(sys.stdin.read()))
        return 0
    if not args.guard or not args.reason:
        parser.error("--guard and --reason are required for recording")

    result = HandlerHookRefusalRecord().handle(
        ModelHookRefusalRecordRequest(
            guard=args.guard,
            reason=args.reason,
            detail=args.detail,
            cwd=args.cwd,
            transcript_path=args.transcript_path,
            session_id=args.session_id,
            agent_id=args.agent_id,
            payload=read_payload(sys.stdin) if args.payload_stdin else None,
            window_seconds=args.window_seconds,
            ledger=args.ledger,
            timeout=args.timeout,
            print_row=args.print_row,
        )
    )
    for message in result.messages:
        _say(message, err=True)
    if result.status is EnumHookRefusalRecordStatus.PRINTED:
        _say(result.row)
    return result.exit_code


if __name__ == "__main__":  # pragma: no cover - process entry
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 - report failure at the process boundary
        _say("hook refusal recorder: " + redact(str(exc)), err=True)
        sys.exit(1)
