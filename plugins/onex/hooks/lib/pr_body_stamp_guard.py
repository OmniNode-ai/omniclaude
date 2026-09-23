# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""PreToolUse admission gate: a pull-request body edit may not drop the stamp.

OMN-18335, step 9 of the mechanical ticket-closeout plan of record.

What it refuses
---------------
A Bash command that REPLACES a pull request's description -- ``gh pr edit
--body`` / ``--body-file``, or a REST ``PATCH`` of ``.../pulls/<n>`` carrying a
``body`` field -- when the replacement text omits a change-control
evidence-source line that the live description currently carries. The refusal
prints the exact line that would have been lost, so the remedy is one paste.

Why a hook and not a validator
------------------------------
The plan's section 2 correction 1 measured it: a pull-request description is a
surface a lane overwrites wholesale, with no compare-and-swap, and it silently
lost the evidence-source line on four of the last five misses -- twice after the
pull request had already merged. One lost line makes every downstream reader
conclude no evidence exists.

The sibling ticket (OMN-18334) repairs that loss after the fact, by re-asserting
the line when a description edit drops it. This gate refuses it at the source,
which is cheaper than a re-assert round trip and is the only half that works
where no workflow run follows the edit at all. Either one alone reduces the
loss; they are deliberately independent.

The edit is a command typed in a session, so no pre-commit hook and no repo CI
job ever sees it -- by the time CI reads the body, the line is already gone.
The tool seam is the only place the loss is observable BEFORE it happens. That
is the same argument, and the same primitive, as
``pre_tool_use_credential_rotation_guard.py`` (OMN-17957),
``pre_tool_use_agent_model_guard.sh`` (OMN-17499) and
``pre_tool_use_ticket_creation_gate.sh`` (OMN-17942): it REFUSES the tool call.

One vocabulary, not a second spelling
-------------------------------------
The stamp pattern is config (``pr_body_stamp_policy.json``) and is pinned
byte-for-byte against ``scripts/ci/check_occ_companion_merged.EVIDENCE_SOURCE_RE``
-- the omniclaude-side authority the OCC companion gate already reads a product
pull-request body with, and the same shape onex_change_control's ``occ-preflight``
and receipt-gate callers grep for. A gate that owned its own regex would drift
from the producers and start refusing edits that lose nothing.

Non-canonical regions are stripped from BOTH bodies first: a stamp quoted inside
a fenced block or a blockquote is documentation, never a declaration (OMN-15615
AC6 / OMN-14682). Protecting a quoted example would refuse every meta pull
request about this gate, and a guard whose false refusals outnumber its true
ones gets routed around -- the plan's constraint 5.

Fail-open / fail-closed boundary, stated deliberately
-----------------------------------------------------
  * A command naming no body-replacing flag never invokes Python at all. The
    wrapper's grep is a cheap OVER-matcher that decides nothing.
  * A command that DOES carry the shape and cannot then be evaluated --
    unparseable hook JSON, an untokenisable command, an unreadable replacement
    body, or a live read that FAILED -- is BLOCKED. A live read that failed is
    evidence of nothing, and must never be converted into evidence that there
    was no stamp (the workspace CLAUDE.md rule 16).
  * Reads are never gated, and they are not allowlisted either: every shape
    names only body-REPLACING flags, so ``gh pr view --json body``, ``gh pr
    list``, a bare ``gh api`` read, ``gh pr comment --body`` and ``gh pr edit
    --add-label`` match nothing.

What this cannot do, stated rather than implied
-----------------------------------------------
It sees one seam: a Bash command in this session. An edit made in the web
interface, by another session, or by a workflow is invisible to it -- that half
is OMN-18334's re-assert, and neither ticket claims the other's coverage. What
this removes is the *silent* local case: a replacement body composed in a
session and sent without the line the live body carries.

Gating: the ``BRANCH_PROTECTION_GUARD`` bit. A dedicated bit is unavailable --
``EnumHookBit`` lives in omnibase_core, all 60 default-mask ordinals are
allocated (60-62 are the disabled-by-default trio, and knowledge-base-internal
``reference/hook-bitmask-bit-governance.md`` rule 7 forbids ordinal 63
outright), so minting one is a cross-repo release chain plus an architecture
review. Same constraint and same resolution
``pre_tool_use_credential_rotation_guard.sh`` recorded for
PRE_TOOL_AUTHORIZATION_SHIM and ``pre_tool_use_pr_ownership_guard.sh`` recorded
for BASH_GUARD.

BRANCH_PROTECTION_GUARD is the faithful borrow and not an arbitrary one: its
namesake ``pre_tool_use_branch_protection_guard.sh`` is a PreToolUse Bash-matcher
guard over GitHub-mutating commands, it is on disk and UNREGISTERED under the
OMN-13244 baseline, and no other registered script gates on it -- so ``onex
hooks disable BRANCH_PROTECTION_GUARD`` disables exactly this guard and nothing
else that is live. ``tests/hooks/test_pr_body_stamp_guard.py`` pins the borrow:
re-registering the namesake turns the suite red rather than quietly sharing the
switch. A disabled run is LOGGED, not silent.

Standard library only. The hook resolves whatever interpreter it can find, so
this module may never import from the project venv.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from collections import ChainMap
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

_HOOKS_LIB = Path(__file__).parent
if str(_HOOKS_LIB) not in sys.path:
    sys.path.insert(0, str(_HOOKS_LIB))

from shell_words import (  # noqa: E402
    UnresolvableWord,
    expand_word,
    shadow,
    shadowed_names,
    unquoted,
)

#: Variables visible when a body-file path is expanded: this hook's
#: environment, overlaid with plain assignments made earlier in the command.
Scope = Mapping[str, "str | None"]

__all__ = [
    "GATE_BIT_NAME",
    "Finding",
    "Policy",
    "PolicyError",
    "PrBodyEdit",
    "check_bash_command",
    "load_policy",
    "main",
    "parse_pr_body_edits",
    "render_block_reason",
    "stamp_lines",
    "strip_noncanonical_regions",
]

#: The hook-activation bit this guard is gated on. Borrowed; see the module
#: docstring for why, and for the test that keeps the borrow exclusive.
GATE_BIT_NAME = "BRANCH_PROTECTION_GUARD"

_DEFAULT_POLICY = (
    Path(__file__).resolve().parents[1] / "config" / ("pr_body_stamp_policy.json")
)

#: Shell segment separators. A body-replacing edit in ANY segment is judged --
#: `git status && gh pr edit ...` is still an edit.
_SEPARATORS = frozenset({";", "&&", "||", "|", "&", "\n"})

#: Wrapper programs stripped before the program is read, so `env -u X gh ...`
#: and `sudo gh ...` cannot hide the shape.
_WRAPPERS = frozenset({"env", "sudo", "command", "nohup", "time", "timeout", "xargs"})

_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

#: Mirror of ``check_occ_companion_merged.FENCE_LINE_RE``, itself a mirror of
#: ``validator_receipt_gate`` (OMN-14682). Copied rather than imported because
#: this module must run under any resolved interpreter with no project path.
_FENCE_LINE_RE = re.compile(r"^\s*(`{3,}|~{3,})")

_FLAG_NAMES = {
    "IGNORECASE": re.IGNORECASE,
    "MULTILINE": re.MULTILINE,
    "DOTALL": re.DOTALL,
    "VERBOSE": re.VERBOSE,
}


class PolicyError(RuntimeError):
    """The shipped policy is missing, unreadable or malformed."""


class _Untokenisable(RuntimeError):
    """The command carries the edit vocabulary and cannot be tokenised."""


@dataclass(frozen=True)
class _GhPrEditShape:
    programs: frozenset[str]
    subcommand: tuple[str, ...]
    body_flags: frozenset[str]
    body_file_flags: frozenset[str]
    repo_flags: frozenset[str]


@dataclass(frozen=True)
class _GhApiPatchShape:
    programs: frozenset[str]
    subcommand: tuple[str, ...]
    method_flags: frozenset[str]
    methods: frozenset[str]
    pull_path: re.Pattern[str]
    field_flags: frozenset[str]
    body_field: str
    input_flags: frozenset[str]


@dataclass(frozen=True)
class Policy:
    """The stamp vocabulary and the two body-replacing command shapes."""

    stamp_line: re.Pattern[str]
    gh_pr_edit: _GhPrEditShape
    gh_api_patch: _GhApiPatchShape
    source: Path


@dataclass(frozen=True)
class PrBodyEdit:
    """One body-replacing edit found in a command."""

    #: What identifies the pull request to the platform: a number, a URL, a
    #: branch name, or ``None`` when ``gh`` would resolve it from the checkout.
    selector: str | None
    repo: str | None
    #: The replacement text, or ``None`` when it could not be read.
    new_body: str | None
    #: Why ``new_body`` is ``None``, for the refusal text.
    unreadable_reason: str | None
    #: Human-readable origin of the replacement, for the refusal text.
    origin: str


@dataclass(frozen=True)
class Finding:
    kind: str
    detail: str
    dropped_lines: tuple[str, ...] = ()
    edit: PrBodyEdit | None = None


# ---------------------------------------------------------------------------
# Policy loading
# ---------------------------------------------------------------------------


def _require(raw: object, key: str, source: Path) -> object:
    if not isinstance(raw, dict) or key not in raw:
        raise PolicyError(f"{source}: missing required key {key!r}")
    return raw[key]


def _str_frozenset(raw: object, key: str, source: Path) -> frozenset[str]:
    value = _require(raw, key, source)
    if not isinstance(value, list) or not value:
        raise PolicyError(f"{source}: {key!r} must be a non-empty list of strings")
    out: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item:
            raise PolicyError(f"{source}: {key!r} must contain non-empty strings")
        out.append(item)
    return frozenset(out)


def load_policy(path: Path | None = None) -> Policy:
    """Read the shipped policy, or raise.

    Never defaults: a guard that silently fell back to a built-in vocabulary
    would enforce a rule nobody can read out of the repository.
    """
    source = path or _DEFAULT_POLICY
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PolicyError(f"{source}: policy file is missing") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise PolicyError(
            f"{source}: policy is unreadable or malformed: {exc}"
        ) from exc
    if not isinstance(raw, dict):
        raise PolicyError(f"{source}: policy is not an object")

    pattern = _require(raw, "stamp_line_pattern", source)
    if not isinstance(pattern, str) or not pattern:
        raise PolicyError(f"{source}: 'stamp_line_pattern' must be a non-empty string")
    flags = 0
    flag_names = raw.get("stamp_line_flags", [])
    if not isinstance(flag_names, list):
        raise PolicyError(f"{source}: 'stamp_line_flags' must be a list")
    for name in flag_names:
        if name not in _FLAG_NAMES:
            raise PolicyError(f"{source}: unknown regex flag {name!r}")
        flags |= _FLAG_NAMES[name]
    try:
        stamp_line = re.compile(pattern, flags)
    except re.error as exc:
        raise PolicyError(
            f"{source}: 'stamp_line_pattern' does not compile: {exc}"
        ) from exc

    edit_raw = _require(raw, "gh_pr_edit", source)
    subcommand = _require(edit_raw, "subcommand", source)
    if not isinstance(subcommand, list) or not all(
        isinstance(t, str) for t in subcommand
    ):
        raise PolicyError(
            f"{source}: 'gh_pr_edit.subcommand' must be a list of strings"
        )
    gh_pr_edit = _GhPrEditShape(
        programs=_str_frozenset(edit_raw, "programs", source),
        subcommand=tuple(subcommand),
        body_flags=_str_frozenset(edit_raw, "body_flags", source),
        body_file_flags=_str_frozenset(edit_raw, "body_file_flags", source),
        repo_flags=_str_frozenset(edit_raw, "repo_flags", source),
    )

    api_raw = _require(raw, "gh_api_patch", source)
    api_subcommand = _require(api_raw, "subcommand", source)
    if not isinstance(api_subcommand, list) or not all(
        isinstance(t, str) for t in api_subcommand
    ):
        raise PolicyError(
            f"{source}: 'gh_api_patch.subcommand' must be a list of strings"
        )
    pull_path_raw = _require(api_raw, "pull_path_pattern", source)
    if not isinstance(pull_path_raw, str):
        raise PolicyError(
            f"{source}: 'gh_api_patch.pull_path_pattern' must be a string"
        )
    body_field = _require(api_raw, "body_field", source)
    if not isinstance(body_field, str) or not body_field:
        raise PolicyError(f"{source}: 'gh_api_patch.body_field' must be a string")
    try:
        pull_path = re.compile(pull_path_raw)
    except re.error as exc:
        raise PolicyError(
            f"{source}: 'pull_path_pattern' does not compile: {exc}"
        ) from exc
    gh_api_patch = _GhApiPatchShape(
        programs=_str_frozenset(api_raw, "programs", source),
        subcommand=tuple(api_subcommand),
        method_flags=_str_frozenset(api_raw, "method_flags", source),
        methods=frozenset(
            m.upper() for m in _str_frozenset(api_raw, "methods", source)
        ),
        pull_path=pull_path,
        field_flags=_str_frozenset(api_raw, "field_flags", source),
        body_field=body_field,
        input_flags=_str_frozenset(api_raw, "input_flags", source),
    )

    return Policy(
        stamp_line=stamp_line,
        gh_pr_edit=gh_pr_edit,
        gh_api_patch=gh_api_patch,
        source=source,
    )


# ---------------------------------------------------------------------------
# Stamp extraction
# ---------------------------------------------------------------------------


def strip_noncanonical_regions(pr_body: str) -> str:
    """Blank out body regions that cannot carry a *canonical* stamp.

    Mirror of ``check_occ_companion_merged.strip_noncanonical_regions``, itself
    a mirror of ``validator_receipt_gate.strip_noncanonical_regions``
    (OMN-14682). Excluded lines become empty lines rather than disappearing, so
    line positions survive and the MULTILINE anchors behave identically for
    every surviving canonical line. An unterminated opening fence blanks
    everything to end-of-body.

    Idempotent: re-stripping an already-stripped body is a no-op.
    """
    out: list[str] = []
    in_fence = False
    fence_marker = ""
    for line in pr_body.splitlines():
        fence = _FENCE_LINE_RE.match(line)
        if fence is not None:
            marker = fence.group(1)
            marker_char = marker[0]
            if not in_fence:
                in_fence = True
                fence_marker = marker
            elif marker_char == fence_marker[0] and len(marker) >= len(fence_marker):
                in_fence = False
                fence_marker = ""
            out.append("")
            continue
        if in_fence:
            out.append("")
            continue
        if line.lstrip().startswith(">"):
            out.append("")
            continue
        out.append(line)
    return "\n".join(out)


def stamp_lines(body: str, policy: Policy) -> list[str]:
    """Every canonical stamp line in ``body``, verbatim and in order.

    Returned verbatim because the refusal has to print what would have been
    lost, and a normalised rendering is not a paste.
    """
    stripped = strip_noncanonical_regions(body)
    return [
        match.group(0).rstrip("\r") for match in policy.stamp_line.finditer(stripped)
    ]


# ---------------------------------------------------------------------------
# Command parsing
# ---------------------------------------------------------------------------


def _segments(command: str) -> list[list[str]]:
    """Split ``command`` into shell segments, as token lists.

    ``shlex`` in POSIX mode resolves quoting for us, so a separator inside a
    quoted string is a token of that string rather than a segment boundary, and
    a quoted ``gh`` never becomes the program of a segment.
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
    """Return the program basename and the remaining tokens."""
    index = 0
    while index < len(segment):
        token = segment[index]
        if _ASSIGNMENT.match(token):
            index += 1
            continue
        basename = os.path.basename(token)
        if basename in _WRAPPERS:
            index += 1
            while index < len(segment) and (
                segment[index].startswith("-") or _ASSIGNMENT.match(segment[index])
            ):
                if segment[index] in {"-u", "-C", "-S"} and index + 1 < len(segment):
                    index += 1
                index += 1
            continue
        return basename, segment[index + 1 :]
    return "", []


#: ``--body "$(cat path)"`` and its backtick spelling. A lane composing a body
#: in a file and handing it to ``--body`` through a substitution is the most
#: common real spelling of this command, and the shell has not expanded it by
#: the time the guard sees it. Reading the named file is what keeps the guard
#: from refusing a legitimate edit it simply could not see -- the plan's
#: constraint 5, a guard whose false refusals outnumber its true ones is one
#: that gets routed around.
_CAT_SUBSTITUTION = re.compile(
    r"""^(?:\$\((?:\s*cat\s+)|`(?:\s*cat\s+))(?P<path>[^)`]+?)\s*(?:\)|`)$"""
)

#: Any OTHER unexpanded shell construct in the replacement body. The guard
#: cannot resolve it, so it does not know what the new body says -- and must
#: not report that as a dropped line, which would be a specific accusation it
#: has no evidence for.
_UNEXPANDED = re.compile(r"\$\(|`|\$\{|\$[A-Za-z_]")


def _read_body_file(raw: str, scope: Scope) -> tuple[str | None, str | None]:
    """Return ``(text, unreadable_reason)`` for a ``--body-file`` argument.

    The path is expanded the way the shell would (``~``, ``$NAME``,
    ``${NAME}``) by the shared OMN-19229 helper, so ``--body-file "$B"`` reads
    the file the shell hands ``gh`` instead of a file literally named ``$B``.
    """
    if raw == "-":
        return None, (
            "the replacement body is read from standard input, which this "
            "guard structurally cannot see"
        )
    try:
        path = expand_word(unquoted(raw), scope)
    except UnresolvableWord as exc:
        return None, f"the replacement body file {raw} cannot be resolved: {exc}"
    try:
        return Path(path).read_text(encoding="utf-8"), None
    except (OSError, UnicodeDecodeError) as exc:
        return None, f"the replacement body file {raw} could not be read: {exc}"


def _resolve_body_argument(raw: str, scope: Scope) -> tuple[str | None, str | None]:
    """Resolve a ``--body`` argument the shell has not expanded yet.

    Three outcomes, and the middle one is the reason this exists:

    * plain text -> itself;
    * ``$(cat path)`` / ``` `cat path` ``` -> the file's contents, because that
      is how a lane that composed the body in a file actually spells this
      command, and refusing it would be a false accusation against the most
      common legitimate shape; and
    * any other unexpanded construct -> UNREADABLE, not "dropped". The guard
      cannot see what the body says, and reporting a dropped line it has no
      evidence for would send the author hunting for a line they did not
      remove.
    """
    match = _CAT_SUBSTITUTION.match(raw.strip())
    if match is not None:
        return _read_body_file(match.group("path").strip().strip("'\""), scope)
    if _UNEXPANDED.search(raw):
        return None, (
            "the replacement body is an unexpanded shell substitution "
            f"({raw[:80]!r}), so its text cannot be read here. Pass the body "
            "with --body-file <path> instead, which this guard can read"
        )
    return raw, None


def _parse_gh_pr_edit(
    tokens: list[str], shape: _GhPrEditShape, scope: Scope
) -> PrBodyEdit | None:
    if list(tokens[: len(shape.subcommand)]) != list(shape.subcommand):
        return None
    rest = tokens[len(shape.subcommand) :]

    selector: str | None = None
    repo: str | None = None
    new_body: str | None = None
    unreadable: str | None = None
    origin = ""
    found_body = False

    index = 0
    while index < len(rest):
        token = rest[index]
        flag, _, inline = token.partition("=")
        has_inline = "=" in token
        if flag in shape.body_flags:
            found_body = True
            origin = "--body"
            raw_value: str | None
            if has_inline:
                raw_value = inline
            elif index + 1 < len(rest):
                index += 1
                raw_value = rest[index]
            else:
                raw_value = None
            if raw_value is None:
                unreadable = "the body flag was given no value"
            else:
                new_body, unreadable = _resolve_body_argument(raw_value, scope)
            index += 1
            continue
        if flag in shape.body_file_flags:
            found_body = True
            origin = "--body-file"
            raw: str | None
            if has_inline:
                raw = inline
            elif index + 1 < len(rest):
                index += 1
                raw = rest[index]
            else:
                raw = None
            if raw is None:
                unreadable = "the body-file flag was given no value"
            else:
                new_body, unreadable = _read_body_file(raw, scope)
            index += 1
            continue
        if flag in shape.repo_flags:
            if has_inline:
                repo = inline
            elif index + 1 < len(rest):
                index += 1
                repo = rest[index]
            index += 1
            continue
        if token.startswith("-"):
            # An unknown flag may or may not take a value. Skipping only the
            # flag is safe: a value that looks like a positional is not used as
            # a selector unless nothing better was found, and the live read
            # simply fails, which is a refusal rather than a wrong verdict.
            index += 1
            continue
        if selector is None:
            selector = token
        index += 1

    if not found_body:
        return None
    return PrBodyEdit(
        selector=selector,
        repo=repo,
        new_body=new_body,
        unreadable_reason=unreadable,
        origin=origin,
    )


def _parse_gh_api_patch(
    tokens: list[str], shape: _GhApiPatchShape, scope: Scope
) -> PrBodyEdit | None:
    if list(tokens[: len(shape.subcommand)]) != list(shape.subcommand):
        return None
    rest = tokens[len(shape.subcommand) :]

    method = "GET"
    endpoint: str | None = None
    new_body: str | None = None
    unreadable: str | None = None
    found_body = False
    origin = ""

    index = 0
    while index < len(rest):
        token = rest[index]
        flag, _, inline = token.partition("=")
        has_inline = "=" in token
        if token in shape.method_flags and index + 1 < len(rest):
            index += 1
            method = rest[index].upper()
            index += 1
            continue
        if flag in shape.method_flags and has_inline:
            method = inline.upper()
            index += 1
            continue
        if token in shape.field_flags and index + 1 < len(rest):
            index += 1
            field, sep, value = rest[index].partition("=")
            if sep and field == shape.body_field:
                found_body = True
                origin = token
                if value.startswith("@"):
                    new_body, unreadable = _read_body_file(value[1:], scope)
                else:
                    new_body = value
            index += 1
            continue
        if token in shape.input_flags and index + 1 < len(rest):
            index += 1
            found_body = True
            origin = token
            raw = rest[index]
            text, unreadable = _read_body_file(raw, scope)
            if text is None:
                new_body = None
            else:
                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError as exc:
                    unreadable = f"the --input payload is not readable JSON: {exc}"
                else:
                    if isinstance(parsed, dict) and shape.body_field in parsed:
                        candidate = parsed[shape.body_field]
                        if isinstance(candidate, str):
                            new_body = candidate
                        else:
                            unreadable = "the --input payload's body is not a string"
                    else:
                        # No body field at all: this PATCH replaces something
                        # else, so it is not a body-replacing edit.
                        found_body = False
                        unreadable = None
            index += 1
            continue
        if token.startswith("-"):
            index += 1
            continue
        if endpoint is None:
            endpoint = token
        index += 1

    if method not in shape.methods or not found_body:
        return None
    if endpoint is None:
        return PrBodyEdit(
            selector=None,
            repo=None,
            new_body=new_body,
            unreadable_reason=unreadable or "the REST endpoint could not be read",
            origin=origin,
        )
    match = shape.pull_path.match(endpoint)
    if match is None:
        return None
    owner, repo_name, number = match.group(1), match.group(2), match.group(3)
    return PrBodyEdit(
        selector=number,
        repo=f"{owner}/{repo_name}",
        new_body=new_body,
        unreadable_reason=unreadable,
        origin=origin,
    )


def parse_pr_body_edits(command: str, policy: Policy) -> list[PrBodyEdit]:
    """Every body-replacing pull-request edit in ``command``."""
    edits: list[PrBodyEdit] = []
    segments = _segments(command)
    # A name the command sets any other way (`export`, `read`, `for`) is
    # unresolvable: the environment only holds its value from before.
    assigned: dict[str, str | None] = {}
    scope: Scope = ChainMap(assigned, shadow(os.environ, shadowed_names(segments)))  # type: ignore[arg-type]
    for segment in segments:
        if all(_ASSIGNMENT.match(token) for token in segment):
            # `B=/tmp/body.md; gh pr edit --body-file "$B"`: the assignment
            # is what the later expansion reads.
            for token in segment:
                name, _, value = token.partition("=")
                try:
                    assigned[name] = expand_word(unquoted(value), scope)
                except UnresolvableWord:
                    assigned[name] = None
            continue
        program, tokens = _program_of(segment)
        if program in policy.gh_pr_edit.programs:
            edit = _parse_gh_pr_edit(tokens, policy.gh_pr_edit, scope)
            if edit is not None:
                edits.append(edit)
                continue
        if program in policy.gh_api_patch.programs:
            edit = _parse_gh_api_patch(tokens, policy.gh_api_patch, scope)
            if edit is not None:
                edits.append(edit)
    return edits


# ---------------------------------------------------------------------------
# Live body reads
# ---------------------------------------------------------------------------


LiveBodyReader = Callable[[PrBodyEdit], "str | None"]


def gh_live_body_reader(cwd: str | None = None, timeout: int = 45) -> LiveBodyReader:
    """A reader that asks the platform for the description, read-only.

    ``gh pr view --json body`` is a read and is itself outside every shape this
    guard matches, so the guard can never recurse into itself. ``cwd`` is the
    session's own directory so that a selector-less ``gh pr edit`` -- which gh
    resolves from the checkout's branch -- resolves the same way here.
    """

    def _read(edit: PrBodyEdit) -> str | None:
        argv = ["gh", "pr", "view"]
        if edit.selector:
            argv.append(edit.selector)
        if edit.repo:
            argv += ["--repo", edit.repo]
        argv += ["--json", "body", "--jq", ".body"]
        try:
            result = subprocess.run(  # fixed argv, no shell
                argv,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
                cwd=cwd if cwd and Path(cwd).is_dir() else None,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if result.returncode != 0:
            return None
        return result.stdout

    return _read


# ---------------------------------------------------------------------------
# The decision
# ---------------------------------------------------------------------------


def check_bash_command(
    command: object, policy: Policy, live_body: LiveBodyReader
) -> list[Finding]:
    """Findings for one Bash command. Empty means admit."""
    if command is None or not isinstance(command, str):
        return [
            Finding(
                kind="non_string_command",
                detail=(
                    "the Bash payload names a body-replacing pull-request edit "
                    "but carries no readable command string"
                ),
            )
        ]

    try:
        edits = parse_pr_body_edits(command, policy)
    except _Untokenisable as exc:
        return [
            Finding(
                kind="untokenisable",
                detail=(
                    "this command names a body-replacing pull-request edit and "
                    f"cannot be tokenised ({exc}), so whether it drops a "
                    "change-control evidence line cannot be decided"
                ),
            )
        ]

    findings: list[Finding] = []
    for edit in edits:
        if edit.new_body is None:
            findings.append(
                Finding(
                    kind="unreadable_new_body",
                    detail=edit.unreadable_reason
                    or "the replacement body could not be read",
                    edit=edit,
                )
            )
            continue
        live = live_body(edit)
        if live is None:
            findings.append(
                Finding(
                    kind="unreadable_live_body",
                    detail=(
                        "the live description could not be read, so whether "
                        "this edit drops a change-control evidence line is "
                        "unknown. A read that failed is evidence of nothing"
                    ),
                    edit=edit,
                )
            )
            continue
        present = stamp_lines(live, policy)
        if not present:
            continue
        kept = set(stamp_lines(edit.new_body, policy))
        dropped = tuple(line for line in present if line not in kept)
        if dropped:
            findings.append(
                Finding(
                    kind="dropped_stamp",
                    detail=(
                        "this edit replaces the description with text that "
                        "omits a change-control evidence line the live "
                        "description carries"
                    ),
                    dropped_lines=dropped,
                    edit=edit,
                )
            )
    return findings


def _target_of(edit: PrBodyEdit | None) -> str:
    if edit is None:
        return "the pull request"
    if edit.repo and edit.selector:
        return f"{edit.repo}#{edit.selector}"
    if edit.selector:
        return str(edit.selector)
    return "the pull request resolved from the current branch"


def render_block_reason(findings: list[Finding]) -> str:
    """The refusal text. The dropped line appears verbatim, so the fix is one paste."""
    parts: list[str] = []
    for finding in findings:
        target = _target_of(finding.edit)
        if finding.kind == "dropped_stamp":
            lines = "\n".join(finding.dropped_lines)
            parts.append(
                f"BLOCKED: this edit to {target} would DROP a change-control "
                "evidence line that its description currently carries "
                "(OMN-18335). One lost line makes every downstream reader "
                "conclude no evidence exists, and on a merged pull request "
                "nothing re-asserts it.\n\n"
                "Put these lines back into the replacement body, verbatim, "
                "each on a line of its own:\n\n"
                f"{lines}\n\n"
                "Then re-run the edit. Nothing else about the command needs to "
                "change."
            )
            continue
        parts.append(
            f"BLOCKED: {finding.detail} ({target}). A body-replacing "
            "pull-request edit whose effect on the change-control evidence "
            "line cannot be verified is refused, never assumed harmless "
            "(OMN-18335)."
        )
    parts.append(
        f"To disable this guard deliberately: onex hooks disable {GATE_BIT_NAME}"
    )
    return "\n\n".join(parts)


def _block(reason: str) -> int:
    json.dump({"decision": "block", "reason": reason}, sys.stdout)
    sys.stdout.write("\n")
    return 3


def main(argv: list[str] | None = None) -> int:
    """Hook entry point. Reads the PreToolUse JSON on stdin.

    Exit codes: ``0`` allow, ``3`` block (payload on stdout), ``1`` the guard
    itself could not decide. The shell wrapper treats ``1`` as a block too -- a
    command carrying the edit vocabulary that cannot be evaluated is refused,
    never assumed harmless.
    """
    parser = argparse.ArgumentParser(
        description="pull-request body stamp-preservation admission gate"
    )
    parser.add_argument(
        "--policy",
        type=Path,
        default=None,
        help="override the shipped policy (tests only)",
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

    tool_input = payload.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None

    cwd = payload.get("cwd")
    reader = gh_live_body_reader(cwd if isinstance(cwd, str) else None)

    findings = check_bash_command(command, policy, reader)
    if findings:
        return _block(render_block_reason(findings))
    return 0


if __name__ == "__main__":
    sys.exit(main())
