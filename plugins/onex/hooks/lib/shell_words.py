#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
r"""Shell word splitting and path expansion shared by PreToolUse guards (OMN-19229).

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
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

QuoteKind = Literal["none", "double", "literal"]

_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_UNQUOTED_GLOB = re.compile(r"[*?\[]")
_UNQUOTED_BRACE = re.compile(r"\{[^{}]*(?:,|\.\.)[^{}]*\}")
_PARAMETER = re.compile(r"\$(?:\{[A-Za-z_][A-Za-z0-9_]*\}|[A-Za-z_][A-Za-z0-9_]*)")

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
    quote: QuoteKind


@dataclass(frozen=True)
class Word:
    parts: tuple[WordPart, ...]

    @property
    def text(self) -> str:
        """The word with quotes removed and nothing expanded."""
        return "".join(part.text for part in self.parts)

    @property
    def is_plain(self) -> bool:
        """True when the word needs no expansion at all."""
        for part in self.parts:
            if part.quote == "literal":
                continue
            if "$" in part.text or "`" in part.text:
                return False
            if part.quote == "none" and (
                part.text.startswith("~")
                or _UNQUOTED_GLOB.search(part.text)
                or _UNQUOTED_BRACE.search(part.text)
            ):
                return False
        return True

    def assignment(self) -> tuple[str, Word] | None:
        """``(NAME, value)`` when this word is a ``NAME=value`` assignment."""
        if not self.parts or self.parts[0].quote != "none":
            return None
        head = self.parts[0].text
        match = _ASSIGNMENT.match(head)
        if match is None:
            return None
        name = head[: match.end() - 1]
        rest = head[match.end() :]
        value_parts = ((WordPart(rest, "none"),) if rest else ()) + self.parts[1:]
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
        return Word((WordPart(self.body, "double" if self.expands else "literal"),))


Token = Word | Operator | HereDoc


class _Builder:
    def __init__(self) -> None:
        self.parts: list[WordPart] = []
        self.started = False

    def add(self, text: str, quote: QuoteKind) -> None:
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


def _scan_balanced(command: str, start: int, opener: str, closer: str) -> int:
    """Index just past the ``closer`` matching the ``opener`` at ``start``."""
    depth = 0
    i = start
    n = len(command)
    while i < n:
        ch = command[i]
        if ch == "\\":
            i += 2
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
        lines: list[str] = []
        while i < len(command):
            end = command.find("\n", i)
            line = command[i:] if end < 0 else command[i:end]
            i = len(command) if end < 0 else end + 1
            if heredoc.strip_tabs:
                line = line.lstrip("\t")
            if line == heredoc.delimiter:
                break
            lines.append(line + "\n")
        heredoc.body = "".join(lines)
    pending.clear()
    return i


def tokenize(command: str) -> list[Token]:
    """Split ``command`` into words and command separators.

    Redirections are dropped together with their targets, so ``2>&1`` and
    ``>/dev/null`` never reach a guard as arguments. A here-document becomes a
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
    drop_next: HereDoc | bool = False
    i = 0
    n = len(command)

    def finish_word() -> None:
        nonlocal drop_next
        word = builder.take()
        if word is None:
            return
        if isinstance(drop_next, HereDoc):
            drop_next.delimiter = word.text
            drop_next.expands = all(part.quote == "none" for part in word.parts)
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
                builder.add(command[i + 1], "literal")
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
            if builder.started and all(
                part.quote == "none" and part.text.isdigit() for part in builder.parts
            ):
                builder.take()
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
                continue
            if op in ("<<", "<<-"):
                drop_next = HereDoc(strip_tabs=op == "<<-")
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
            builder.add(command[i + 1 : end], "literal")
            i = end + 1
            continue
        if ch == '"':
            text, i = _scan_double(command, i + 1)
            builder.add(text, "double")
            continue
        if ch == "$":
            end = _scan_dollar(command, i)
            builder.add(command[i:end], "none")
            i = end
            continue
        if ch == "`":
            end = _scan_backtick(command, i)
            builder.add(command[i:end], "none")
            i = end
            continue
        builder.add(ch, "none")
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
        if name not in env:
            raise UnresolvableWord(f"`${name}` is unset")
        value = env[name]
        if value is None:
            raise UnresolvableWord(
                f"`${name}` is assigned in this command to a value the guard "
                "cannot resolve"
            )
        if value == "":
            raise UnresolvableWord(f"`${name}` is set but empty")
        out.append(value)
        i += consumed
    return "".join(out)


def expand_word(word: Word, env: Mapping[str, str | None]) -> str:
    """The value the shell would give ``word``, or :class:`UnresolvableWord`.

    ``env`` maps a variable to its value, or to ``None`` when it was assigned
    in the same command to something that could not be resolved.
    """
    out: list[str] = []
    for index, part in enumerate(word.parts):
        if part.quote == "literal":
            out.append(part.text)
            continue
        text = part.text
        if part.quote == "none":
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
        if part.quote == "none":
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
