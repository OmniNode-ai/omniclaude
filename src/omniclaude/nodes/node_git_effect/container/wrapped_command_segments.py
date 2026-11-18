# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Wrapper programs of a Bash command, split out of the git admission handler (OMN-24734).

The shared-tree git guard judges each simple command's own words. A command a wrapper
runs for its caller (`bash -c`, `python3 -c` handing a script to bash, `perl -e` with
`exec @ARGV`, `timeout`) is a segment of its own here, so a `git push --force origin main`
inside the detached push launch of the standing rules block is judged as the plain command is.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from typing import Final

from omniclaude.nodes.node_git_effect.handlers.handler_shell_words import (
    ShellSyntaxError,
)

#: Splits a script into its simple commands (words and joiner): the guard's own tokenizer.
Splitter = Callable[[str], list[tuple[list[str], str]]]

#: Wrapper programs stripped before a segment's program is read, so
#: `sudo git reset --hard` is still a git reset.
WRAPPERS: Final[frozenset[str]] = frozenset(
    {"sudo", "env", "command", "time", "nohup", "nice", "doas"}
)

#: Shell reserved words that may stand in front of a simple command, so the
#: command's own first word is not its program (OMN-18927). `do` and `{` were
#: already peeled for a loop body (OMN-19380); the rest head a condition
#: (`if`, `elif`, `while`, `until`), a branch body (`then`, `else`) or negate
#: the command that follows (`!`). Left in place a segment's program reads as
#: the keyword, `_parse_git` returns None, and the git call inside a compound
#: command is never judged at all -- `if true; then git reset --hard
#: origin/main; fi` was admitted in the shared registry clone.
LEADING_KEYWORDS: Final[frozenset[str]] = frozenset(
    {"{", "!", "do", "then", "else", "elif", "if", "while", "until"}
)

ASSIGNMENT: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def strip_wrappers(tokens: list[str]) -> list[str]:
    result = list(tokens)
    while result:
        head = result[0]
        if ASSIGNMENT.match(head):
            result = result[1:]
            continue
        if os.path.basename(head) in WRAPPERS:
            result = result[1:]
            continue
        break
    return result


def peel_grouping(segment: list[str]) -> tuple[list[str], int, int]:
    """Strip subshell and brace grouping from one segment (OMN-19852).

    Returns ``(tokens, opened, closed)``: the segment without its leading
    ``(`` / ``{`` and its unmatched trailing ``)`` / ``}``, how many subshells
    it opens (each ``(`` keeps a directory change from leaking out) and how
    many it closes. A ``$(`` substitution balances itself and is left alone.
    """
    tokens = list(segment)
    opened = 0
    while tokens:
        head = tokens[0]
        if head in LEADING_KEYWORDS:
            # OMN-19380: a loop body begins with do before its first command.
            # OMN-18927: so does every other reserved word that may precede a
            # simple command, and a segment still wearing one is read as a
            # command named `then` rather than as the git call it carries.
            tokens = tokens[1:]
        elif head.startswith("(") and not head.startswith("$("):
            opened += 1
            tokens[0] = head[1:]
            if not tokens[0]:
                tokens = tokens[1:]
        else:
            break
    closed = 0
    balance = sum(t.count("(") - t.count(")") for t in tokens)
    while tokens and balance < 0 and tokens[-1].endswith(")"):
        tokens[-1] = tokens[-1][:-1]
        closed += 1
        balance += 1
        if not tokens[-1]:
            tokens.pop()
    while tokens and tokens[-1] == "}":
        tokens.pop()
    return tokens, opened, closed


def drop_timeout(tokens: list[str]) -> list[str]:
    """``timeout [opts] DURATION cmd...`` as ``cmd...``; anything else unchanged."""
    words = strip_wrappers(tokens)
    if not words or os.path.basename(words[0]) != "timeout":
        return tokens
    rest = words[1:]
    while rest and rest[0].startswith("-"):
        rest = rest[1:]
    return rest[1:]


#: Interpreters whose `-c`/`-e` argument is a script the guard reads as commands.
_SHELL_PROGRAMS: Final[frozenset[str]] = frozenset({"bash", "sh", "zsh", "dash", "ksh"})
_MAX_WRAP_DEPTH: Final[int] = 4


def _script_after_flag(words: list[str], letter: str) -> tuple[str, list[str]] | None:
    """The script a `-<letter>` flag takes, and the words after it, or None."""
    for index, word in enumerate(words):
        if word.startswith("-") and not word.startswith("--") and letter in word[1:]:
            if index + 1 < len(words):
                return str(words[index + 1]), words[index + 2 :]
            return None
    return None


def _wrapped_payloads(tokens: list[str], split: Splitter) -> list[list[str]]:
    """Commands one wrapper runs for its caller (OMN-24734).

    `bash -c 'git push ...'`, `python3 -c '<code>' '<script>'` (the detached
    launch of the standing rules block hands the script to bash as an
    argument), `perl -e 'alarm N; exec @ARGV' git push ...` and
    `timeout N git push ...` all run a `git push` the words of the simple
    command never show. Each payload is a list of simple commands' words.
    """
    words = strip_wrappers(peel_grouping(tokens)[0])
    if not words:
        return []
    name = os.path.basename(words[0])
    rest = [str(word) for word in words[1:]]
    scripts: list[str] = []
    payloads: list[list[str]] = []
    if name in _SHELL_PROGRAMS:
        found = _script_after_flag(rest, "c")
        if found is not None:
            scripts.append(found[0])
    elif name.startswith("python"):
        found = _script_after_flag(rest, "c")
        if found is not None:
            scripts.extend(arg for arg in found[1] if "git" in arg)
    elif name == "perl":
        found = _script_after_flag(rest, "e")
        if found is not None and "exec" in found[0] and "@ARGV" in found[0]:
            payloads.append(list(found[1]))
    elif name == "timeout":
        payloads.append(drop_timeout(list(words)))
    for script in scripts:
        try:
            payloads.extend(segment for segment, _ in split(script))
        except ShellSyntaxError:
            continue
    return [payload for payload in payloads if payload]


def with_wrapped_segments(
    segments: list[tuple[list[str], str]], split: Splitter
) -> list[tuple[list[str], str]]:
    """`segments`, each followed by the commands its wrappers run, to a depth."""

    def expand(tokens: list[str], depth: int) -> list[list[str]]:
        if depth >= _MAX_WRAP_DEPTH:
            return []
        found: list[list[str]] = []
        for payload in _wrapped_payloads(tokens, split):
            found.append(payload)
            found.extend(expand(payload, depth + 1))
        return found

    expanded: list[tuple[list[str], str]] = []
    for tokens, joiner in segments:
        expanded.append((tokens, joiner))
        expanded.extend((payload, "") for payload in expand(tokens, 0))
    return expanded
