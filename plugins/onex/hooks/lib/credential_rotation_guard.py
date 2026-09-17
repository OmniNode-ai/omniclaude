#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
r"""Fail-closed credential-rotation admission gate (OMN-17957).

Why this exists
---------------
Operator ruling, 2026-09-05, firm: credential rotations keep being performed
because an agent decided that a value it saw in its own transcript -- a value
that never left the computer -- was a leak. That is a waste of time, and it
caused a five-day staging outage.

The measured incident. On 2026-08-30T09:52Z a lane rotated the Infisical
``operator-k8s`` org-admin client secret. The stated cause was an internal
least-privilege finding: a newly minted store-resolver identity could read the
org-admin pair sitting at the same Infisical path. Nothing in that ticket or its
comments claims the value was pushed to a remote, posted to Slack/Linear/GitHub,
printed into CI logs, or handed outside -- the lane's own probes state no value
was printed, logged or committed. Under the ruling that is **not exposure**.

The rotation rewrote ``dev/universal-auth-credentials`` and
``onex-dev/universal-auth-credentials``, the exact Secrets the InfisicalSecret
operator's CRs authenticate with via ``credentialsRef``. Three application
Deployments were restarted; the Infisical **operator** Deployment was neither
enumerated nor restarted, and the runbook does not name it. About fourteen hours
later all five onex-dev InfisicalSecret CRs began failing 401 ``No identity
access token found``, and managed secret sync stayed frozen cluster-wide for
five days.

A second rotation in the same 30-day window fails the same bar: a freshly minted
tenant API key was rotated solely because the invite's key had been echoed into
the session's own log.

The bar, and the approvers
--------------------------
* A value in a local transcript, log, scratch file or ledger is **NOT
  exposure**. No rotation.
* Rotation only for **real exposure** -- pushed to a remote, posted to
  Slack/Linear/GitHub, printed into CI logs, or handed outside -- with the
  exposure path recorded **first**.
* Every rotation needs explicit approval by **the operator or Jake**. No agent,
  lane or codex message is approval.
* Every rotation enumerates and restarts/re-reads **every consumer in the same
  action**, with readback.

Why a hook and not a validator
------------------------------
There is no mechanical control on this class today. The omniclaude hooks tree
carries secret-leak/redaction guards only -- they detect and redact secret
*values* in tool output. Nothing detects or refuses the mutating *command
shapes*: ``pre_tool_use_bash_guard.sh`` has no match for ``secretsmanager``,
``create-access-key``, ``client-secrets``, ``kcadm``, ``ALTER ROLE`` or
``gh secret set``. There is no analog to the ``no-raw-prod-bypass`` CI gate that
exists for prod promotion. A rotation is a command typed in a session, so no
pre-commit hook and no repo CI job ever sees it; the tool seam is the only place
it is observable before the credential is already gone. That is the same
argument, and the same primitive, as ``pre_tool_use_agent_model_guard.sh``
(OMN-17499) and ``pre_tool_use_ticket_creation_gate.sh`` (OMN-17942): it REFUSES
the tool call.

What it refuses, and what it deliberately does not
--------------------------------------------------
A shell segment whose tokens match a configured rotation shape is refused unless
the command carries::

    ROTATION-CONSENT: docs/tracking/ROLLING_WORK_LEDGER.md:<line>

resolving to an ``OPERATOR-CONSENT`` row -- rule 18 of the workspace doctrine,
extended by rule 22 with ``approved_by=<operator|jake>`` -- whose APPROVED SCOPE
names the credential the command names, and which carries an OUT OF SCOPE list.
Both lists are required: the OUT OF SCOPE half is the one that BOUNDS the grant,
and a row missing it looks identical to a valid one to the next lane that cites
it.

**Reads are never gated.** They are not allowlisted -- they simply match no
shape, because every shape lists only mutating subcommands. ``kubectl get`` /
``describe``, ``-o name``, ``aws secretsmanager get-secret-value`` /
``describe-secret`` / ``list-secrets``, ``gh secret list``, ``kcadm get`` and a
``curl`` with no mutating method are outside the vocabulary entirely.
``kubectl rollout restart`` is likewise outside it, deliberately: it is the
consumer-restart half of the remedy the ruling requires, and a gate that made
the correct repair harder than the mistake would be routed around.

Token matching, not substring matching
--------------------------------------
Each shell segment is tokenised and matched by program plus tokens, never by raw
text. ``echo 'aws secretsmanager rotate-secret'`` and a ``grep`` for the
vocabulary are not rotations, and a raw-substring rule would refuse both -- the
OCC#7213 shape, a gate firing on documentation about the gate (``omni_home``
CLAUDE.md rule 15). The consent citation itself is read from the raw command
text, because an inline environment assignment or a trailing ``#`` comment is
exactly where a caller writes it.

The selection surface is the command and its arguments (OMN-18175)
------------------------------------------------------------------
A heredoc **body** is data the command writes, not a command the shell runs, so
it is removed before the command is tokenised. Two lanes were refused in four
days for writing an ordinary file -- one a findings document, one a test fixture
-- because the body named credential vocabulary and an ordinary English
apostrophe in the prose (``the lane's own``) read to the tokeniser as an
unbalanced quote. The fail-closed refusal that followed was correct; the defect
was upstream of it, in selecting the command at all. Recorded at
``docs/tracking/ROLLING_WORK_LEDGER.md:8464`` and ``:8479``.

What the tokeniser now sees, stated precisely, because the safety argument is
entirely in this list:

* **The command line and its arguments**, byte for byte. A heredoc body starts
  on the line AFTER the redirection, so a one-line command is never rewritten --
  which is why every shape in the OMN-17957 sweep is unaffected.
* **A body redirected to a program that runs it** -- ``sh``/``bash``/``zsh``/
  ``ksh``/``dash``/``ash``, ``ssh``, ``docker``, ``podman``. That body IS a
  command, so it is tokenised as one and matched on the same terms, and an
  untokenisable one is refused. This is strictly MORE than the shipped guard saw:
  it merged such a body into the redirecting segment, where the program was
  ``bash`` and no shape could apply, so ``bash <<EOF`` + a rotation was ADMITTED.
* **A body redirected to a credential-surface program** -- one named by a policy
  shape, such as ``psql`` -- as a single argument of that segment, because that
  is what it is. ``psql <<EOF ALTER ROLE ... PASSWORD ... EOF`` is now the same
  refusal as ``psql -c "ALTER ROLE ... PASSWORD ..."``; it was admitted before.
* **Nothing else.** A body redirected to ``cat``, ``tee`` or any other sink is
  dropped, and the drop is recorded in the hook log with the delimiter, the byte
  count and the receiving program -- never the content, which can hold a value.

The guard reads no file. A path named by ``--append-file``, ``--body-file`` or
any other flag is a string in the argument list and stays one; what a lane later
writes from that file is not this command.

Two segment-boundary defects were found while making that list true, both of
them admissions rather than refusals, and both fixed here because a heredoc
makes multi-line commands the normal shape at this seam:

* An unquoted newline did not end a segment -- ``shlex`` reads it as ordinary
  whitespace -- so every line of a multi-line command was merged into one
  segment whose program came from line 1. ``echo hi`` followed by a rotation on
  the next line was ADMITTED.
* An escaped newline -- a ``\`` line continuation, which JOINS two lines -- was
  the one newline ``shlex`` does emit, and it was being treated as a separator.
  ``aws secretsmanager \`` + newline + ``rotate-secret --secret-id x`` split
  into ``aws secretsmanager``, which matches no shape, and was ADMITTED.

Measured across a 20-case before/after matrix, this module now refuses five
shapes it previously admitted and admits exactly one it previously refused --
the documentation heredoc this change exists for. No refusal was lost.

Residual, stated rather than implied: a rotation written into a file and run
later (``bash /tmp/x.sh``) is invisible here, exactly as it was before -- the
tool seam sees one command at a time, and a command in a file is a different
command. This change narrows nothing about that: it removes only text that the
shipped guard could never match a shape against anyway.

Fail-closed boundary, stated deliberately
-----------------------------------------
* A command carrying none of the rotation vocabulary never reaches this module
  at all -- the shell wrapper's pre-filter drops it. A bug here can never brick
  unrelated Bash traffic.
* A command that DOES carry the vocabulary and cannot then be evaluated -- an
  untokenisable segment, a non-string command, an unreadable policy, an
  unresolvable ``$OMNI_HOME``, an unreadable ledger, a shape whose credential
  cannot be read -- is REFUSED. An unverifiable rotation is refused, never
  assumed clean.

What this cannot do, stated rather than implied
-----------------------------------------------
No file can prove a human said the words. This gate does not establish operator
authenticity; it establishes that a durable, citable, correctly shaped row
naming the credential and an authorised approver exists in the one append-only
coordination surface **before** the rotation runs, so the authorisation is
resolvable after the session that granted it is gone. It converts a silent
rotation into one that must leave an auditable artifact. That is the same
honest limit the workspace doctrine records for the staging-namespace gate:
what is enforced is blast radius and evidence, not authenticity.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

__all__ = [
    "CONSENT_CITATION_GRAMMAR",
    "GATE_BIT_NAME",
    "Decision",
    "Finding",
    "Heredoc",
    "Policy",
    "PolicyError",
    "RotationShape",
    "check_bash_command",
    "evaluate_bash_command",
    "load_policy",
    "render_block_reason",
    "split_heredocs",
]

DEFAULT_POLICY_PATH: Final[Path] = (
    Path(__file__).resolve().parent.parent
    / "config"
    / "credential_rotation_policy.json"
)

#: The mask bit this guard is gated by. Named in every refusal so a lane that
#: believes the guard is wrong has a documented route that is not "work around
#: it". See the shell wrapper's header for why it is borrowed.
GATE_BIT_NAME: Final[str] = "PRE_TOOL_AUTHORIZATION_SHIM"

TICKET: Final[str] = "OMN-17957"

CONSENT_CITATION_GRAMMAR: Final[str] = (
    "ROTATION-CONSENT: docs/tracking/ROLLING_WORK_LEDGER.md@<row timestamp> "
    "(or the older :<line> form)"
)

#: The citation, read from the raw command text. TWO FORMS (OMN-18620).
#:
#: ``@<row timestamp>`` is the durable one and the one to write. A line number
#: is only true until the ledger is next rolled: a cap-crossing roll on
#: 2026-09-17 removed 926 lines from the top of the live file, which moved the
#: operator's qwen hold ruling from ``:4311`` to ``:3385`` and a consent row
#: from ``:4367`` to ``:3441``. A pending rotation citing either by line would
#: then resolve to a DIFFERENT row, and this guard would refuse a legitimate
#: rotation while reporting a reason that describes the wrong row entirely.
#:
#: A row timestamp travels with the row -- into the archive when it is rolled --
#: so the timestamp form survives any number of rolls. The line form is kept
#: working because citations already written must not be invalidated by the
#: change that introduces the replacement.
_CITATION: Final[re.Pattern[str]] = re.compile(
    r"ROTATION-CONSENT:\s*(?P<path>[^\s:@'\"]+)"
    r"(?::(?P<line>\d+)|@(?P<stamp>[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z))"
)

#: Shell separators that end one segment and begin another. Matched outside
#: quotes only, which ``shlex`` handles for us by tokenising the whole command
#: once and splitting the TOKEN stream rather than the text.
#:
#: A newline is deliberately NOT here. The only newline ``shlex`` ever emits as
#: a token is an ESCAPED one -- a ``\`` line continuation, which joins two lines
#: into one command rather than separating them. Treating it as a separator is
#: how the shipped guard admitted
#: ``aws secretsmanager \<newline> rotate-secret --secret-id x``: the first
#: segment became ``aws secretsmanager`` with no mutating subcommand, and
#: matched nothing. Real unquoted newlines are made explicit by
#: ``split_heredocs`` before the text ever reaches ``shlex``.
_SEPARATORS: Final[frozenset[str]] = frozenset({";", "&&", "||", "|", "&"})

#: A line-continuation artifact in the token stream: whitespace inside one
#: command, dropped rather than split on.
_CONTINUATION_NEWLINE: Final[str] = "\n"

#: Wrapper programs that prefix a real command. Stripped before the program of a
#: segment is read, so `sudo aws secretsmanager rotate-secret` is still an aws
#: rotation.
_WRAPPERS: Final[frozenset[str]] = frozenset(
    {"sudo", "env", "command", "time", "nohup", "nice", "xargs", "doas"}
)

_ASSIGNMENT: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

#: Programs that RUN their heredoc body as commands, so the body stays in the
#: selection surface and is tokenised as a command in its own right. A program
#: absent from this set and from every shape's ``programs`` receives its body as
#: data -- ``cat``, ``tee`` and every other sink -- and the body is dropped.
#:
#: ``python``/``perl``/``ruby`` are deliberately absent. A body they run is
#: their own language, not shell, so tokenising it against shell shapes would
#: match nothing it should and could match things it should not; a rotation
#: driven from inside an interpreted script is the same residual as a rotation
#: written to a file and run later, and is not made smaller by pretending to
#: read it.
_BODY_EXECUTING_PROGRAMS: Final[frozenset[str]] = frozenset(
    {"sh", "bash", "zsh", "ksh", "dash", "ash", "ssh", "docker", "podman"}
)

#: How deep a heredoc body may nest another executed heredoc before the guard
#: stops descending. Three is far past any real command; the bound exists so a
#: pathological payload cannot spend the session's time here.
_MAX_BODY_DEPTH: Final[int] = 3

#: The token left in the visible text where a heredoc redirection stood, so a
#: body can be attributed to the segment that owns it after tokenising. The
#: spelling is chosen to match no shape's credential pattern: every one of those
#: is either anchored to URL/SQL text or restricted to ``[A-Za-z0-9_.-]`` /
#: ``[a-z0-9]``-initial tokens, and ``@`` is in neither class. A test pins that
#: a marker is never reported as the credential.
_HEREDOC_MARKER: Final[str] = "@@onex-heredoc-{index}@@"

#: Characters that end a heredoc delimiter word.
_DELIMITER_STOP: Final[str] = " \t;&|<>()"

#: `approved_by=<name>`, the OMN-17957 rule-22 extension to the rule-18 row.
_APPROVED_BY: Final[re.Pattern[str]] = re.compile(
    r"(?<![\w-])approved_by\s*=\s*([A-Za-z0-9_.-]+)", re.IGNORECASE
)

_REQUIRED_ROW_KIND: Final[str] = "OPERATOR-CONSENT"
_APPROVED_SCOPE: Final[str] = "APPROVED SCOPE:"
_OUT_OF_SCOPE: Final[str] = "OUT OF SCOPE:"

#: Exactly two people may approve, and that is a property of the ruling rather
#: than of the config. A policy naming a different number is refused.
_REQUIRED_APPROVER_COUNT: Final[int] = 2


class PolicyError(RuntimeError):
    """The rotation policy could not be read.

    Raised rather than defaulting to a permissive policy: a policy that cannot
    be parsed is an unknown policy, and an unknown policy that admits everything
    is a gate reporting green while enforcing nothing.
    """


@dataclass(frozen=True, slots=True)
class RotationShape:
    """One command shape that mutates, issues or revokes a credential."""

    id: str
    description: str
    programs: frozenset[str]
    all_of: tuple[re.Pattern[str], ...]
    any_of: tuple[re.Pattern[str], ...]
    adjacent: tuple[tuple[re.Pattern[str], re.Pattern[str]], ...]
    credential_flags: tuple[str, ...]
    credential_patterns: tuple[re.Pattern[str], ...]
    credential_skips_flag_values: bool


@dataclass(frozen=True, slots=True)
class Policy:
    """The rotation vocabulary and the approver set, read from config."""

    approvers: frozenset[str]
    #: The approver names in config order, for rendering. The ruling reads "the
    #: operator or Jake"; sorting would render it "jake or operator", which
    #: quietly rewrites a quoted ruling into something nobody said.
    approver_display: str
    consent_ledger_paths: frozenset[str]
    consent_ledger_path_prefixes: tuple[str, ...]
    rotation_shapes: tuple[RotationShape, ...]


@dataclass(frozen=True, slots=True)
class Heredoc:
    """One heredoc body, lifted out of the command before it is tokenised."""

    marker: str
    delimiter: str
    body: str


@dataclass(frozen=True, slots=True)
class Finding:
    """One failing admission rule.

    ``code`` is stable and machine-greppable; ``reason`` says what is wrong and
    ``fix`` says what to do about it. Both are rendered, because a refusal that
    names a problem without naming its remedy is a refusal a lane routes around.
    """

    code: str
    shape_id: str
    credential: str
    reason: str
    fix: str


# ---------------------------------------------------------------------------
# Policy loading
# ---------------------------------------------------------------------------


def _require_str(raw: Any, key: str, source: Path) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise PolicyError(f"{source}: '{key}' must be a non-empty string, got {raw!r}")
    return raw.strip()


def _str_tuple(
    raw: Any, key: str, source: Path, *, allow_empty: bool = False
) -> tuple[str, ...]:
    if raw is None and allow_empty:
        return ()
    if not isinstance(raw, list):
        raise PolicyError(f"{source}: '{key}' must be a list of strings, got {raw!r}")
    if not raw and not allow_empty:
        raise PolicyError(f"{source}: '{key}' must not be empty")
    out: list[str] = []
    for entry in raw:
        if not isinstance(entry, str) or not entry.strip():
            raise PolicyError(
                f"{source}: '{key}' has a blank or non-string entry {entry!r}"
            )
        out.append(entry.strip())
    return tuple(out)


def _compile_all(
    raw: Any, key: str, source: Path, *, allow_empty: bool = False
) -> tuple[re.Pattern[str], ...]:
    compiled: list[re.Pattern[str]] = []
    for pattern in _str_tuple(raw, key, source, allow_empty=allow_empty):
        try:
            compiled.append(re.compile(pattern))
        except re.error as exc:
            raise PolicyError(
                f"{source}: '{key}' entry {pattern!r} is not a valid regex ({exc})"
            ) from exc
    return tuple(compiled)


def _load_shape(raw: Any, source: Path) -> RotationShape:
    if not isinstance(raw, dict):
        raise PolicyError(
            f"{source}: each rotation shape must be an object, got {raw!r}"
        )
    shape_id = _require_str(raw.get("id"), "rotation_shapes[].id", source)
    adjacent_raw = raw.get("adjacent") or []
    if not isinstance(adjacent_raw, list):
        raise PolicyError(f"{source}: {shape_id}: 'adjacent' must be a list of pairs")
    adjacent: list[tuple[re.Pattern[str], re.Pattern[str]]] = []
    for pair in adjacent_raw:
        if not isinstance(pair, list) or len(pair) != 2:
            raise PolicyError(
                f"{source}: {shape_id}: 'adjacent' entries must be two-element lists, got {pair!r}"
            )
        left, right = _compile_all(pair, f"{shape_id}.adjacent", source)
        adjacent.append((left, right))
    return RotationShape(
        id=shape_id,
        description=_require_str(
            raw.get("description"), f"{shape_id}.description", source
        ),
        programs=frozenset(
            _str_tuple(raw.get("programs"), f"{shape_id}.programs", source)
        ),
        all_of=_compile_all(
            raw.get("all_of"), f"{shape_id}.all_of", source, allow_empty=True
        ),
        any_of=_compile_all(
            raw.get("any_of"), f"{shape_id}.any_of", source, allow_empty=True
        ),
        adjacent=tuple(adjacent),
        credential_flags=_str_tuple(
            raw.get("credential_flags"),
            f"{shape_id}.credential_flags",
            source,
            allow_empty=True,
        ),
        credential_patterns=_compile_all(
            raw.get("credential_patterns"),
            f"{shape_id}.credential_patterns",
            source,
            allow_empty=True,
        ),
        credential_skips_flag_values=bool(
            raw.get("credential_skips_flag_values", False)
        ),
    )


def load_policy(path: Path | None = None) -> Policy:
    """Read the rotation vocabulary, or raise.

    There is no default policy in code. A missing or malformed config refuses
    every rotation until it is repaired, which is loud, rather than silently
    widening what may rotate, which is not.
    """
    source = path or DEFAULT_POLICY_PATH
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PolicyError(f"rotation policy not found at {source}") from exc
    except json.JSONDecodeError as exc:
        raise PolicyError(f"{source}: not valid JSON ({exc})") from exc
    except OSError as exc:
        raise PolicyError(f"{source}: unreadable ({exc})") from exc
    if not isinstance(raw, dict):
        raise PolicyError(
            f"{source}: top level must be an object, got {type(raw).__name__}"
        )

    approvers = _str_tuple(raw.get("approvers"), "approvers", source)
    if len({a.lower() for a in approvers}) != _REQUIRED_APPROVER_COUNT:
        raise PolicyError(
            f"{source}: 'approvers' must name exactly {_REQUIRED_APPROVER_COUNT} "
            f"distinct people (the operator and Jake, per the 2026-09-05 ruling); "
            f"got {list(approvers)!r}. Widening the approver set is a decision "
            f"about who may authorise a rotation, not a config bump."
        )

    shapes_raw = raw.get("rotation_shapes")
    if not isinstance(shapes_raw, list) or not shapes_raw:
        raise PolicyError(f"{source}: 'rotation_shapes' must be a non-empty list")
    shapes = tuple(_load_shape(entry, source) for entry in shapes_raw)
    seen: set[str] = set()
    for shape in shapes:
        if shape.id in seen:
            raise PolicyError(f"{source}: duplicate rotation shape id {shape.id!r}")
        seen.add(shape.id)

    return Policy(
        approvers=frozenset(a.lower() for a in approvers),
        approver_display=" or ".join(approvers),
        consent_ledger_paths=frozenset(
            _str_tuple(raw.get("consent_ledger_paths"), "consent_ledger_paths", source)
        ),
        consent_ledger_path_prefixes=_str_tuple(
            raw.get("consent_ledger_path_prefixes"),
            "consent_ledger_path_prefixes",
            source,
            allow_empty=True,
        ),
        rotation_shapes=shapes,
    )


# ---------------------------------------------------------------------------
# Command tokenising
# ---------------------------------------------------------------------------


class _Untokenisable(RuntimeError):
    """The command carries rotation vocabulary and cannot be tokenised."""


def _read_delimiter(line: str, index: int) -> tuple[str, int]:
    """Read the heredoc delimiter word at ``index``, resolving its quoting.

    ``<<EOF``, ``<<'EOF'``, ``<<"EOF"`` and ``<<\\EOF`` all delimit on ``EOF``;
    the quoting decides whether the shell expands the body, which is irrelevant
    here because the body is never executed by this guard.
    """
    parts: list[str] = []
    length = len(line)
    while index < length:
        char = line[index]
        if char in _DELIMITER_STOP:
            break
        if char in "'\"":
            close = line.find(char, index + 1)
            if close == -1:
                parts.append(line[index + 1 :])
                index = length
                break
            parts.append(line[index + 1 : close])
            index = close + 1
            continue
        if char == "\\" and index + 1 < length:
            parts.append(line[index + 1])
            index += 2
            continue
        parts.append(char)
        index += 1
    return "".join(parts), index


def _scan_line(
    line: str, quote: str | None, next_index: int
) -> tuple[str, list[tuple[str, bool, str]], str | None]:
    """Replace each heredoc redirection on ``line`` with a marker token.

    Returns the rewritten line, the heredocs it opened in order, and the quoting
    state at end of line. Only text on THIS line is rewritten: a heredoc body
    lives on the lines that follow, so a single-line command comes back
    byte-identical.
    """
    out: list[str] = []
    pending: list[tuple[str, bool, str]] = []
    index = 0
    length = len(line)
    while index < length:
        char = line[index]
        if char == "\\" and quote != "'" and index + 1 < length:
            out.append(line[index : index + 2])
            index += 2
            continue
        if quote is None and char in "'\"":
            quote = char
            out.append(char)
            index += 1
            continue
        if quote is not None and char == quote:
            quote = None
            out.append(char)
            index += 1
            continue
        if quote is None and line.startswith("<<", index):
            if line.startswith("<<<", index):
                # A here-STRING is an argument on this line, not a body.
                out.append("<<<")
                index += 3
                continue
            cursor = index + 2
            if cursor < length and line[cursor] == "-":
                cursor += 1
            while cursor < length and line[cursor] in " \t":
                cursor += 1
            delimiter, cursor = _read_delimiter(line, cursor)
            if not delimiter:
                out.append("<<")
                index += 2
                continue
            marker = _HEREDOC_MARKER.format(index=next_index + len(pending))
            out.append(marker)
            pending.append((delimiter, line[index + 2 : index + 3] == "-", marker))
            index = cursor
            continue
        out.append(char)
        index += 1
    return "".join(out), pending, quote


def _is_continuation(line: str) -> bool:
    """True when ``line`` ends in an odd number of backslashes.

    An even count is an escaped backslash, which ends the line for real.
    """
    return (len(line) - len(line.rstrip("\\"))) % 2 == 1


def split_heredocs(command: str) -> tuple[str, dict[str, Heredoc]]:
    """Lift every heredoc body out of ``command`` (OMN-18175).

    Returns the visible text -- the command and its arguments, with each heredoc
    redirection replaced by a marker token -- and the bodies by marker. The body
    lines and the terminator line are removed entirely.

    The scan tracks quoting the way a shell does, and it does NOT track quoting
    through a body: a body is consumed verbatim from the newline to its
    delimiter. That is what makes an apostrophe in prose harmless here -- it is
    never read as a quote, because the body is never read as shell at all.
    """
    lines = command.split("\n")
    rendered: list[str] = []
    heredocs: dict[str, Heredoc] = {}
    quote: str | None = None
    index = 0
    while index < len(lines):
        text, pending, quote = _scan_line(lines[index], quote, len(heredocs))
        if index + 1 < len(lines) and quote is None and not _is_continuation(text):
            # An unquoted newline ENDS a command. `shlex` treats it as plain
            # whitespace, which silently merged every line of a multi-line
            # command into one segment: the shipped guard admitted
            # `echo hi\naws secretsmanager rotate-secret ...` outright, because
            # the segment's program was `echo`. Heredocs make multi-line
            # commands the normal case here, so the separator is made explicit.
            text = f"{text} ;"
        rendered.append(text)
        index += 1
        for delimiter, strip_tabs, marker in pending:
            body: list[str] = []
            while index < len(lines):
                candidate = lines[index]
                probe = candidate.lstrip("\t") if strip_tabs else candidate
                index += 1
                if probe.rstrip("\r") == delimiter:
                    break
                body.append(candidate)
            heredocs[marker] = Heredoc(
                marker=marker, delimiter=delimiter, body="\n".join(body)
            )
    return "\n".join(rendered), heredocs


def _dropped_body_note(doc: Heredoc, program: str) -> str:
    """Record a body that was NOT evaluated, without echoing a byte of it.

    A body can carry a credential value, so the note names the delimiter the
    author chose, the size, and the program the body was handed to -- the three
    facts that make the decision auditable -- and nothing from inside it.
    """
    return (
        f"NOT SELECTED: heredoc body with delimiter {doc.delimiter!r} "
        f"({len(doc.body.encode('utf-8'))} bytes) was redirected to {program!r}, "
        f"which does not run its input, so it is data the command writes rather "
        f"than a command the shell runs and it was not evaluated as a rotation "
        f"(OMN-18175). The command and its arguments were evaluated in full."
    )


def _segments(command: str) -> list[list[str]]:
    """Split ``command`` into shell segments, as token lists.

    ``shlex`` in POSIX mode resolves quoting for us, so a separator inside a
    quoted string is a token of that string rather than a segment boundary, and
    a quoted rotation verb never becomes the program of a segment.
    """
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError as exc:  # unbalanced quote, unterminated escape
        raise _Untokenisable(str(exc)) from exc

    out: list[list[str]] = [[]]
    for token in tokens:
        if token == _CONTINUATION_NEWLINE:
            continue
        if token in _SEPARATORS:
            out.append([])
            continue
        out[-1].append(token)
    return [segment for segment in out if segment]


def _program_of(segment: list[str]) -> tuple[str, list[str]]:
    """Return the program basename and the remaining tokens.

    Leading ``VAR=value`` assignments and wrapper programs are stripped, so an
    inline environment assignment or a ``sudo`` prefix cannot hide the shape.
    """
    index = 0
    while index < len(segment):
        token = segment[index]
        if _ASSIGNMENT.match(token):
            index += 1
            continue
        basename = os.path.basename(token)
        if basename in _WRAPPERS:
            index += 1
            # `env -u PYTHONPATH aws ...`: skip env's own flags and assignments.
            while index < len(segment) and (
                segment[index].startswith("-") or _ASSIGNMENT.match(segment[index])
            ):
                # `-u NAME` takes a value.
                if segment[index] in {"-u", "-C", "-S"} and index + 1 < len(segment):
                    index += 1
                index += 1
            continue
        return basename, segment[index + 1 :]
    return "", []


def _matches(shape: RotationShape, program: str, tokens: list[str]) -> bool:
    if program not in shape.programs:
        return False
    for pattern in shape.all_of:
        if not any(pattern.search(token) for token in tokens):
            return False
    if shape.any_of or shape.adjacent:
        hit = any(pattern.search(token) for pattern in shape.any_of for token in tokens)
        if not hit:
            hit = any(
                left.search(tokens[i]) and right.search(tokens[i + 1])
                for left, right in shape.adjacent
                for i in range(len(tokens) - 1)
            )
        if not hit:
            return False
    return True


def _credential_of(shape: RotationShape, tokens: list[str]) -> str:
    """Read the credential this segment names, or ``""`` when it names none."""
    for index, token in enumerate(tokens):
        for flag in shape.credential_flags:
            if token == flag and index + 1 < len(tokens):
                return tokens[index + 1].strip()
            if token.startswith(f"{flag}="):
                return token[len(flag) + 1 :].strip()
    candidates = _credential_candidates(shape, tokens)
    for pattern in shape.credential_patterns:
        for token in candidates:
            match = pattern.search(token)
            if match and match.lastindex:
                return match.group(1).strip()
    return ""


def _credential_candidates(shape: RotationShape, tokens: list[str]) -> list[str]:
    """The tokens the credential may be read from.

    With ``credential_skips_flag_values`` a flag and the value that follows it
    are both skipped. kubectl needs that: without it ``-n onex-dev`` makes the
    NAMESPACE look like the credential, so a grant scoped to the credential is
    checked against the wrong name and a correct rotation is refused. psql must
    NOT set it -- there the credential lives inside the ``-c`` flag's own value.
    """
    if not shape.credential_skips_flag_values:
        return tokens
    out: list[str] = []
    skip_next = False
    for token in tokens:
        if skip_next:
            skip_next = False
            continue
        if token.startswith("-"):
            skip_next = "=" not in token
            continue
        out.append(token)
    return out


# ---------------------------------------------------------------------------
# The consent row
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _ConsentVerdict:
    code: str | None
    reason: str
    fix: str
    scope: str


def _citation_path_is_canonical(cited: str, policy: Policy) -> bool:
    normalised = cited.strip().lstrip("./")
    if ".." in Path(normalised).parts or Path(normalised).is_absolute():
        return False
    if normalised in policy.consent_ledger_paths:
        return True
    return any(
        normalised.startswith(prefix) for prefix in policy.consent_ledger_path_prefixes
    )


def _archive_dir_for(ledger: Path) -> Path:
    """Where a roll of ``ledger`` puts the rows it removed."""
    return ledger.parent / "archive"


def _rows_with_stamp(rows: list[str], stamp: str) -> list[str]:
    """Every row whose FIRST field is exactly ``stamp``.

    First field, not "contains": a row body routinely quotes other rows'
    timestamps, and matching those would resolve a citation to a row that merely
    mentions the one meant.
    """
    return [row for row in rows if row.split("|", 1)[0].strip() == stamp]


def _cited_ref(cited: str, match: re.Match[str]) -> str:
    """The citation as the author wrote it, for use in refusal text.

    Echoing the author's own form matters: telling someone their line citation
    is wrong by quoting a timestamp they never typed sends them looking in the
    wrong place.
    """
    stamp = match.group("stamp")
    return f"{cited}@{stamp}" if stamp is not None else f"{cited}:{match.group('line')}"


def _read_consent_row(
    command: str, policy: Policy, omni_home: Path
) -> _ConsentVerdict | None:
    """Resolve the citation in ``command``, or ``None`` when there is none."""
    match = _CITATION.search(command)
    if match is None:
        return None

    cited = match.group("path")
    if not _citation_path_is_canonical(cited, policy):
        allowed = ", ".join(sorted(policy.consent_ledger_paths))
        return _ConsentVerdict(
            code="consent_path_not_canonical",
            reason=(
                f"the citation names {cited!r}, which is not the append-only "
                f"coordination surface a consent row lives in"
            ),
            fix=(
                f"cite a row in {allowed} (or a docs/tracking/archive/ roll), "
                "appended through scripts/ledger_lock.py. A lane that may cite "
                "any file it can write has not been authorised by anybody"
            ),
            scope="",
        )

    ledger = omni_home / cited
    try:
        rows = ledger.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return _ConsentVerdict(
            code="consent_ledger_unreadable",
            reason=f"the cited ledger {ledger} could not be read ({exc})",
            fix=(
                "set OMNI_HOME to the omni_home clone and cite a line that "
                "exists in its rolling ledger"
            ),
            scope="",
        )

    stamp = match.group("stamp")
    if stamp is not None:
        located = _rows_with_stamp(rows, stamp)
        if not located and _archive_dir_for(ledger).is_dir():
            # A rolled row is still a real consent row. This is the whole point
            # of the timestamp form: the row moved into the archive and its
            # timestamp went with it.
            for archive in sorted(_archive_dir_for(ledger).glob("*.md")):
                try:
                    archived = archive.read_text(encoding="utf-8").splitlines()
                except OSError:
                    continue
                located.extend(_rows_with_stamp(archived, stamp))
        if not located:
            return _ConsentVerdict(
                code="consent_stamp_absent",
                reason=(
                    f"no row in {cited} or its archive carries the timestamp {stamp}"
                ),
                fix=(
                    "cite the timestamp the consent row actually opens with, "
                    "copied from the row rather than retyped"
                ),
                scope="",
            )
        if len(located) > 1:
            # AMBIGUITY IS A REFUSAL, never a pick. Two lanes can append inside
            # the same second, so a timestamp is not guaranteed unique, and
            # choosing one of several rows would mean this guard authorising a
            # rotation against a row nobody cited.
            return _ConsentVerdict(
                code="consent_stamp_ambiguous",
                reason=(
                    f"{len(located)} rows carry the timestamp {stamp}, so the "
                    "citation does not name one row"
                ),
                fix=(
                    "cite the line form for this row instead, or have the "
                    "approver re-append the consent row so its timestamp is "
                    "unique"
                ),
                scope="",
            )
        row = located[0]
    else:
        line_no = int(match.group("line"))
        if line_no < 1 or line_no > len(rows):
            return _ConsentVerdict(
                code="consent_line_absent",
                reason=(
                    f"the citation names line {line_no} of {cited}, which has "
                    f"{len(rows)} lines"
                ),
                fix=(
                    "cite the line number the consent row actually occupies, or "
                    "better, cite it as <path>@<row timestamp>, which a ledger "
                    "roll cannot move"
                ),
                scope="",
            )
        row = rows[line_no - 1]
    fields = [field.strip() for field in row.split("|")]
    if _REQUIRED_ROW_KIND not in fields:
        return _ConsentVerdict(
            code="consent_row_not_operator_consent",
            reason=(
                f"{_cited_ref(cited, match)} is not an {_REQUIRED_ROW_KIND} row -- its "
                f"fields are {fields[:3]!r}"
            ),
            fix=(
                f"cite a row whose second field is exactly {_REQUIRED_ROW_KIND}. "
                "A CLAIM, NOTE or TERMINAL row records what a lane did; it does "
                "not authorise anything"
            ),
            scope="",
        )

    scope_fields = [f for f in fields if f.upper().startswith(_APPROVED_SCOPE)]
    out_fields = [f for f in fields if f.upper().startswith(_OUT_OF_SCOPE)]
    scope = scope_fields[0][len(_APPROVED_SCOPE) :].strip() if scope_fields else ""
    if not scope or not out_fields or not out_fields[0][len(_OUT_OF_SCOPE) :].strip():
        return _ConsentVerdict(
            code="consent_missing_scope_list",
            reason=(
                f"{_cited_ref(cited, match)} does not carry both a non-empty "
                f"'{_APPROVED_SCOPE}' and a non-empty '{_OUT_OF_SCOPE}' list"
            ),
            fix=(
                "both lists are required. The OUT OF SCOPE half is the one that "
                "BOUNDS the grant, and a row missing it looks identical to a "
                "valid one to the next lane that cites it"
            ),
            scope="",
        )

    approver_match = _APPROVED_BY.search(row)
    approver = approver_match.group(1).lower() if approver_match else ""
    if approver not in policy.approvers:
        named = " or ".join(sorted(policy.approvers))
        return _ConsentVerdict(
            code="consent_approver_not_authorized",
            reason=(
                f"{_cited_ref(cited, match)} carries approved_by={approver or '(absent)'}, "
                f"which is not {named}"
            ),
            fix=(
                f"a credential rotation is approved by {named} and by nobody "
                "else. No agent, lane or codex message is approval, and a lane "
                "cannot approve itself"
            ),
            scope="",
        )

    return _ConsentVerdict(code=None, reason="", fix="", scope=scope)


def _scope_names(scope: str, credential: str) -> bool:
    """True when ``scope`` names ``credential``, matched on word boundaries."""
    if not credential:
        return False
    return (
        re.search(
            rf"(?<![\w.-]){re.escape(credential)}(?![\w.-])", scope, re.IGNORECASE
        )
        is not None
    )


# ---------------------------------------------------------------------------
# The check
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Decision:
    """The verdict for one Bash command, and what was left out of it.

    ``notes`` carries every heredoc body that was NOT evaluated. It is written
    to the hook log on the allow path so a non-selection is auditable rather
    than invisible: a guard that silently narrows what it looks at is
    indistinguishable from a guard that is not running.
    """

    findings: list[Finding]
    notes: list[str]


def _selection_surface(
    command: str, policy: Policy, depth: int = 0
) -> tuple[list[tuple[str, list[str]]], list[str], list[str]]:
    """Return the ``(program, tokens)`` segments to match, the notes, and the
    text a consent citation may be written in.

    Raises ``_Untokenisable`` when the command and its arguments -- or the body
    of a heredoc that is executed -- cannot be parsed.
    """
    visible, heredocs = split_heredocs(command)
    shape_programs = {
        program for shape in policy.rotation_shapes for program in shape.programs
    }
    segments: list[tuple[str, list[str]]] = []
    notes: list[str] = []
    citation_text: list[str] = [visible]
    claimed: set[str] = set()

    for raw_segment in _segments(visible):
        program, tokens = _program_of(raw_segment)
        if not program:
            continue
        owned = [heredocs[token] for token in tokens if token in heredocs]
        claimed.update(doc.marker for doc in owned)
        enriched = list(tokens)
        for doc in owned:
            if program in shape_programs:
                # The body is stdin to a credential-surface program, which makes
                # it an argument of that command: `psql <<EOF ALTER ROLE ...` is
                # the rotation `psql -c "ALTER ROLE ..."` is.
                enriched.append(doc.body)
                citation_text.append(doc.body)
            elif program in _BODY_EXECUTING_PROGRAMS and depth < _MAX_BODY_DEPTH:
                inner_segments, inner_notes, inner_text = _selection_surface(
                    doc.body, policy, depth + 1
                )
                segments.extend(inner_segments)
                notes.extend(inner_notes)
                citation_text.extend(inner_text)
            else:
                notes.append(_dropped_body_note(doc, program))
        segments.append((program, enriched))

    for marker, doc in heredocs.items():
        if marker not in claimed:
            notes.append(_dropped_body_note(doc, "(no command)"))

    return segments, notes, citation_text


def check_bash_command(command: Any, policy: Policy, omni_home: Path) -> list[Finding]:
    """Return every failing rule for one Bash command.

    An empty list admits the command. A command matching no rotation shape --
    every read, and every unrelated command -- returns an empty list without
    ever touching the ledger.
    """
    return evaluate_bash_command(command, policy, omni_home).findings


def evaluate_bash_command(command: Any, policy: Policy, omni_home: Path) -> Decision:
    """Decide one Bash command, and report what was excluded from the decision."""
    if not isinstance(command, str) or not command.strip():
        return Decision(
            findings=[
                Finding(
                    code="unevaluable",
                    shape_id="",
                    credential="",
                    reason=(
                        f"the Bash call carries no command string (got "
                        f"{type(command).__name__}), so a rotation cannot be "
                        f"ruled out"
                    ),
                    fix="re-issue the call with the command as a string",
                )
            ],
            notes=[],
        )

    try:
        segments, notes, citation_parts = _selection_surface(command, policy)
    except _Untokenisable as exc:
        return Decision(
            findings=[
                Finding(
                    code="unevaluable",
                    shape_id="",
                    credential="",
                    reason=(
                        f"the command carries credential-rotation vocabulary and "
                        f"cannot be tokenised ({exc}), so the guard cannot tell "
                        f"which credential it mutates"
                    ),
                    fix=(
                        "balance the quoting and re-issue the command. An "
                        "unverifiable rotation is refused, never assumed clean. "
                        "Note that a heredoc BODY is no longer read as shell "
                        "(OMN-18175), so this is an unbalanced quote in the "
                        "command itself or in a heredoc that is executed"
                    ),
                )
            ],
            notes=[],
        )

    hits: list[tuple[RotationShape, str]] = []
    for program, tokens in segments:
        for shape in policy.rotation_shapes:
            if _matches(shape, program, tokens):
                hits.append((shape, _credential_of(shape, tokens)))
                break

    if not hits:
        return Decision(findings=[], notes=notes)

    consent = _read_consent_row("\n".join(citation_parts), policy, omni_home)
    findings: list[Finding] = []

    if consent is None:
        for shape, credential in hits:
            findings.append(
                Finding(
                    code="rotation_without_consent",
                    shape_id=shape.id,
                    credential=credential,
                    reason=(
                        f"{shape.description} -- and the command carries no "
                        f"consent citation"
                    ),
                    fix=(
                        f"do not rotate. If the credential is genuinely exposed "
                        f"and the operator or Jake has approved it, append the "
                        f"OPERATOR-CONSENT row through scripts/ledger_lock.py "
                        f"and cite it as '{CONSENT_CITATION_GRAMMAR}'"
                    ),
                )
            )
        return Decision(findings=findings, notes=notes)

    if consent.code is not None:
        for shape, credential in hits:
            findings.append(
                Finding(
                    code=consent.code,
                    shape_id=shape.id,
                    credential=credential,
                    reason=consent.reason,
                    fix=consent.fix,
                )
            )
        return Decision(findings=findings, notes=notes)

    for shape, credential in hits:
        if not credential:
            findings.append(
                Finding(
                    code="credential_unnamed",
                    shape_id=shape.id,
                    credential="",
                    reason=(
                        f"{shape.description} -- but the command names no "
                        f"credential the guard can read, so the cited consent "
                        f"scope cannot be checked against it"
                    ),
                    fix=(
                        "name the credential explicitly on the command line so "
                        "the grant can be matched to it"
                    ),
                )
            )
            continue
        if not _scope_names(consent.scope, credential):
            findings.append(
                Finding(
                    code="consent_scope_omits_credential",
                    shape_id=shape.id,
                    credential=credential,
                    reason=(
                        f"the cited row's APPROVED SCOPE does not name "
                        f"{credential!r}; it reads: {consent.scope}"
                    ),
                    fix=(
                        f"a grant authorises the credentials its scope names and "
                        f"no others. Get {credential!r} named in an APPROVED "
                        f"SCOPE, or do not rotate it"
                    ),
                )
            )

    return Decision(findings=findings, notes=notes)


def render_block_reason(findings: list[Finding], policy: Policy) -> str:
    """Render one refusal that states the ruling, the bar, and every failure.

    Every rule at once, not the first: a guard that reports one problem per
    attempt turns a single fix into several round trips, and each round trip is
    a chance for the lane to reach for a surface the gate does not see.
    """
    approvers = policy.approver_display
    lines = [
        f"BLOCKED: this looks like a credential rotation, re-issue or revoke, "
        f"and it is not authorised ({TICKET}).",
        "",
        (
            "Operator ruling, 2026-09-05, firm. Credential rotations keep being "
            "performed because an agent decided that a value it saw in a local "
            "transcript, log, scratch file or ledger was a leak. A value that "
            "never left the computer is NOT exposure and is not a reason to "
            "rotate; the 2026-08-30 rotation taken on exactly that reasoning "
            "froze secret sync cluster-wide for five days. Rotate only for real "
            "exposure -- pushed to a remote, posted to Slack/Linear/GitHub, "
            "printed into CI logs, or handed outside -- with the exposure path "
            f"recorded FIRST; every rotation is approved explicitly by "
            f"{approvers} and by nobody else; and every rotation enumerates and "
            "restarts or re-reads EVERY consumer in the same action, with "
            "readback. No agent, lane or codex message is approval."
        ),
        "",
    ]
    for finding in findings:
        target = f" [{finding.credential}]" if finding.credential else ""
        lines.append(
            f"  * [{finding.code}] {finding.shape_id}{target}: {finding.reason}"
        )
        lines.append(f"      fix: {finding.fix}")
    lines.extend(
        [
            "",
            (
                "To proceed on a real, approved exposure, carry the citation on "
                f"the command line or in an inline assignment: '{CONSENT_CITATION_GRAMMAR}' "
                "pointing at an OPERATOR-CONSENT row (omni_home CLAUDE.md rules "
                "18 and 22) that carries approved_by=<"
                + "|".join(sorted(policy.approvers))
                + ">, an APPROVED SCOPE naming this credential, and an OUT OF "
                "SCOPE list."
            ),
            (
                "Reads are never gated: get, describe, list, -o name, "
                "get-secret-value, gh secret list, and kubectl rollout restart "
                "all pass untouched."
            ),
            f"To disable this guard deliberately: onex hooks disable {GATE_BIT_NAME}",
        ]
    )
    return "\n".join(lines)


def _block(reason: str) -> int:
    json.dump({"decision": "block", "reason": reason}, sys.stdout)
    sys.stdout.write("\n")
    return 3


def main(argv: list[str] | None = None) -> int:
    """Hook entry point. Reads the PreToolUse JSON on stdin.

    Exit codes: ``0`` allow, ``3`` block (payload on stdout), ``1`` the guard
    itself could not decide. The shell wrapper treats ``1`` as a block too -- a
    command carrying rotation vocabulary that cannot be evaluated is refused,
    never assumed clean.
    """
    parser = argparse.ArgumentParser(description="credential-rotation admission gate")
    parser.add_argument(
        "--policy",
        type=Path,
        default=None,
        help="override the shipped rotation policy (tests only)",
    )
    args = parser.parse_args(argv)

    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        sys.stderr.write(f"unparseable hook JSON on stdin: {exc}\n")
        return 1
    if not isinstance(payload, dict):
        sys.stderr.write("hook JSON on stdin is not an object\n")
        return 1

    if payload.get("tool_name") != "Bash":
        return 0

    try:
        policy = load_policy(args.policy)
    except PolicyError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1

    home_raw = os.environ.get("OMNI_HOME")
    if not home_raw:
        # Resolved fail-fast rather than defaulted (omni_home CLAUDE.md rule 8).
        # A silent default here would resolve every citation against the wrong
        # tree, which is a gate that reads a file nobody wrote.
        sys.stderr.write(
            "OMNI_HOME is not set, so a consent citation cannot be resolved\n"
        )
        omni_home = Path("/nonexistent-omni-home")
    else:
        omni_home = Path(home_raw)

    tool_input = payload.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None

    decision = evaluate_bash_command(command, policy, omni_home)
    if decision.findings:
        return _block(render_block_reason(decision.findings, policy))
    if decision.notes:
        # The allow path speaks only when something was left out of the
        # decision. The wrapper captures this stream and writes it to the hook
        # log; it never reaches the transcript.
        json.dump({"decision": "allow", "notes": decision.notes}, sys.stdout)
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
