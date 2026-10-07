#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
r"""Shell word splitting and path expansion shared by PreToolUse guards (OMN-19229).

Used by the worktree guard, the shared-tree git guard (``cd`` and ``git -C``
targets) and the PR-body stamp guard (body-file paths), so the class of
"a guard judged the raw text of a variable" is retired in one place.

The same module now owns command scope, cd/git -C composition and the
cat/printf/tee/cp/sed file projection, migrated from the PR-body guard.
Unresolvable protected operands produce an explicit unknown result and the
admission guard refuses with a preparation or absolute-path remedy. Nothing
is executed to resolve a command. Subshell state is restored on exit, while
its projected file writes remain visible to the parent shell.

Why this exists
---------------
A PreToolUse guard is handed the raw text of a Bash command and has to judge
the argument vector the shell will build from it. Guards that judged the raw
text instead refused correct commands and admitted wrong ones:

* the worktree guard read ``"$WT"`` as the literal string ``$WT`` joined to
  the hook's cwd and refused a destination that expanded to exactly the
  sanctioned location (ledger:5591);
* it took the value of ``-b`` as the destination (ledger:5848) and the
  ``2>&1`` of a ``git worktree add -h 2>&1`` as a path;
* it never saw ``git -C <clone> worktree add <relative>``, which git
  resolves against the ``-C`` directory, so a worktree landed inside a
  canonical clone (ledger:4007, ledger:5841).

``shlex`` alone is not enough for this. It forgets which parts of a word were
single-quoted (so ``'$WT'`` and ``"$WT"`` look the same), it eats the newline
that ends a comment (so the command on the next line joins the commented
one), and it splits ``2>&1`` into an argument ``2`` and an argument ``1``.
This module keeps the quoting of every part of a word, treats newlines as
command separators, drops redirections with their targets, and skips here-
document bodies, so a guard sees the words git will see.

Expansion is deliberately narrow and never executes anything
------------------------------------------------------------
:func:`expand_word` resolves ``~``, ``$NAME`` and ``${NAME}`` from a mapping
the caller supplies (the hook's environment, overlaid with plain assignments
made earlier in the same command). Everything else that the shell would
compute is refused with :class:`UnresolvableWord`: command substitution,
arithmetic, parameter operators such as ``${X:-y}``, positional and special
parameters, unquoted globs and brace expansion. An unset or empty variable is
refused too, because the shell would hand git a different argument vector.
Nothing here spawns a process.
"""

from __future__ import annotations

import os
import re
from collections import ChainMap
from collections.abc import (
    Callable,
    Iterable,
    Iterator,
    Mapping,
    MutableMapping,
    Sequence,
)
from dataclasses import dataclass
from pathlib import Path

from omniclaude.nodes.node_git_effect.enums.enum_quote_kind import EnumQuoteKind

_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_UNQUOTED_GLOB = re.compile(r"[*?\[]")
_UNQUOTED_BRACE = re.compile(r"\{[^{}]*(?:,|\.\.)[^{}]*\}")
_PARAMETER = re.compile(r"\$(?:\{[A-Za-z_][A-Za-z0-9_]*\}|[A-Za-z_][A-Za-z0-9_]*)")

# Variables the shell itself changes while a command runs, so the value a
# hook inherits says nothing about the value the command will see.
_DYNAMIC = frozenset({"PWD", "OLDPWD", "RANDOM", "SECONDS", "LINENO", "BASHPID", "_"})
# Builtins that set the variables named in their operands.
_SETTERS = frozenset({"read", "unset", "mapfile", "readarray"})

# Operators that end one simple command and start the next.
SEPARATORS = frozenset({";", ";;", "&", "&&", "|", "||", "|&", "\n", "(", ")"})


class ShellSyntaxError(ValueError):
    """The command cannot be split into words (an unbalanced quote, most likely)."""


class UnresolvableWord(ValueError):
    """A word whose value the shell would compute and this module will not."""


@dataclass(frozen=True)
class WordPart:
    text: str
    # "none": unquoted; "double": inside double quotes; "literal": single
    # quotes or a backslash escape, where nothing is expanded.
    quote: EnumQuoteKind


@dataclass(frozen=True)
class Word:
    parts: tuple[WordPart, ...]

    @property
    def text(self) -> str:
        """The word with quotes removed and nothing expanded."""
        return "".join(part.text for part in self.parts)

    @property
    def splits(self) -> bool:
        """True when an unquoted expansion makes the shell word-split this word."""
        return any(
            part.quote == EnumQuoteKind.NONE and ("$" in part.text or "`" in part.text)
            for part in self.parts
        )

    @property
    def is_plain(self) -> bool:
        """True when the word needs no expansion at all."""
        for part in self.parts:
            if part.quote == EnumQuoteKind.LITERAL:
                continue
            if "$" in part.text or "`" in part.text:
                return False
            if part.quote == EnumQuoteKind.NONE and (
                part.text.startswith("~")
                or _UNQUOTED_GLOB.search(part.text)
                or _UNQUOTED_BRACE.search(part.text)
            ):
                return False
        return True

    def assignment(self) -> tuple[str, Word] | None:
        """``(NAME, value)`` when this word is a ``NAME=value`` assignment."""
        if not self.parts or self.parts[0].quote != EnumQuoteKind.NONE:
            return None
        head = self.parts[0].text
        match = _ASSIGNMENT.match(head)
        if match is None:
            return None
        name = head[: match.end() - 1]
        rest = head[match.end() :]
        value_parts = (
            (WordPart(rest, EnumQuoteKind.NONE),) if rest else ()
        ) + self.parts[1:]
        return name, Word(value_parts)


@dataclass(frozen=True)
class Operator:
    text: str


class HereDoc:
    """A here-document, placed where its ``<<`` operator was.

    The body is filled in when the tokenizer reaches it, on the lines after the
    command. ``expands`` is False when any part of the delimiter was quoted,
    in which case the shell expands nothing inside the body.
    """

    def __init__(self, strip_tabs: bool) -> None:
        self.strip_tabs = strip_tabs
        self.delimiter = ""
        self.expands = True
        self.body = ""

    def as_word(self) -> Word:
        """The body as a word, quoted the way the shell reads it."""
        return Word(
            (
                WordPart(
                    self.body,
                    EnumQuoteKind.DOUBLE if self.expands else EnumQuoteKind.LITERAL,
                ),
            )
        )


class Redirect:
    """A redirection, emitted only by ``tokenize(..., keep_redirects=True)``.

    ``op`` is the operator without its descriptor digits (``>``, ``>>``,
    ``<``, ``<<<``, ``&>``, ``>|``, ``>&``); ``fd`` is the digits glued before
    it (``"2"`` in ``2>err.log``) or ``None``; ``target`` is the word after it,
    or ``None`` when the operator takes none (``>&-``). A here-document is a
    :class:`HereDoc`, never a ``Redirect``.

    Most guards want redirections dropped, which is the default. A guard that
    has to know which file a command writes (OMN-19542: a body file written by
    an earlier segment of the same command) asks for them.
    """

    def __init__(self, op: str, fd: str | None) -> None:
        self.op = op
        self.fd = fd
        self.target: Word | None = None


Token = Word | Operator | HereDoc | Redirect


class _Builder:
    def __init__(self) -> None:
        self.parts: list[WordPart] = []
        self.started = False

    def add(self, text: str, quote: EnumQuoteKind) -> None:
        self.started = True
        if not text:
            return
        if self.parts and self.parts[-1].quote == quote:
            self.parts[-1] = WordPart(self.parts[-1].text + text, quote)
        else:
            self.parts.append(WordPart(text, quote))

    def take(self) -> Word | None:
        if not self.started:
            return None
        word = Word(tuple(self.parts))
        self.parts = []
        self.started = False
        return word


def _heredoc_delimiter(command: str, i: int) -> tuple[str, bool, int]:
    """The delimiter of the ``<<`` at ``i``, whether tabs are stripped, and the index past it."""
    j = i + 2
    strip_tabs = command[j : j + 1] == "-"
    if strip_tabs:
        j += 1
    while j < len(command) and command[j] in " \t":
        j += 1
    out: list[str] = []
    while j < len(command) and command[j] not in " \t\n;&|()<>":
        ch = command[j]
        if ch in "'\"":
            end = command.find(ch, j + 1)
            if end < 0:
                raise ShellSyntaxError("unterminated here-document delimiter")
            out.append(command[j + 1 : end])
            j = end + 1
            continue
        if ch == "\\":
            out.append(command[j + 1 : j + 2])
            j += 2
            continue
        out.append(ch)
        j += 1
    return "".join(out), strip_tabs, j


def _read_lines_to(
    command: str, i: int, delimiter: str, strip_tabs: bool
) -> tuple[list[str], int]:
    """The body lines before the line holding ``delimiter`` alone, and the index past it."""
    lines: list[str] = []
    while i < len(command):
        end = command.find("\n", i)
        line = command[i:] if end < 0 else command[i:end]
        i = len(command) if end < 0 else end + 1
        if strip_tabs:
            line = line.lstrip("\t")
        if line == delimiter:
            break
        lines.append(line)
    return lines, i


def _scan_balanced(command: str, start: int, opener: str, closer: str) -> int:
    """Index just past the ``closer`` matching the ``opener`` at ``start``.

    A here-document or a comment inside a ``$( ... )`` is skipped as text, so
    an apostrophe in a commit message written through ``$(cat <<'EOF' ...)``
    is not read as an unterminated quote.
    """
    depth = 0
    i = start
    n = len(command)
    pending: list[tuple[str, bool]] = []
    while i < n:
        ch = command[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "\n":
            i += 1
            for delimiter, strip_tabs in pending:
                i = _read_lines_to(command, i, delimiter, strip_tabs)[1]
            pending.clear()
            continue
        if command.startswith("<<", i) and not command.startswith("<<<", i):
            delimiter, strip_tabs, i = _heredoc_delimiter(command, i)
            pending.append((delimiter, strip_tabs))
            continue
        if ch == "#" and (i == start + 1 or command[i - 1] in " \t\n;&|("):
            end = command.find("\n", i)
            i = n if end < 0 else end
            continue
        if ch == "'":
            end = command.find("'", i + 1)
            if end < 0:
                raise ShellSyntaxError("unterminated single quote")
            i = end + 1
            continue
        if ch == '"':
            i = _scan_double(command, i + 1)[1]
            continue
        if ch == "`":
            i = _scan_backtick(command, i)
            continue
        if ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    raise ShellSyntaxError(f"unterminated {opener}...{closer}")


def _scan_backtick(command: str, start: int) -> int:
    i = start + 1
    while i < len(command):
        if command[i] == "\\":
            i += 2
            continue
        if command[i] == "`":
            return i + 1
        i += 1
    raise ShellSyntaxError("unterminated backtick")


def _scan_dollar(command: str, start: int) -> int:
    """Index just past a ``$`` construct that must be kept whole."""
    nxt = command[start + 1] if start + 1 < len(command) else ""
    if nxt == "(":
        return _scan_balanced(command, start + 1, "(", ")")
    if nxt == "{":
        return _scan_balanced(command, start + 1, "{", "}")
    if nxt == "'":
        end = start + 2
        while end < len(command) and command[end] != "'":
            end += 2 if command[end] == "\\" else 1
        if end >= len(command):
            raise ShellSyntaxError("unterminated $'...' quote")
        return end + 1
    return start + 1


def _scan_double(command: str, start: int) -> tuple[str, int]:
    """Text inside a double-quoted string opening before ``start``, and the index past it."""
    out: list[str] = []
    i = start
    n = len(command)
    while i < n:
        ch = command[i]
        if ch == '"':
            return "".join(out), i + 1
        if ch == "\\" and i + 1 < n:
            nxt = command[i + 1]
            if nxt == "\n":
                i += 2
                continue
            if nxt in '$`"\\':
                # An escaped `$` or backtick keeps its backslash, so that
                # expansion reads it as a literal character rather than as a
                # parameter or a substitution; expand_word drops the backslash.
                out.append("\\" + nxt if nxt in "$`" else nxt)
                i += 2
                continue
            out.append(ch)
            i += 1
            continue
        if ch == "$":
            end = _scan_dollar(command, i)
            out.append(command[i:end])
            i = end
            continue
        if ch == "`":
            end = _scan_backtick(command, i)
            out.append(command[i:end])
            i = end
            continue
        out.append(ch)
        i += 1
    raise ShellSyntaxError("unterminated double quote")


def _read_heredoc_bodies(command: str, i: int, pending: list[HereDoc]) -> int:
    """Read the bodies of here-documents that start at ``i``; the index past them."""
    for heredoc in pending:
        lines, i = _read_lines_to(command, i, heredoc.delimiter, heredoc.strip_tabs)
        heredoc.body = "".join(line + "\n" for line in lines)
    pending.clear()
    return i


def tokenize(command: str, *, keep_redirects: bool = False) -> list[Token]:
    """Split ``command`` into words and command separators.

    Redirections are dropped together with their targets, so ``2>&1`` and
    ``>/dev/null`` never reach a guard as arguments. With ``keep_redirects``
    each one is emitted as a :class:`Redirect` token in its command instead,
    for a guard that must know which file a command writes; its target is
    still never a :class:`Word`. A here-document becomes a
    :class:`HereDoc` token in its command, so its body is never read as a
    command line, yet a guard can still judge it when a shell runs it as a
    script. Comments are dropped up to, but not including, the newline that
    ends them.
    """
    tokens: list[Token] = []
    builder = _Builder()
    pending_heredocs: list[HereDoc] = []
    # After a redirection operator the next word is its target and is
    # dropped; for `<<` it is the delimiter of this here-document.
    drop_next: HereDoc | Redirect | bool = False
    i = 0
    n = len(command)

    def finish_word() -> None:
        nonlocal drop_next
        word = builder.take()
        if word is None:
            return
        if isinstance(drop_next, Redirect):
            drop_next.target = word
        if isinstance(drop_next, HereDoc):
            drop_next.delimiter = word.text
            drop_next.expands = all(
                part.quote == EnumQuoteKind.NONE for part in word.parts
            )
            pending_heredocs.append(drop_next)
        if drop_next is not False:
            drop_next = False
            return
        tokens.append(word)

    while i < n:
        ch = command[i]
        if ch in " \t\r":
            finish_word()
            i += 1
            continue
        if ch == "\\":
            if i + 1 < n and command[i + 1] == "\n":
                i += 2
                continue
            if i + 1 < n:
                builder.add(command[i + 1], EnumQuoteKind.LITERAL)
            i += 2
            continue
        if ch == "#" and not builder.started:
            end = command.find("\n", i)
            i = n if end < 0 else end
            continue
        if ch == "\n":
            finish_word()
            tokens.append(Operator("\n"))
            i = _read_heredoc_bodies(command, i + 1, pending_heredocs)
            continue
        if ch in "<>" or (ch == "&" and command[i + 1 : i + 2] == ">"):
            # An all-digit word glued to the operator is its file descriptor.
            fd: str | None = None
            if builder.started and all(
                part.quote == EnumQuoteKind.NONE and part.text.isdigit()
                for part in builder.parts
            ):
                taken = builder.take()
                fd = taken.text if taken is not None else None
            finish_word()
            j = i + 1 if ch == "&" else i
            while j < n and command[j] in "<>":
                j += 1
            if j < n and command[j] in "&|":
                j += 1
            if command[i:j] == "<<" and j < n and command[j] == "-":
                j += 1
            op = command[i:j]
            i = j
            if j < n and command[j] == "-" and op.endswith("&"):
                # `>&-` closes a descriptor and has no target word.
                i += 1
                if keep_redirects:
                    tokens.append(Redirect(op, fd))
                continue
            if op in ("<<", "<<-"):
                drop_next = HereDoc(strip_tabs=op == "<<-")
                tokens.append(drop_next)
            elif keep_redirects:
                drop_next = Redirect(op, fd)
                tokens.append(drop_next)
            else:
                drop_next = True
            continue
        if ch in ";&|()":
            finish_word()
            j = i + 1
            if ch in ";&|" and j < n and command[j] in (";&|" if ch != ";" else ";"):
                j += 1
            tokens.append(Operator(command[i:j]))
            i = j
            continue
        if ch == "'":
            end = command.find("'", i + 1)
            if end < 0:
                raise ShellSyntaxError("unterminated single quote")
            builder.add(command[i + 1 : end], EnumQuoteKind.LITERAL)
            i = end + 1
            continue
        if ch == '"':
            text, i = _scan_double(command, i + 1)
            builder.add(text, EnumQuoteKind.DOUBLE)
            continue
        if ch == "$":
            end = _scan_dollar(command, i)
            builder.add(command[i:end], EnumQuoteKind.NONE)
            i = end
            continue
        if ch == "`":
            end = _scan_backtick(command, i)
            builder.add(command[i:end], EnumQuoteKind.NONE)
            i = end
            continue
        builder.add(ch, EnumQuoteKind.NONE)
        i += 1
    finish_word()
    return tokens


def split_commands(tokens: list[Token]) -> list[list[Word]]:
    """Group ``tokens`` into simple commands, dropping the separators."""
    commands: list[list[Word]] = []
    current: list[Word] = []
    for token in tokens:
        if isinstance(token, Operator):
            if current:
                commands.append(current)
            current = []
        elif isinstance(token, Word):
            current.append(token)
    if current:
        commands.append(current)
    return commands


def _expand_parameters(text: str, env: Mapping[str, str | None]) -> str:
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "\\" and i + 1 < n and text[i + 1] in "$`":
            out.append(text[i + 1])
            i += 2
            continue
        if ch == "`":
            raise UnresolvableWord(
                "command substitution with backticks is never executed by the guard"
            )
        if ch != "$":
            out.append(ch)
            i += 1
            continue
        rest = text[i + 1 :]
        if not rest:
            out.append("$")
            i += 1
            continue
        if rest.startswith("("):
            raise UnresolvableWord(
                "command substitution `$(...)` is never executed by the guard"
            )
        if rest.startswith("{"):
            close = rest.find("}")
            inner = rest[1:close] if close > 0 else rest[1:]
            if close < 0 or not _NAME.fullmatch(inner):
                raise UnresolvableWord(
                    f"parameter expansion `${{{inner}}}` is not resolved by the guard"
                )
            name = inner
            consumed = close + 2
        else:
            match = _NAME.match(rest)
            if match is None:
                raise UnresolvableWord(
                    f"`${rest[:1]}` (a positional, special or quoted parameter) "
                    "is not resolved by the guard"
                )
            name = match.group(0)
            consumed = match.end() + 1
        if name in _DYNAMIC:
            raise UnresolvableWord(
                f"`${name}` is set by the shell as the command runs, not by "
                "this environment"
            )
        if name not in env:
            raise UnresolvableWord(f"`${name}` is unset")
        value = env[name]
        if value is None:
            raise UnresolvableWord(
                f"`${name}` is set in this command to a value the guard cannot resolve"
            )
        if value == "":
            raise UnresolvableWord(f"`${name}` is set but empty")
        out.append(value)
        i += consumed
    return "".join(out)


def unquoted(token: str) -> Word:
    """A word from a token that ``shlex`` has already dequoted, read as unquoted.

    Guards that split commands with ``shlex`` lose each part's quoting, so they
    hand a token here to judge it the way the shell reads an unquoted word:
    ``~`` and parameters expand, and a glob is refused.
    """
    return Word((WordPart(token, EnumQuoteKind.NONE),))


def shadowed_names(commands: Iterable[Sequence[str]]) -> set[str]:
    """Names a command assigns, reads, loops over or unsets.

    The hook's environment holds the value such a variable had BEFORE the
    command ran, which is not the value a later word will expand to. A guard
    that cannot track the new value (``read``, ``for``, ``export X=$(...)``)
    must treat the name as unresolvable rather than read the stale one.
    """
    names: set[str] = set()
    for command in commands:
        for token in command:
            match = _ASSIGNMENT.match(token)
            if match is not None:
                names.add(token[: match.end() - 1])
        words = [t for t in command if _ASSIGNMENT.match(t) is None]
        if not words:
            continue
        head = os.path.basename(words[0])
        if head == "for" and len(words) > 1:
            names.add(words[1])
        elif head in _SETTERS:
            names.update(t for t in words[1:] if _NAME.fullmatch(t))
        elif head == "printf" and "-v" in words[:-1]:
            names.add(words[words.index("-v") + 1])
        elif head == "getopts" and len(words) > 2:
            names.add(words[2])
    return {name for name in names if _NAME.fullmatch(name)}


def shadow(env: Mapping[str, str], names: Iterable[str]) -> Mapping[str, str | None]:
    """``env`` with ``names`` marked unresolvable (see :func:`shadowed_names`)."""
    hidden: dict[str, str | None] = dict.fromkeys(names)
    return ChainMap(hidden, dict(env))


def expand_word(word: Word, env: Mapping[str, str | None]) -> str:
    """The value the shell would give ``word``, or :class:`UnresolvableWord`.

    ``env`` maps a variable to its value, or to ``None`` when it was assigned
    in the same command to something that could not be resolved.
    """
    out: list[str] = []
    for index, part in enumerate(word.parts):
        if part.quote == EnumQuoteKind.LITERAL:
            out.append(part.text)
            continue
        text = part.text
        if part.quote == EnumQuoteKind.NONE:
            if index == 0 and text.startswith("~"):
                head, sep, tail = text.partition("/")
                if head == "~":
                    home = env.get("HOME")
                    if not home:
                        raise UnresolvableWord("`~` with HOME unset")
                    expanded = home
                else:
                    expanded = os.path.expanduser(head)
                    if expanded == head:
                        raise UnresolvableWord(f"`{head}` names no known user")
                text = expanded + sep + tail
        expanded_text = _expand_parameters(text, env)
        if part.quote == EnumQuoteKind.NONE:
            # Judged on the text as written, with its parameters taken out:
            # a pattern the shell would match against the filesystem.
            written = _PARAMETER.sub("", text)
            if _UNQUOTED_GLOB.search(written):
                raise UnresolvableWord(
                    f"unquoted glob characters in `{part.text}` are not resolved "
                    "by the guard"
                )
            if _UNQUOTED_BRACE.search(written):
                raise UnresolvableWord(
                    f"brace expansion in `{part.text}` is not resolved by the guard"
                )
        out.append(expanded_text)
    return "".join(out)


# Static command scope and same-command file projection (OMN-17427).
_WRAPPERS = frozenset({"env", "sudo", "command", "nohup", "time", "timeout", "xargs"})


class _Untokenisable(ShellSyntaxError):
    """A command whose words cannot be read."""


class Scope(Mapping[str, str | None]):
    """Environment overlaid by the command's own assignments."""

    def __init__(self, env: Mapping[str, str], local: Mapping[str, str | None]):
        self._env, self._local = env, local

    def __getitem__(self, key: str) -> str | None:
        return self._local[key] if key in self._local else self._env[key]

    def __iter__(self) -> Iterator[str]:
        yield from self._local
        yield from (k for k in self._env if k not in self._local)

    def __len__(self) -> int:
        return len(set(self._env) | set(self._local))


def resolve_path(
    word: Word, scope: Mapping[str, str | None], cwd: str | Path | None
) -> str:
    raw = expand_word(word, scope)
    if word.splits:
        if scope.get("IFS", " \t\n") not in (None, " \t\n"):
            raise UnresolvableWord(
                "an unquoted path with a custom IFS cannot be resolved; quote the path"
            )
        if len(raw.split()) != 1:
            raise UnresolvableWord(
                "the unquoted path expands to multiple shell words; quote the path"
            )
    if not Path(raw).is_absolute():
        if cwd is None:
            raise UnresolvableWord(
                f"the relative path {raw} follows a directory change the guard cannot resolve; pass an absolute path"
            )
        raw = os.path.join(cwd, raw)
    return os.path.normpath(raw)


def apply_assignments(
    words: list[Word],
    scope: Mapping[str, str | None],
    local: MutableMapping[str, str | None],
    expand: Callable[[Word], str] | None = None,
) -> bool:
    body = words
    if body and body[0].text in {"export", "declare", "typeset", "local", "readonly"}:
        body = [w for w in body[1:] if not w.text.startswith("-")]
    pairs = [w.assignment() for w in body]
    if not body or any(pair is None for pair in pairs):
        return False
    for pair in pairs:
        assert pair is not None
        name, value = pair
        try:
            local[name] = expand(value) if expand else expand_word(value, scope)
        except (UnresolvableWord, _Unknown):
            local[name] = None
    return True


def directory_target(
    words: list[Word], scope: Mapping[str, str | None], cwd: str | Path | None
) -> str:
    program, args = _program_of(words)
    if program != "cd":
        raise UnresolvableWord(f"`{program}` directory stack is not tracked")
    options_done = False
    while args and args[0].text in {"--", "-L", "-P", "-e"}:
        option = args[0].text
        args = args[1:]
        if option == "--":
            options_done = True
            break
    if not args:
        home = scope.get("HOME")
        if not home:
            raise UnresolvableWord("`cd` with HOME unset")
        return os.path.normpath(home)
    if len(args) != 1 or args[0].text == "-":
        raise UnresolvableWord(
            "the cd directory stack or multiple operands cannot be resolved"
        )
    if args[0].text.startswith("-") and not options_done:
        raise UnresolvableWord("the cd option cannot be resolved")
    return resolve_path(args[0], scope, cwd)


def git_directory(
    operands: list[Word], scope: Mapping[str, str | None], cwd: str | Path | None
) -> str | None:
    directory = str(cwd) if cwd is not None else None
    for operand in operands:
        # Git treats an empty -C as a no-op, unlike an empty path operand.
        if not operand.text:
            continue
        directory = resolve_path(operand, scope, directory)
    return directory


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


@dataclass
class _Cmd:
    words: list[Word]
    heredocs: list[HereDoc]
    redirects: list[Redirect]
    piped_from: _Cmd | None
    in_subshell: bool
    context: tuple[int, ...] = ()


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
    serial = 0
    context: list[int] = []
    current = _Cmd([], [], [], None, False)
    piped: _Cmd | None = None

    def close(next_piped: bool) -> None:
        nonlocal current, piped
        if current.words or current.heredocs or current.redirects:
            out.append(current)
            piped = current if next_piped else None
        else:
            piped = None
        current = _Cmd([], [], [], piped, depth > 0, tuple(context))

    for token in tokens:
        if isinstance(token, Operator):
            if token.text == "(":
                close(False)
                depth += 1
                serial += 1
                context.append(serial)
                current.context = tuple(context)
                current.in_subshell = True
            elif token.text == ")":
                close(False)
                depth = max(0, depth - 1)
                if context:
                    context.pop()
                current.context = tuple(context)
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
        if part.quote == EnumQuoteKind.NONE and "=" in part.text:
            _, _, rest = part.text.partition("=")
            head = (WordPart(rest, EnumQuoteKind.NONE),) if rest else ()
            return Word(head + word.parts[index + 1 :])
        if part.quote != EnumQuoteKind.NONE:
            return None
    return None


#: Characters that make a ``sed`` pattern anything other than the literal text
#: it spells, in basic or extended syntax alike. A pattern free of all of them
#: matches exactly its own characters, so the substitution is the same
#: ``str.replace`` in every ``sed`` dialect.
_SED_PATTERN_SPECIAL = frozenset("\\.[]*^$+?(){}|")

#: Characters that make a ``sed`` replacement anything other than literal text.
_SED_REPLACEMENT_SPECIAL = frozenset("\\&\n")

#: A ``sed`` script that only prints lines: an optional line range, then ``p``.
_SED_PRINT_ONLY = re.compile(r"(?:(?:\d+|\$)(?:,(?:\d+|\$))?)?p")


@dataclass(frozen=True)
class _SedPlan:
    """One ``sed`` command read as a filter over its files, or standard input."""

    in_place: bool
    suffix: str
    #: ``-n``: nothing is printed except by a ``p`` command.
    quiet: bool
    #: ``(pattern, replacement, every)`` in the order ``sed`` applies them to
    #: each line.
    edits: tuple[tuple[str, str, bool], ...]
    files: tuple[Word, ...]


def _sed_substitution(script: str) -> tuple[str, str, bool] | None:
    """``(pattern, replacement, every)`` for ``s<d>literal<d>literal<d>[g]``."""
    if len(script) < 5 or script[0] != "s":
        return None
    delimiter = script[1]
    if delimiter.isalnum() or delimiter.isspace() or delimiter == "\\":
        return None
    parts = script[2:].split(delimiter)
    if len(parts) != 3 or parts[2] not in ("", "g"):
        return None
    pattern, replacement, flags = parts
    if not pattern or _SED_PATTERN_SPECIAL & set(pattern):
        return None
    if _SED_REPLACEMENT_SPECIAL & set(replacement):
        return None
    return pattern, replacement, flags == "g"


def _parse_sed(args: list[Word]) -> _SedPlan | None:
    """Read a ``sed`` command, or None when what it does cannot be computed.

    OMN-17427. ``sed`` was treated as a program that may rewrite any file it
    names, so a body file it merely printed or filtered made every later edit
    from that file "unknown", and a literal substitution the guard could just
    apply was refused too. What is modelled is what any ``sed`` reads the same
    way:

    * a script that only prints (``-n`` with an optional line range and ``p``),
      and a substitution whose pattern and replacement are literal text,
      neither of which can write a file, run a command or read another one;
    * ``-i`` in the two spellings that mean one thing to both the BSD and the
      GNU ``sed``: an attached suffix (``-i.bak``), and the BSD idiom ``-i ''``
      whose empty suffix is a separate word. A bare ``-i`` followed by a script
      is a suffix to BSD ``sed`` and an in-place edit to GNU ``sed``, so it is
      not read.

    Anything else -- a regular expression, a ``w`` or ``e`` command, a script
    file, several commands in one script, a long option -- is not modelled and
    leaves the file unknown, as before.
    """
    in_place = False
    suffix = ""
    quiet = False
    scripts: list[str] = []
    files: list[Word] = []
    index = 0
    options_done = False
    while index < len(args):
        word = args[index]
        text = word.text
        index += 1
        if options_done or not text.startswith("-") or text == "-":
            if not word.is_plain and not files and not scripts:
                return None  # a script the shell computes
            if not scripts and not files:
                scripts.append(text)
            else:
                files.append(word)
            continue
        if text == "--":
            options_done = True
            continue
        if text.startswith("--"):
            return None
        cluster = text[1:]
        for pos, letter in enumerate(cluster):
            if letter in "nEr":
                quiet = quiet or letter == "n"
            elif letter == "e":
                rest = cluster[pos + 1 :]
                if rest:
                    scripts.append(rest)
                elif index < len(args) and args[index].is_plain:
                    scripts.append(args[index].text)
                    index += 1
                else:
                    return None
                break
            elif letter == "i":
                in_place = True
                rest = cluster[pos + 1 :]
                if rest:
                    suffix = rest
                elif index < len(args) and args[index].text == "":
                    index += 1
                else:
                    return None
                break
            else:
                return None
    if not scripts or (quiet and in_place):
        return None
    edits: list[tuple[str, str, bool]] = []
    for script in scripts:
        substitution = _sed_substitution(script)
        if substitution is not None:
            edits.append(substitution)
        elif not (quiet and _SED_PRINT_ONLY.fullmatch(script)):
            return None
    return _SedPlan(in_place, suffix, quiet, tuple(edits), tuple(files))


def _sed_transform(text: str, edits: tuple[tuple[str, str, bool], ...]) -> str:
    """``text`` after ``sed`` applies each literal substitution to each line."""
    lines: list[str] = []
    for line in text.splitlines(keepends=True):
        body = line.rstrip("\n")
        ending = line[len(body) :]
        for pattern, replacement, every in edits:
            body = body.replace(pattern, replacement, -1 if every else 1)
        lines.append(body + ending)
    return "".join(lines)


class CommandResolver:
    """The files a command writes, followed in order, and how to read them."""

    def __init__(
        self,
        scope: ChainMap[str, str | None],
        cwd: str | None,
    ) -> None:
        self.scope = scope
        self.cwd = cwd
        self.files: dict[str, _File] = {}
        self.taints: list[_Taint] = []
        self.at = 0
        self._context: tuple[int, ...] = ()
        self._stack: list[tuple[str | None, dict[str, str | None]]] = []

    def enter(self, cmd: _Cmd) -> None:
        """Restore shell state at a subshell boundary; files remain shared."""
        common = 0
        for before, after in zip(self._context, cmd.context, strict=False):
            if before != after:
                break
            common += 1
        for _ in self._context[common:]:
            self.cwd, variables = self._stack.pop()
            self.scope.maps[0].clear()
            self.scope.maps[0].update(variables)
        for _ in cmd.context[common:]:
            self._stack.append((self.cwd, dict(self.scope.maps[0])))
        self._context = cmd.context

    # -- words ---------------------------------------------------------------

    def expand(self, word: Word) -> str:
        """The value the shell gives ``word``; command substitutions whose
        output the model can compute are substituted. Raises ``_Unknown``."""
        out: list[str] = []
        for index, part in enumerate(word.parts):
            if part.quote == EnumQuoteKind.LITERAL:
                out.append(part.text)
                continue
            out.append(self._expand_text(part.text, part.quote, index == 0))
        return "".join(out)

    def _expand_text(self, text: str, quote: EnumQuoteKind, first: bool) -> str:
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
                parts = (WordPart("", EnumQuoteKind.LITERAL),) + parts
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
                if quote == EnumQuoteKind.NONE:
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
            return resolve_path(word, self.scope, self.cwd)
        except UnresolvableWord as exc:
            raise _Unknown(str(exc)) from exc

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
                return self._expand_text(doc.body, EnumQuoteKind.DOUBLE, False)
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
        if program == "sed":
            plan = _parse_sed(args)
            if plan is not None and not plan.in_place and not plan.quiet:
                text = (
                    "".join(self.read(f, "the file") for f in plan.files)
                    if plan.files
                    else self.stdin(cmd)
                )
                return _sed_transform(text, plan.edits)
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
            options_done = bool(args) and args[0].text == "--"
            if options_done:
                args = args[1:]
            if not args or (not options_done and args[0].text.startswith("-")):
                raise _Unknown("`printf` with options is not modelled")
            return _printf(self.expand(args[0]), [self.expand(a) for a in args[1:]])
        raise _Unknown(
            f"the output of `{program or 'a compound command'}` cannot be "
            "computed without running it"
        )

    # -- effects of one command -----------------------------------------------

    def apply(self, cmd: _Cmd) -> None:
        """Record what ``cmd`` does to files and to the working directory."""
        self.enter(cmd)
        self.at += 1
        program, args = _program_of(cmd.words)
        who = f"`{program}`" if program else "a compound command"

        if apply_assignments(cmd.words, self.scope, self.scope.maps[0], self.expand):
            return
        if program in ("cd", "pushd", "popd"):
            try:
                self.cwd = directory_target(cmd.words, self.scope, self.cwd)
            except UnresolvableWord:
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
        if program == "sed":
            plan = _parse_sed(args)
            if plan is not None:
                if plan.in_place:
                    self._apply_sed_in_place(cmd, plan, who)
                # A filter writes only through a redirection, handled above.
                return
        runs_a_script = "/" in next(
            (w.text for w in cmd.words if w.assignment() is None), ""
        )
        if _INTERPRETERS.match(program) or runs_a_script:
            self.taints.append(_Taint(self.at, who, None))
            return
        if program not in _NO_FILE_WRITES:
            self.taints.append(_Taint(self.at, who, self._mention_text(cmd)))

    def _apply_sed_in_place(self, cmd: _Cmd, plan: _SedPlan, who: str) -> None:
        """Record the text ``sed -i`` leaves in each file it names.

        A file whose text or path the guard cannot read is left unknown, which
        is what an unmodelled ``sed`` did to every file it mentioned.
        """
        if not plan.files:
            return  # `sed -i` with no file reads no input and edits nothing
        try:
            results = []
            for word in plan.files:
                path = self.path(word)
                before = self.read(word, "the file")
                results.append((path, before, _sed_transform(before, plan.edits)))
        except _Unknown:
            self.taints.append(_Taint(self.at, who, self._mention_text(cmd)))
            return
        for path, before, after in results:
            if plan.suffix:
                self.write(path + plan.suffix, before, None)
            self.write(path, after, None)

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
