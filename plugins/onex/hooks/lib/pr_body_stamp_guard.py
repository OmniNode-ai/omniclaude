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
  * OMN-19542: "cannot be evaluated" now means it. The command is split by the
    shared shell tokenizer, so a here-document body is data rather than
    shell, and a body file the same command writes is judged on the text the
    command writes, never on the file the disk held when the hook ran. A body
    that is only known once the command has run -- a file rewritten by an
    interpreter, a script or ``sed -i``, an expanding here-document with a
    command substitution, a write to a path that cannot be resolved -- is
    refused with the workaround named: prepare the file in one Bash call, run
    the edit in the next. A command that cannot be split into words at all is
    refused only when its text names ``gh`` then ``pr edit`` or ``api``; text
    without them cannot hold an edit this parser would recognise.
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
import subprocess
import sys
from collections import ChainMap
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

_HOOKS_LIB = Path(__file__).parent
if str(_HOOKS_LIB) not in sys.path:
    sys.path.insert(0, str(_HOOKS_LIB))

from shell_words import (  # noqa: E402
    HereDoc,
    Operator,
    QuoteKind,
    Redirect,
    ShellSyntaxError,
    UnresolvableWord,
    Word,
    WordPart,
    _scan_backtick,
    _scan_balanced,
    expand_word,
    shadow,
    shadowed_names,
    tokenize,
)

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
# Command parsing (OMN-19542)
# ---------------------------------------------------------------------------
#
# The command is split by the shared shell tokenizer (``shell_words``), which
# knows what ``shlex`` does not: a here-document body is data, not shell. That
# alone retires the class that produced 15 of this guard's 22 logged refusals
# (the rolling work ledger, row 3319): an apostrophe in a quoted here-document body made
# the whole command "untokenisable", so a command that only CREATED a pull
# request was refused as an unverifiable edit.
#
# The command is then walked in order, keeping a small model of the files it
# writes. A body file is judged on the text the command itself puts there when
# that text is determined by the command (a here-document, printf, echo, cat,
# tee, cp, or the live body fetched with a read), and never on whatever the
# disk held when the hook ran. Anything else that may have written the file --
# an interpreter, a script, sed -i, a write to a path that cannot be resolved,
# a program that names the file -- makes the body UNKNOWN, and an unknown body
# is refused with the workaround named: run the step that prepares the file as
# its own Bash call first. Nothing is ever executed to find out.


class _Unknown(Exception):
    """The text a construct produces cannot be determined before it runs."""


#: Programs that run code which can write any file, whatever their arguments
#: say. One of these earlier in the command makes every body file unknown.
_INTERPRETERS = re.compile(
    r"^(?:python[0-9.]*|pypy[0-9.]*|node|nodejs|deno|bun|ruby|perl|php|"
    r"bash|sh|zsh|dash|ksh|fish|uv|uvx|npx|npm|pnpm|yarn|make|osascript|"
    r"eval|source|\.|exec)$"
)

#: Programs that write no file other than through a redirection, which the
#: model handles itself. Naming a body file as an argument of one of these is a
#: read. Every other program that names the file may have rewritten it.
_NO_FILE_WRITES = frozenset(
    {
        "cat", "grep", "egrep", "fgrep", "rg", "head", "tail", "wc", "diff",
        "cmp", "ls", "stat", "file", "test", "[", "[[", "echo", "printf",
        "true", "false", ":", "sleep", "date", "pwd", "cd", "which", "type",
        "jq", "sort", "uniq", "cut", "tr", "basename", "dirname", "realpath",
        "readlink", "git", "gh", "export", "unset", "local", "declare",
        "shasum", "md5", "sha256sum", "nl", "column", "fold", "mkdir",
        "wait", "exit", "return", "read", "for", "case", "esac", "done",
        "fi", "}", "tee", "cp",
    }
)  # fmt: skip

#: Words that open a compound command. The program is the word after them.
_KEYWORDS = frozenset({"if", "then", "else", "elif", "do", "while", "until", "!", "{"})

_DEV_FILES = frozenset({"/dev/null", "/dev/stdout", "/dev/stderr", "/dev/tty"})

#: Redirections that write standard output, with and without appending.
_WRITE_OPS = frozenset({">", ">|", ">>", "&>", "&>>", ">&"})

#: ``gh api`` field flags that read ``@file``; ``-f`` sends its value verbatim.
_TYPED_FIELD_FLAGS = frozenset({"-F", "--field"})

#: The one sentence every "cannot be determined" refusal ends with.
_WORKAROUND = (
    "Run the step that prepares the body as its own Bash call first, then run "
    "the edit as its own Bash call with --body-file <path>; the guard then "
    "reads the finished file"
)


@dataclass
class _Cmd:
    words: list[Word]
    heredocs: list[HereDoc]
    redirects: list[Redirect]
    piped_from: _Cmd | None
    in_subshell: bool


@dataclass
class _File:
    text: str | None
    reason: str | None
    written_at: int


@dataclass
class _Taint:
    at: int
    who: str
    #: Text of the command, searched for the body file's path; ``None`` when
    #: the writer can reach any file.
    mentions: str | None


def _commands(command: str) -> list[_Cmd]:
    try:
        tokens = tokenize(command, keep_redirects=True)
    except ShellSyntaxError as exc:
        raise _Untokenisable(str(exc)) from exc
    out: list[_Cmd] = []
    depth = 0
    current = _Cmd([], [], [], None, False)
    piped: _Cmd | None = None

    def close(next_piped: bool) -> None:
        nonlocal current, piped
        if current.words or current.heredocs or current.redirects:
            out.append(current)
            piped = current if next_piped else None
        else:
            piped = None
        current = _Cmd([], [], [], piped, depth > 0)

    for token in tokens:
        if isinstance(token, Operator):
            if token.text == "(":
                close(False)
                depth += 1
                current.in_subshell = True
            elif token.text == ")":
                close(False)
                depth = max(0, depth - 1)
                current.in_subshell = depth > 0
            else:
                close(token.text in ("|", "|&"))
        elif isinstance(token, HereDoc):
            current.heredocs.append(token)
        elif isinstance(token, Redirect):
            current.redirects.append(token)
        else:
            current.words.append(token)
    close(False)
    return out


def _program_of(words: list[Word]) -> tuple[str, list[Word]]:
    """Return the program basename and the words after it."""
    index = 0
    while index < len(words):
        text = words[index].text
        if words[index].assignment() is not None or text in _KEYWORDS:
            index += 1
            continue
        basename = os.path.basename(text)
        if basename in _WRAPPERS:
            index += 1
            while index < len(words) and (
                words[index].text.startswith("-")
                or words[index].assignment() is not None
            ):
                if words[index].text in {"-u", "-C", "-S"} and index + 1 < len(words):
                    index += 1
                index += 1
            continue
        return basename, words[index + 1 :]
    return "", []


def _split_inline(word: Word) -> Word | None:
    """The value of ``--flag=value``, keeping the quoting of every part."""
    for index, part in enumerate(word.parts):
        if part.quote == "none" and "=" in part.text:
            _, _, rest = part.text.partition("=")
            head = (WordPart(rest, "none"),) if rest else ()
            return Word(head + word.parts[index + 1 :])
        if part.quote != "none":
            return None
    return None


class _Model:
    """The files a command writes, followed in order, and how to read them."""

    def __init__(
        self,
        scope: ChainMap[str, str | None],
        cwd: str | None,
        live_body: LiveBodyReader | None,
    ) -> None:
        self.scope = scope
        self.cwd = cwd
        self.live_body = live_body
        self.files: dict[str, _File] = {}
        self.taints: list[_Taint] = []
        self.at = 0

    # -- words ---------------------------------------------------------------

    def expand(self, word: Word) -> str:
        """The value the shell gives ``word``; command substitutions whose
        output the model can compute are substituted. Raises ``_Unknown``."""
        out: list[str] = []
        for index, part in enumerate(word.parts):
            if part.quote == "literal":
                out.append(part.text)
                continue
            out.append(self._expand_text(part.text, part.quote, index == 0))
        return "".join(out)

    def _expand_text(self, text: str, quote: QuoteKind, first: bool) -> str:
        out: list[str] = []
        plain_start = 0
        i = 0
        n = len(text)

        def flush(end: int) -> None:
            chunk = text[plain_start:end]
            if not chunk:
                return
            at_start = first and plain_start == 0
            parts: tuple[WordPart, ...] = (WordPart(chunk, quote),)
            if not at_start:
                parts = (WordPart("", "literal"),) + parts
            try:
                out.append(expand_word(Word(parts), self.scope))
            except UnresolvableWord as exc:
                raise _Unknown(str(exc)) from exc

        while i < n:
            ch = text[i]
            if ch == "\\":
                i += 2
                continue
            if text.startswith("$((", i):
                raise _Unknown("arithmetic expansion is not evaluated by the guard")
            if text.startswith("$(", i) or ch == "`":
                if quote == "none":
                    raise _Unknown(
                        "an unquoted command substitution is split into words by "
                        "the shell"
                    )
                flush(i)
                try:
                    if ch == "`":
                        end = _scan_backtick(text, i)
                        inner = text[i + 1 : end - 1]
                    else:
                        end = _scan_balanced(text, i + 1, "(", ")")
                        inner = text[i + 2 : end - 1]
                except ShellSyntaxError as exc:
                    raise _Unknown(str(exc)) from exc
                out.append(self._substitute(inner))
                i = end
                plain_start = i
                continue
            i += 1
        flush(n)
        return "".join(out)

    def _substitute(self, inner: str) -> str:
        try:
            commands = _commands(inner)
        except _Untokenisable as exc:
            raise _Unknown(f"a command substitution cannot be read ({exc})") from exc
        if len(commands) != 1:
            raise _Unknown(
                "a command substitution runs more than one command, and the guard "
                "computes the output of one"
            )
        # The shell strips trailing newlines here; they are kept, because they
        # cannot change which lines a body carries.
        return self.stdout(commands[0])

    def path(self, word: Word) -> str:
        try:
            raw = expand_word(word, self.scope)
        except UnresolvableWord as exc:
            raise _Unknown(
                f"the path {word.text} cannot be resolved: {exc}. Only a variable "
                "assigned earlier in this same command is expanded here; pass a "
                "literal path, or assign it in the command"
            ) from exc
        if raw in _DEV_FILES or Path(raw).is_absolute():
            return os.path.normpath(raw)
        if self.cwd is None:
            raise _Unknown(
                f"the relative path {raw} follows a directory change the guard "
                "cannot resolve; pass an absolute path"
            )
        return os.path.normpath(os.path.join(self.cwd, raw))

    # -- files ---------------------------------------------------------------

    def read(self, word: Word, what: str = "the replacement body file") -> str:
        path = self.path(word)
        entry = self.files.get(path)
        since = entry.written_at if entry is not None else -1
        for taint in self.taints:
            if taint.at <= since:
                continue
            if (
                taint.mentions is None
                or path in taint.mentions
                or (os.path.basename(path) in taint.mentions)
            ):
                raise _Unknown(
                    f"{what} {word.text} may be rewritten earlier in this same "
                    f"command by {taint.who}, whose effect the guard cannot "
                    "compute before the command runs"
                )
        if entry is not None:
            if entry.text is None:
                raise _Unknown(
                    f"{what} {word.text} is written earlier in this same command "
                    f"by {entry.reason}, whose output the guard cannot compute "
                    "before the command runs"
                )
            return entry.text
        try:
            return Path(path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise _Unknown(f"{what} {word.text} could not be read: {exc}") from exc

    def write(self, path: str, text: str | None, reason: str | None) -> None:
        if path in _DEV_FILES:
            return
        self.files[path] = _File(text, reason, self.at)

    # -- output of one command ------------------------------------------------

    def stdin(self, cmd: _Cmd) -> str:
        for redirect in reversed(cmd.redirects):
            if redirect.op == "<<<" and redirect.target is not None:
                return self.expand(redirect.target) + "\n"
            if redirect.op == "<" and redirect.fd in (None, "0") and redirect.target:
                return self.read(redirect.target, "the file on standard input")
        if cmd.heredocs:
            doc = cmd.heredocs[-1]
            if not doc.expands:
                return doc.body
            try:
                return self._expand_text(doc.body, "double", False)
            except _Unknown as exc:
                raise _Unknown(
                    f"the here-document {doc.delimiter} expands text the guard "
                    f"cannot resolve ({exc}); quote its delimiter, as <<'"
                    f"{doc.delimiter}', or write the body with the editor tool"
                ) from exc
        if cmd.piped_from is not None:
            return self.stdout(cmd.piped_from)
        raise _Unknown(
            "the replacement body is read from standard input, and nothing in "
            "this command that the guard can read supplies it"
        )

    def stdout(self, cmd: _Cmd) -> str:
        program, args = _program_of(cmd.words)
        if program == "cat":
            if any(a.text.startswith("-") and a.text != "-" for a in args):
                raise _Unknown("`cat` with options is not modelled")
            if not args or [a.text for a in args] == ["-"]:
                return self.stdin(cmd)
            return "".join(
                self.stdin(cmd) if a.text == "-" else self.read(a, "the file")
                for a in args
            )
        if program == "tee":
            return self.stdin(cmd)
        if program == "echo":
            newline = "\n"
            if args and args[0].text == "-n":
                newline = ""
                args = args[1:]
            values = [self.expand(a) for a in args]
            if any("\\" in v for v in values) or (
                args and args[0].text.startswith("-")
            ):
                raise _Unknown("`echo` with escapes or options differs between shells")
            return " ".join(values) + newline
        if program == "printf":
            if not args or args[0].text.startswith("-"):
                raise _Unknown("`printf` with options is not modelled")
            return _printf(self.expand(args[0]), [self.expand(a) for a in args[1:]])
        if program == "gh":
            selector, repo = _live_read_target(args, self)
            if selector is not None and self.live_body is not None:
                body = self.live_body(
                    PrBodyEdit(
                        selector=selector,
                        repo=repo,
                        new_body=None,
                        unreadable_reason=None,
                        origin="read",
                    )
                )
                if body is None:
                    raise _Unknown(
                        f"the live description of {repo}#{selector} could not "
                        "be read, and this command writes it to the body file"
                    )
                return body if body.endswith("\n") else body + "\n"
        raise _Unknown(
            f"the output of `{program or 'a compound command'}` cannot be "
            "computed without running it"
        )

    # -- effects of one command -----------------------------------------------

    def apply(self, cmd: _Cmd) -> None:
        """Record what ``cmd`` does to files and to the working directory."""
        self.at += 1
        program, args = _program_of(cmd.words)
        who = f"`{program}`" if program else "a compound command"

        if cmd.words and all(w.assignment() is not None for w in cmd.words):
            for word in cmd.words:
                name, value = word.assignment()  # type: ignore[misc]
                try:
                    self.scope.maps[0][name] = self.expand(value)
                except _Unknown:
                    self.scope.maps[0][name] = None
            return

        if program in ("cd", "pushd", "popd"):
            target = args[0] if args else None
            if program != "cd" or cmd.in_subshell:
                self.cwd = None
            elif target is None:
                self.cwd = self.scope.get("HOME")
            else:
                try:
                    self.cwd = self.path(target)
                except _Unknown:
                    self.cwd = None

        for redirect in cmd.redirects:
            if redirect.op not in _WRITE_OPS or redirect.target is None:
                continue
            if redirect.op == ">&" and (
                redirect.target.text.isdigit() or redirect.target.text == "-"
            ):
                continue
            try:
                path = self.path(redirect.target)
            except _Unknown as exc:
                self.taints.append(
                    _Taint(
                        self.at,
                        f"{who} writing to {redirect.target.text} ({exc})",
                        None,
                    )
                )
                continue
            if path in _DEV_FILES:
                continue
            if redirect.fd not in (None, "1") or redirect.op in ("&>", "&>>", ">&"):
                self.write(path, None, f"{who} (its error stream)")
                continue
            appending = redirect.op == ">>"
            try:
                text = self.stdout(cmd)
                if appending:
                    base = self._current(path)
                    text = base + text
            except _Unknown as exc:
                self.write(path, None, f"{who} ({exc})")
                continue
            self.write(path, text, None)

        if program == "tee":
            appending = bool(args) and args[0].text == "-a"
            targets = args[1:] if appending else args
            piped: str | None
            try:
                piped = self.stdin(cmd)
            except _Unknown:
                piped = None
            for target in targets:
                try:
                    path = self.path(target)
                except _Unknown as exc:
                    self.taints.append(_Taint(self.at, f"`tee` ({exc})", None))
                    continue
                if piped is not None and appending:
                    try:
                        self.write(path, self._current(path) + piped, None)
                    except _Unknown:
                        self.write(path, None, "`tee -a`")
                else:
                    self.write(path, piped, None if piped is not None else "`tee`")
            return

        if (
            program == "cp"
            and len(args) == 2
            and not any(a.text.startswith("-") for a in args)
        ):
            try:
                dest = self.path(args[1])
            except _Unknown as exc:
                self.taints.append(_Taint(self.at, f"`cp` ({exc})", None))
                return
            try:
                self.write(dest, self.read(args[0], "the copied file"), None)
            except _Unknown:
                self.write(dest, None, "`cp`")
            return

        if not program:
            return
        runs_a_script = "/" in next(
            (w.text for w in cmd.words if w.assignment() is None), ""
        )
        if _INTERPRETERS.match(program) or runs_a_script:
            self.taints.append(_Taint(self.at, who, None))
            return
        if program not in _NO_FILE_WRITES:
            self.taints.append(_Taint(self.at, who, self._mention_text(cmd)))

    def _mention_text(self, cmd: _Cmd) -> str:
        """Every word of ``cmd``, as written and as expanded, and its
        here-document bodies: where a program would name the file it writes."""
        parts: list[str] = []
        for word in cmd.words:
            parts.append(word.text)
            try:
                parts.append(self.expand(word))
            except _Unknown:
                pass
        parts += [doc.body for doc in cmd.heredocs]
        return "\n".join(parts)

    def _current(self, path: str) -> str:
        entry = self.files.get(path)
        if entry is not None:
            if entry.text is None:
                raise _Unknown(entry.reason or "unknown")
            return entry.text
        try:
            return Path(path).read_text(encoding="utf-8")
        except FileNotFoundError:
            return ""
        except (OSError, UnicodeDecodeError) as exc:
            raise _Unknown(str(exc)) from exc


def _live_read_target(args: list[Word], model: _Model) -> tuple[str | None, str | None]:
    """``(selector, repo)`` when ``args`` print one pull request's live body.

    Recognised: ``gh pr view [<n>] [-R <repo>] --json body --jq|-q .body`` and
    ``gh api repos/<o>/<r>/pulls/<n> --jq .body`` with no method or fields.
    """
    texts = [a.text for a in args]

    def value_after(*flags: str) -> str | None:
        for index, text in enumerate(texts):
            for flag in flags:
                if text == flag and index + 1 < len(texts):
                    try:
                        return model.expand(args[index + 1])
                    except _Unknown:
                        return None
                if text.startswith(flag + "="):
                    return text.partition("=")[2]
        return None

    if value_after("--jq", "-q") != ".body":
        return None, None
    if texts[:2] == ["pr", "view"]:
        if value_after("--json") != "body":
            return None, None
        selector: str | None = None
        index = 2
        while index < len(texts):
            text = texts[index]
            if text in _VIEW_VALUE_FLAGS:
                index += 2
                continue
            if not text.startswith("-") and selector is None:
                try:
                    selector = model.expand(args[index])
                except _Unknown:
                    return None, None
            index += 1
        return selector, value_after("--repo", "-R")
    if texts[:1] == ["api"]:
        if any(
            t in ("-X", "--method", "-f", "-F", "--field", "--raw-field", "--input")
            for t in texts
        ):
            return None, None
        endpoint = texts[1] if len(texts) > 1 else ""
        match = re.match(r"^/?repos/([^/$]+)/([^/$]+)/pulls/(\d+)$", endpoint)
        if match is None:
            return None, None
        return match.group(3), f"{match.group(1)}/{match.group(2)}"
    return None, None


#: ``gh pr view`` flags that take a value, so the value is never the selector.
_VIEW_VALUE_FLAGS = frozenset(
    {"--repo", "-R", "--json", "--jq", "-q", "--template", "-t"}
)

_PRINTF_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", '"': '"', "'": "'",
                   "a": "\a", "b": "\b", "f": "\f", "v": "\v"}  # fmt: skip


def _printf_escapes(text: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(text):
        if text[i] == "\\" and i + 1 < len(text):
            nxt = text[i + 1]
            if nxt not in _PRINTF_ESCAPES:
                raise _Unknown(f"printf escape \\{nxt} is not modelled")
            out.append(_PRINTF_ESCAPES[nxt])
            i += 2
            continue
        out.append(text[i])
        i += 1
    return "".join(out)


def _printf(fmt: str, args: list[str]) -> str:
    """``printf`` for the ``%s``, ``%b`` and ``%%`` directives, which is what a
    body is assembled with. Any other directive is unknown, not guessed."""
    out: list[str] = []
    remaining = list(args)
    while True:
        consumed = False
        i = 0
        while i < len(fmt):
            ch = fmt[i]
            if ch == "\\":
                out.append(_printf_escapes(fmt[i : i + 2]))
                i += 2
                continue
            if ch == "%":
                directive = fmt[i + 1 : i + 2]
                if directive == "%":
                    out.append("%")
                elif directive in ("s", "b"):
                    value = remaining.pop(0) if remaining else ""
                    consumed = True
                    out.append(_printf_escapes(value) if directive == "b" else value)
                else:
                    raise _Unknown(f"printf directive %{directive} is not modelled")
                i += 2
                continue
            out.append(ch)
            i += 1
        if not remaining or not consumed:
            return "".join(out)


def _resolve_body_word(word: Word, model: _Model) -> tuple[str | None, str | None]:
    try:
        return model.expand(word), None
    except _Unknown as exc:
        return None, (
            f"the replacement body {word.text[:80]!r} cannot be read here ({exc}). "
            "Pass the body with --body-file <path> instead, which this guard can "
            f"read. {_WORKAROUND}"
        )


def _read_body_file(
    word: Word, cmd: _Cmd, model: _Model
) -> tuple[str | None, str | None]:
    try:
        if word.text == "-":
            return model.stdin(cmd), None
        return model.read(word), None
    except _Unknown as exc:
        return None, f"{exc}. {_WORKAROUND}"


def _flag_value(rest: list[Word], index: int) -> tuple[Word | None, int]:
    """The value of the flag at ``index`` (inline or next word), and the next index."""
    word = rest[index]
    if "=" in word.text and word.text.startswith("-"):
        return _split_inline(word), index + 1
    if index + 1 < len(rest):
        return rest[index + 1], index + 2
    return None, index + 1


def _parse_gh_pr_edit(
    words: list[Word], shape: _GhPrEditShape, cmd: _Cmd, model: _Model
) -> PrBodyEdit | None:
    texts = [w.text for w in words]
    if texts[: len(shape.subcommand)] != list(shape.subcommand):
        return None
    rest = words[len(shape.subcommand) :]

    selector: str | None = None
    repo: str | None = None
    new_body: str | None = None
    unreadable: str | None = None
    origin = ""
    found_body = False

    index = 0
    while index < len(rest):
        text = rest[index].text
        flag = text.partition("=")[0]
        if flag in shape.body_flags:
            found_body, origin = True, "--body"
            value, index = _flag_value(rest, index)
            if value is None:
                new_body, unreadable = None, "the body flag was given no value"
            else:
                new_body, unreadable = _resolve_body_word(value, model)
            continue
        if flag in shape.body_file_flags:
            found_body, origin = True, "--body-file"
            value, index = _flag_value(rest, index)
            if value is None:
                new_body, unreadable = None, "the body-file flag was given no value"
            else:
                new_body, unreadable = _read_body_file(value, cmd, model)
            continue
        if flag in shape.repo_flags:
            value, index = _flag_value(rest, index)
            if value is not None:
                repo = _best_effort(value, model)
            continue
        if text.startswith("-"):
            # An unknown flag may or may not take a value. Skipping only the
            # flag is safe: the live read of a wrong selector fails, which is a
            # refusal rather than a wrong verdict.
            index += 1
            continue
        if selector is None:
            selector = _best_effort(rest[index], model)
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


def _best_effort(word: Word, model: _Model) -> str:
    try:
        return model.expand(word)
    except _Unknown:
        return word.text


def _parse_gh_api_patch(
    words: list[Word], shape: _GhApiPatchShape, cmd: _Cmd, model: _Model
) -> PrBodyEdit | None:
    texts = [w.text for w in words]
    if texts[: len(shape.subcommand)] != list(shape.subcommand):
        return None
    rest = words[len(shape.subcommand) :]

    method = "GET"
    endpoint: str | None = None
    new_body: str | None = None
    unreadable: str | None = None
    found_body = False
    origin = ""

    index = 0
    while index < len(rest):
        text = rest[index].text
        flag, _, inline = text.partition("=")
        if text in shape.method_flags and index + 1 < len(rest):
            method = rest[index + 1].text.upper()
            index += 2
            continue
        if flag in shape.method_flags and "=" in text:
            method = inline.upper()
            index += 1
            continue
        if text in shape.field_flags and index + 1 < len(rest):
            assignment = rest[index + 1].assignment()
            if assignment is not None and assignment[0] == shape.body_field:
                found_body, origin = True, text
                value = assignment[1]
                if text in _TYPED_FIELD_FLAGS and value.text.startswith("@"):
                    new_body, unreadable = _read_body_file(_drop_at(value), cmd, model)
                else:
                    new_body, unreadable = _resolve_body_word(value, model)
            index += 2
            continue
        if text in shape.input_flags and index + 1 < len(rest):
            found_body, origin = True, text
            payload, unreadable = _read_body_file(rest[index + 1], cmd, model)
            new_body = None
            if payload is not None:
                try:
                    parsed = json.loads(payload)
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
                        # No body field: this PATCH replaces something else.
                        found_body = False
                        unreadable = None
            index += 2
            continue
        if text.startswith("-"):
            index += 1
            continue
        if endpoint is None:
            endpoint = _best_effort(rest[index], model)
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


def _drop_at(value: Word) -> Word:
    first = value.parts[0]
    return Word((WordPart(first.text[1:], first.quote),) + value.parts[1:])


#: The raw-text test used only when the command cannot be split into words:
#: could any segment of it be a body-replacing edit? The parser only ever
#: recognises a program literally named ``gh``, so text without ``gh`` followed
#: by ``pr edit`` or ``api`` cannot hide one.
_EDIT_TEXT = re.compile(r"\bgh\b[\s\S]*?\b(?:pr\s+edit|api)\b")


def _is_edit(program: str, words: list[Word], policy: Policy) -> bool:
    texts = [w.text for w in words]
    if program in policy.gh_pr_edit.programs and (
        texts[: len(policy.gh_pr_edit.subcommand)] == list(policy.gh_pr_edit.subcommand)
    ):
        return True
    return program in policy.gh_api_patch.programs and (
        texts[: len(policy.gh_api_patch.subcommand)]
        == list(policy.gh_api_patch.subcommand)
    )


def parse_pr_body_edits(
    command: str,
    policy: Policy,
    *,
    cwd: str | None = None,
    live_body: LiveBodyReader | None = None,
) -> list[PrBodyEdit]:
    """Every body-replacing pull-request edit in ``command``.

    ``cwd`` is the session's working directory, against which a relative body
    file resolves (default: this process's). ``live_body`` lets the model
    compute a file the command fills with a pull request's live description;
    without it such a file is unknown.
    """
    commands = _commands(command)
    candidates = {
        id(cmd) for cmd in commands if _is_edit(*_program_of(cmd.words), policy)
    }
    if not candidates:
        return []
    # Only what the command itself assigns is expanded, plus HOME for `~`.
    # The hook's environment is not the command's: a variable it inherits may
    # name a different file from the one gh uploads, and reading that file
    # would judge the wrong body. A name the command sets any other way
    # (`export`, `read`, `for`) is unresolvable too.
    assigned: dict[str, str | None] = {}
    trusted = {"HOME": os.environ["HOME"]} if os.environ.get("HOME") else {}
    shadowed = shadowed_names([[w.text for w in cmd.words] for cmd in commands])
    scope: ChainMap[str, str | None] = ChainMap(
        assigned, dict(shadow(trusted, shadowed))
    )
    model = _Model(scope, cwd if cwd is not None else os.getcwd(), live_body)

    edits: list[PrBodyEdit] = []
    for cmd in commands:
        program, words = _program_of(cmd.words)
        edit: PrBodyEdit | None = None
        if id(cmd) in candidates:
            if program in policy.gh_pr_edit.programs:
                edit = _parse_gh_pr_edit(words, policy.gh_pr_edit, cmd, model)
            if edit is None and program in policy.gh_api_patch.programs:
                edit = _parse_gh_api_patch(words, policy.gh_api_patch, cmd, model)
        if edit is not None:
            edits.append(edit)
        model.apply(cmd)
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
    command: object,
    policy: Policy,
    live_body: LiveBodyReader,
    cwd: str | None = None,
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
        edits = parse_pr_body_edits(command, policy, cwd=cwd, live_body=live_body)
    except _Untokenisable as exc:
        if not _EDIT_TEXT.search(command):
            # Text that never names `gh` then `pr edit` or `api` cannot hold a
            # body-replacing edit: the parser recognises no other spelling.
            return []
        return [
            Finding(
                kind="untokenisable",
                detail=(
                    "this command names a pull-request edit and cannot be split "
                    f"into shell words ({exc}), so the replacement body it sends "
                    "cannot be read. Write the body to a file with the editor "
                    "tool, then run the edit as its own Bash call with "
                    "--body-file <path>"
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

    findings = check_bash_command(
        command, policy, reader, cwd if isinstance(cwd, str) else None
    )
    if findings:
        return _block(render_block_reason(findings))
    return 0


if __name__ == "__main__":
    sys.exit(main())
