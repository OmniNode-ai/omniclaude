#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Fail-closed credential-rotation admission gate (OMN-17957).

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

resolving to an ``OPERATOR-CONSENT`` row -- rule 18 of ``omni_home/CLAUDE.md``
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
honest limit ``omni_home`` CLAUDE.md records for the staging-namespace gate:
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
    "Finding",
    "Policy",
    "PolicyError",
    "RotationShape",
    "check_bash_command",
    "load_policy",
    "render_block_reason",
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
    "ROTATION-CONSENT: docs/tracking/ROLLING_WORK_LEDGER.md:<line>"
)

#: The citation, read from the raw command text.
_CITATION: Final[re.Pattern[str]] = re.compile(
    r"ROTATION-CONSENT:\s*(?P<path>[^\s:'\"]+):(?P<line>\d+)"
)

#: Shell separators that end one segment and begin another. Matched outside
#: quotes only, which ``shlex`` handles for us by tokenising the whole command
#: once and splitting the TOKEN stream rather than the text.
_SEPARATORS: Final[frozenset[str]] = frozenset({";", "&&", "||", "|", "&", "\n"})

#: Wrapper programs that prefix a real command. Stripped before the program of a
#: segment is read, so `sudo aws secretsmanager rotate-secret` is still an aws
#: rotation.
_WRAPPERS: Final[frozenset[str]] = frozenset(
    {"sudo", "env", "command", "time", "nohup", "nice", "xargs", "doas"}
)

_ASSIGNMENT: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

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

    line_no = int(match.group("line"))
    if line_no < 1 or line_no > len(rows):
        return _ConsentVerdict(
            code="consent_line_absent",
            reason=(
                f"the citation names line {line_no} of {cited}, which has "
                f"{len(rows)} lines"
            ),
            fix="cite the line number the consent row actually occupies",
            scope="",
        )

    row = rows[line_no - 1]
    fields = [field.strip() for field in row.split("|")]
    if _REQUIRED_ROW_KIND not in fields:
        return _ConsentVerdict(
            code="consent_row_not_operator_consent",
            reason=(
                f"{cited}:{line_no} is not an {_REQUIRED_ROW_KIND} row -- its "
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
                f"{cited}:{line_no} does not carry both a non-empty "
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
                f"{cited}:{line_no} carries approved_by={approver or '(absent)'}, "
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


def check_bash_command(command: Any, policy: Policy, omni_home: Path) -> list[Finding]:
    """Return every failing rule for one Bash command.

    An empty list admits the command. A command matching no rotation shape --
    every read, and every unrelated command -- returns an empty list without
    ever touching the ledger.
    """
    if not isinstance(command, str) or not command.strip():
        return [
            Finding(
                code="unevaluable",
                shape_id="",
                credential="",
                reason=(
                    f"the Bash call carries no command string (got "
                    f"{type(command).__name__}), so a rotation cannot be ruled out"
                ),
                fix="re-issue the call with the command as a string",
            )
        ]

    try:
        segments = _segments(command)
    except _Untokenisable as exc:
        return [
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
                    "unverifiable rotation is refused, never assumed clean"
                ),
            )
        ]

    hits: list[tuple[RotationShape, str]] = []
    for segment in segments:
        program, tokens = _program_of(segment)
        if not program:
            continue
        for shape in policy.rotation_shapes:
            if _matches(shape, program, tokens):
                hits.append((shape, _credential_of(shape, tokens)))
                break

    if not hits:
        return []

    consent = _read_consent_row(command, policy, omni_home)
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
        return findings

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
        return findings

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

    return findings


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

    findings = check_bash_command(command, policy, omni_home)
    if findings:
        return _block(render_block_reason(findings, policy))
    return 0


if __name__ == "__main__":
    sys.exit(main())
