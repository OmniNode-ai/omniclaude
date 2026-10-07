# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
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

ISOLATION. Called from ``hook_record_refusal`` in ``error-guard.sh``, which
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
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TextIO

#: One row per (guard, reason, lane) per hour. An hour is the window the
#: ticket names, and it is also the cadence the morning sweep reads at, so a
#: finer window would add rows no reader distinguishes.
DEFAULT_WINDOW_SECONDS = 3600
# OMN-20343: SubagentStop retries are actionable immediately after the third
# refusal. This exception applies only to the secret guard, keyed by session.
SECRET_REPEAT_THRESHOLD = 3

#: Ledger row class. `FRICTION` is the existing class the morning friction
#: sweep already selects on; a new class would need a new reader, which is
#: how the surface being fixed here got lost in the first place.
ROW_CLASS = "FRICTION"

#: How much of the refusal text a row carries. A refusal message is a
#: paragraph; a ledger row is a line. The first line names the class, which
#: is what a reader triages on, and the guard plus reason token identify it
#: exactly.
MAX_DETAIL_CHARS = 240

#: Values that must never reach an append-only shared file. The redaction is
#: deliberately blunt: a refusal message quotes the command that was refused,
#: and a refused command is exactly the kind that carries a token.
_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"\bsk-[A-Za-z0-9]{20,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    re.compile(r"(?i)\b(secret|token|password|api[_-]?key)\s*[=:]\s*\S+"),
)

#: Segments dropped when a reason is normalised into a dedupe token. A guard
#: interpolates the offending path, branch or count into the reason it logs,
#: and a dedupe key carrying one would be unique on every refusal — which
#: would defeat the rate limit and turn this module into the second flood.
#: Any whitespace-delimited token containing a separator: a filesystem path,
#: a URL, a branch name. Removed WHOLE and BEFORE slugification — splitting
#: first would turn one path into a handful of surviving word-shaped
#: segments, which is exactly the per-instance variation the key must not
#: carry.
_PATHLIKE_SEGMENT = re.compile(r"\S*[/\\]\S*")
#: A bare number: a line number, a count, a duration. A ticket id like
#: `omn18335` is NOT dropped — it is stable for the refusal class and is the
#: most useful thing a reader can see in the key.
_BARE_NUMBER = re.compile(r"^[0-9]+$")
_SLUG_SPLIT = re.compile(r"[^a-z0-9]+")

#: Characters a ledger row cannot carry. The ledger is pipe-delimited and
#: line-oriented, so a pipe or a newline inside a field would forge a column
#: or a row to every reader that splits on them.
_FIELD_BREAKERS = re.compile(r"[|\r\n]+")


def redact(text: str) -> str:
    """Strip credential-shaped substrings and anything that breaks a row."""
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[redacted]", text)
    return _FIELD_BREAKERS.sub(" ", text).strip()


def normalise_reason(reason: str) -> str:
    """Collapse a guard's own reason text into a stable, low-cardinality token.

    Guards log a human phrase, often with the offending path or branch
    interpolated into it. That phrase identifies the refusal CLASS well and
    makes a terrible dedupe key: one refusal per path is one row per path.
    Lowercase, split on non-alphanumerics, drop the segments that carry the
    instance rather than the class, and cap the result.

    Returns ``"unspecified"`` rather than an empty token when nothing
    survives, so a row is still written and still groups.
    """
    lowered = _PATHLIKE_SEGMENT.sub(" ", reason.strip().lower())
    kept = [
        seg for seg in _SLUG_SPLIT.split(lowered) if seg and not _BARE_NUMBER.match(seg)
    ]
    # The leading words carry the class; a long tail is usually the instance.
    slug = "-".join(kept[:8])
    return slug[:64] or "unspecified"


def dedupe_key(guard: str, reason: str, lane: str) -> str:
    """Stable short key for one refusal CLASS.

    Deliberately excludes the refusal detail and the command: a guard
    refusing the same class of thing on twenty different files is one
    recurring friction, not twenty. Including the lane keeps two lanes hitting
    the same guard visible as two, which is the fact that turns "a lane is
    stuck" into "the guard is wrong".
    """
    raw = f"{guard}\x1f{reason}\x1f{lane}".encode()
    return hashlib.sha256(raw).hexdigest()[:12]


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


def build_row(
    *,
    guard: str,
    reason: str,
    lane: str,
    lane_source: str,
    detail: str,
    key: str,
    suppressed: int,
    timestamp: str,
) -> str:
    """One pipe-delimited ledger row.

    Field order and spelling follow the rows already in the ledger so an
    existing reader needs no change: leading timestamp, class, then
    ``name=value`` fields.
    """
    # Redacted here as well as at the CLI boundary. This function's contract
    # is "one well-formed row", and a caller passing raw text must not be
    # able to forge a column or a second row through it.
    detail = redact(detail)[:MAX_DETAIL_CHARS]
    return (
        f"{timestamp} | {ROW_CLASS} | lane={redact(lane) or 'unresolved'} | "
        f"actor=hook | model=none | class=refusal | guard={guard} | "
        f"reason={reason} | lane_source={lane_source} | dedupe={key} | "
        f"suppressed_since_last_row={suppressed} | "
        f'detail="{detail}" | existing=OMN-18946 | cost=~1 lane-minute | '
        "This row exists because a hook refusal is otherwise terminal-only "
        "and unaggregated (OMN-18946)"
    )


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
    lives in ``hook_refusal_lane``; the payload's own fields win over the
    environment-derived arguments, which stay as fallbacks.

    Imported lazily and defensively: this module must still write a row when
    the attribution module is missing or broken, naming the lane as
    unresolved rather than dropping the refusal. A row that names no lane is
    far better than no row, and a GUESSED lane would be worse than either --
    it would attribute one lane's friction to a neighbour.
    """
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        # Resolved at runtime from this file's own directory, so it is
        # invisible to a type checker that does not have the hooks lib on
        # its path. Imported this way on purpose: see the docstring.
        import hook_refusal_lane  # type: ignore[import-not-found,unused-ignore] # noqa: PLC0415

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
        print(
            "hook refusal recorder: ledger writer project is unavailable: "
            + redact(str(project)),
            file=sys.stderr,
        )
        return False
    if not ledger.is_file():
        print(
            "hook refusal recorder: ledger is unavailable: " + redact(str(ledger)),
            file=sys.stderr,
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
        print(
            "hook refusal recorder: ledger writer failed: " + redact(str(exc)),
            file=sys.stderr,
        )
        return False
    if completed.returncode != 0:
        print(
            f"hook refusal recorder: ledger writer exited {completed.returncode}: "
            + redact(completed.stderr or "no stderr reason")[:MAX_DETAIL_CHARS],
            file=sys.stderr,
        )
        return False
    return True


def _resolve_registry_root() -> Path | None:
    """The workspace registry root, from its env var. No default.

    An unset variable means the ledger is unreachable from here, which is a
    dropped row; a guessed default would be a row written into the wrong
    tree.
    """
    value = os.environ.get("OMNI_HOME")
    return Path(value) if value and Path(value).is_absolute() else None


def extract_detail(raw: str) -> str:
    """Read a guard's verdict, retaining the diagnostic ahead of boilerplate.

    Only safe rule IDs and line numbers are constructed by the secret guard.
    Other guards can cite user text, so apply both shared redactors BEFORE
    truncation. No raw payload, command or final message is a fallback.
    """
    from secret_redactor import redact_secrets

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


def main(argv: list[str] | None = None) -> int:
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
        "--print-row",
        action="store_true",
        help="print the row instead of appending it; for tests and inspection",
    )
    args = parser.parse_args(argv)
    if args.extract_detail:
        print(extract_detail(sys.stdin.read()))
        return 0
    if not args.guard or not args.reason:
        parser.error("--guard and --reason are required for recording")

    guard = redact(args.guard)[:64] or "unknown-guard"
    reason = normalise_reason(redact(args.reason))
    detail = redact(args.detail)[:MAX_DETAIL_CHARS]

    payload = read_payload(sys.stdin) if args.payload_stdin else None
    lane, lane_source = resolve_lane_fields(
        args.cwd,
        args.transcript_path,
        args.session_id,
        args.agent_id,
        payload=payload,
        ledger=args.ledger,
    )
    key = dedupe_key(guard, reason, lane)
    repeated_secret = guard == "subagent_stop_secret_leak_guard.sh"
    if repeated_secret:
        # Lane attribution is a separate concern. A retry budget must not be
        # shared by unrelated sessions, even when both have an unresolved lane.
        session = args.session_id or (payload or {}).get("session_id")
        session = (
            session
            or args.transcript_path
            or (payload or {}).get("agent_transcript_path")
        )
        if session:
            key = dedupe_key(guard, reason, f"{lane}:{session}")

    if args.print_row:
        print(
            build_row(
                guard=guard,
                reason=reason,
                lane=lane,
                lane_source=lane_source,
                detail=detail,
                key=key,
                suppressed=0,
                timestamp=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            )
        )
        return 0

    registry_root = _resolve_registry_root()
    if registry_root is None:
        print(
            "hook refusal recorder: OMNI_HOME must name an absolute registry root; "
            "dedupe state unchanged",
            file=sys.stderr,
        )
        return 1
    project = Path(
        os.environ.get("OMNIBASE_INTERNAL_HOME")
        or registry_root.parent / "omnibase_internal"
    )
    if not project.is_absolute():
        print(
            "hook refusal recorder: OMNIBASE_INTERNAL_HOME must be absolute; "
            "dedupe state unchanged",
            file=sys.stderr,
        )
        return 1

    directory = state_dir()
    now = time.time()
    emit, suppressed = should_emit(
        key,
        now=now,
        window_seconds=args.window_seconds,
        directory=directory,
        surface_after=SECRET_REPEAT_THRESHOLD if repeated_secret else None,
    )
    if not emit:
        return 0

    row = build_row(
        guard=guard,
        reason=reason,
        lane=lane,
        lane_source=lane_source,
        detail=detail,
        key=key,
        suppressed=suppressed,
        timestamp=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    ledger = (
        Path(args.ledger)
        if args.ledger
        else registry_root / "docs" / "tracking" / "ROLLING_WORK_LEDGER.md"
    )
    if not append_row(row, ledger=ledger, project=project, timeout=args.timeout):
        print(
            "hook refusal recorder: ledger append failed; dedupe state unchanged",
            file=sys.stderr,
        )
        return 1
    state_path = directory / f"{key}.json"
    attempts = 0
    if repeated_secret:
        try:
            attempts = max(
                0, int(json.loads(state_path.read_text()).get("attempts", 0))
            )
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        attempts += 1
    _write_state(state_path, last_emitted=now, suppressed=0, attempts=attempts)
    return 0


if __name__ == "__main__":  # pragma: no cover - process entry
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 - report failure at the process boundary
        print("hook refusal recorder: " + redact(str(exc)), file=sys.stderr)
        sys.exit(1)
