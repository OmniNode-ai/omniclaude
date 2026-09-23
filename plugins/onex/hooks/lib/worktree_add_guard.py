#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
r"""Decision core of the ``git worktree add`` canonical-root guard (OMN-19229, OMN-19123).

``pre_tool_use_worktree_guard.sh`` resolves the canonical worktree root and
hands this module the PreToolUse payload. This module finds every
``git ... worktree add`` in the command and judges the destination git will
actually receive, the way git reads its own arguments:

* global options before ``worktree`` are read, and each ``-C <dir>`` is
  composed onto the directory before it, exactly as git composes them;
* ``cd``/``pushd`` earlier in the same command move the directory a relative
  path resolves against, and a ``( ... )`` subshell restores it;
* the ``add`` options that take a value (``-b``, ``-B``, ``--reason``) consume
  it, attached or separate; ``--orphan`` and the other flags take none;
  ``--`` ends the options; options may follow the path, since git permutes;
* ``$NAME``, ``${NAME}`` and ``~`` are expanded from the hook's environment,
  overlaid with plain assignments made earlier in the same command;
* a relative destination resolves against the ``-C`` directory, not the
  hook's cwd -- the defect that put a worktree inside a canonical clone.

Fail-closed, and the refusal names what was judged
--------------------------------------------------
A destination is refused when it resolves outside the canonical root, and
also when it cannot be resolved at all: an unset variable, command
substitution (never executed), a relative path under an unknown directory,
an option this parser does not know, or a command that cannot be split into
words while it names ``worktree add``. Every refusal names the value it
judged, so the lane can see what the shell would have handed git.

A command with no real ``worktree add`` in it -- the words inside a commit
message, a here-document or a comment -- is not judged at all.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

_HOOKS_LIB = Path(__file__).parent
if str(_HOOKS_LIB) not in sys.path:
    sys.path.insert(0, str(_HOOKS_LIB))

from shell_words import (  # noqa: E402
    HereDoc,
    ShellSyntaxError,
    UnresolvableWord,
    Word,
    WordPart,
    expand_word,
    shadowed_names,
    tokenize,
)

DISABLE_HINT = "To disable this guard: onex hooks disable WORKTREE_GUARD"

# git's global options that take a separate value (`git --help`).
_GIT_VALUE_OPTIONS = frozenset(
    {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env"}
)

# `git worktree add` options, per git-worktree(1) (git 2.50).
_ADD_SHORT_FLAGS = frozenset("fdq")
_ADD_SHORT_VALUED = frozenset("bB")
_ADD_LONG_FLAGS = frozenset(
    {
        "force",
        "detach",
        "checkout",
        "no-checkout",
        "guess-remote",
        "no-guess-remote",
        "relative-paths",
        "no-relative-paths",
        "track",
        "no-track",
        "lock",
        "no-lock",
        "orphan",
        "no-orphan",
        "quiet",
        "no-quiet",
        "no-force",
        "no-detach",
    }
)
_ADD_LONG_VALUED = frozenset({"reason"})

# Programs that run their operands as a command, and so are looked through.
_WRAPPERS = frozenset({"command", "exec", "nohup", "time", "builtin"})
# Reserved words that can open a simple command without changing its argv.
_RESERVED = frozenset({"if", "then", "elif", "else", "do", "while", "until", "{", "!"})
_SHELLS = frozenset({"bash", "sh", "zsh", "dash"})
# Shell options that take a separate value.
_SHELL_VALUE_OPTIONS = frozenset({"-o", "+o", "-O", "+O", "--rcfile", "--init-file"})
# Programs whose operands are text, never a command they run.
_TEXT_ONLY = frozenset(
    {"echo", "printf", "grep", "egrep", "rg", "man", "which", "type"}
)
_DECLARERS = frozenset({"export", "declare", "typeset", "local", "readonly"})
_MAX_NESTING = 3

_WORKTREE_ADD_TEXT = re.compile(r"worktree\W+add\b")


class Refusal(Exception):
    """The command must be refused; the message is the reason."""


@dataclass(frozen=True)
class Decision:
    blocked: bool
    reason: str = ""
    judged: tuple[str, ...] = field(default_factory=tuple)


@dataclass
class _State:
    cwd: Path | None
    variables: dict[str, str | None]
    unknown: str = ""  # why `cwd` is None, when it is
    stack: list[tuple[Path | None, str]] = field(default_factory=list)


class _Scope(Mapping[str, str | None]):
    """The hook's environment, overlaid with this command's own assignments."""

    def __init__(self, env: Mapping[str, str], local: Mapping[str, str | None]):
        self._env = env
        self._local = local

    def __getitem__(self, key: str) -> str | None:
        if key in self._local:
            return self._local[key]
        return self._env[key]

    def __iter__(self) -> Iterator[str]:
        yield from self._local
        yield from (k for k in self._env if k not in self._local)

    def __len__(self) -> int:
        return len(set(self._env) | set(self._local))


def _join(base: Path | None, raw: str, what: str, unknown: str) -> Path:
    candidate = Path(raw)
    if candidate.is_absolute():
        return Path(os.path.normpath(candidate))
    if base is None:
        raise Refusal(
            f"the {what} `{raw}` is relative, and the directory it resolves "
            f"against cannot be determined ({unknown})"
        )
    return Path(os.path.normpath(base / candidate))


def _literal(text: str) -> Word:
    return Word((WordPart(text, "literal"),))


@dataclass
class _Unwrapped:
    words: list[Word]  # the command itself, wrappers and assignments removed
    chdirs: list[Word]  # `env -C <dir>` operands, in order
    split: Word | None  # an `env -S <string>` command string
    assignments: list[tuple[str, Word]]  # `NAME=value` given to this command only


def _unwrap(words: list[Word]) -> _Unwrapped:
    """Drop leading assignments, reserved words and wrappers such as ``env``."""
    result = list(words)
    chdirs: list[Word] = []
    split: Word | None = None
    assignments: list[tuple[str, Word]] = []
    while result:
        head = result[0]
        pair = head.assignment()
        if pair is not None:
            assignments.append(pair)
            result = result[1:]
            continue
        name = os.path.basename(head.text)
        if head.text in _RESERVED:
            result = result[1:]
            continue
        if name in _WRAPPERS:
            result = result[1:]
            while result and result[0].text.startswith("-"):
                result = result[1:]
            continue
        if name != "env":
            break
        result = result[1:]
        while result:
            text = result[0].text
            pair = result[0].assignment()
            if text in ("-C", "--chdir", "-S", "--split-string") and len(result) > 1:
                if text in ("-C", "--chdir"):
                    chdirs.append(result[1])
                else:
                    split = result[1]
                result = result[2:]
                continue
            if pair is not None:
                assignments.append(pair)
            elif text.startswith("--chdir="):
                chdirs.append(_literal(text.partition("=")[2]))
            elif text.startswith("--split-string="):
                split = _literal(text.partition("=")[2])
            elif text.startswith("-C") and len(text) > 2:
                chdirs.append(_literal(text[2:]))
            elif text.startswith("-S") and len(text) > 2:
                split = _literal(text[2:])
            elif text in ("-u", "--unset"):
                result = result[1:]
            elif not text.startswith("-"):
                break
            result = result[1:]
    return _Unwrapped(result, chdirs, split, assignments)


def _apply_assignments(
    words: list[Word], state: _State, env: Mapping[str, str]
) -> bool:
    """Record ``NAME=value`` words; True when ``words`` was only assignments."""
    body = words
    if body and body[0].text in _DECLARERS:
        body = [w for w in body[1:] if not w.text.startswith("-")]
    pairs = [w.assignment() for w in body]
    if not body or any(pair is None for pair in pairs):
        return False
    scope = _Scope(env, state.variables)
    resolved: dict[str, str | None] = {}
    for pair in pairs:
        assert pair is not None
        name, value = pair
        try:
            resolved[name] = expand_word(value, scope)
        except UnresolvableWord:
            resolved[name] = None
    state.variables.update(resolved)
    return True


def _apply_cd(words: list[Word], state: _State, env: Mapping[str, str]) -> bool:
    """Move ``state.cwd`` for a ``cd``/``pushd``/``popd``; True when it was one."""
    if not words or words[0].text not in ("cd", "pushd", "popd"):
        return False
    verb = words[0].text
    operands = [w for w in words[1:] if not w.text.startswith("-") or w.text == "-"]
    if verb == "popd" or (operands and operands[0].text == "-") or len(operands) > 1:
        state.cwd = None
        state.unknown = f"`{' '.join(w.text for w in words)}` is not tracked"
        return True
    if not operands:
        home = env.get("HOME")
        state.cwd = Path(home) if home else None
        state.unknown = "`cd` with HOME unset"
        return True
    try:
        target = expand_word(operands[0], _Scope(env, state.variables))
        state.cwd = _join(state.cwd, target, "`cd` target", state.unknown)
    except (UnresolvableWord, Refusal) as exc:
        state.cwd = None
        state.unknown = f"`{verb} {operands[0].text}` cannot be resolved: {exc}"
    return True


@dataclass(frozen=True)
class _Invocation:
    directory: Path | None  # where git runs, after every `-C`
    unknown: str  # why `directory` is None, when it is
    add_args: list[Word]
    via_wrapper: bool = False  # run by another program, which may append arguments


def _git_worktree_add(
    words: list[Word], state: _State, env: Mapping[str, str], *, via_wrapper: bool
) -> _Invocation | None:
    """The shape of one ``git ... worktree add`` command, or None if it is not one."""
    if not words or os.path.basename(words[0].text) != "git":
        return None
    scope = _Scope(env, state.variables)
    directory = state.cwd
    unknown = state.unknown
    args = words[1:]
    idx = 0
    while idx < len(args):
        text = args[idx].text
        if text == "-C" and idx + 1 < len(args):
            operand = args[idx + 1]
            try:
                directory = _join(
                    directory,
                    expand_word(operand, scope),
                    "`git -C` directory",
                    unknown,
                )
            except UnresolvableWord as exc:
                directory = None
                unknown = (
                    f"the `git -C` directory `{operand.text}` cannot be resolved: {exc}"
                )
            except Refusal as exc:
                directory = None
                unknown = str(exc)
            idx += 2
            continue
        if text in _GIT_VALUE_OPTIONS:
            idx += 2
            continue
        if text.startswith("-"):
            idx += 1
            continue
        break
    if (
        idx + 1 >= len(args)
        or args[idx].text != "worktree"
        or args[idx + 1].text != "add"
    ):
        return None
    return _Invocation(directory, unknown, list(args[idx + 2 :]), via_wrapper)


def _long_option(name: str) -> str:
    """git accepts any unambiguous prefix of a long option."""
    known = _ADD_LONG_FLAGS | _ADD_LONG_VALUED
    if name in known:
        return name
    matches = sorted(opt for opt in known if opt.startswith(name))
    if len(matches) == 1:
        return matches[0]
    raise Refusal(
        f"`--{name}` is not a `git worktree add` option this guard can read"
        + (f" (ambiguous: {', '.join('--' + m for m in matches)})" if matches else "")
    )


def _destination(add_args: list[Word], scope: Mapping[str, str | None]) -> Word | None:
    """The ``<path>`` operand of ``git worktree add``, or None when git makes nothing."""
    for word in add_args:
        # An unquoted expansion is split into words by the shell, which moves
        # every operand after it, so it must resolve to exactly one word.
        if not word.splits:
            continue
        try:
            value = expand_word(word, scope)
        except UnresolvableWord as exc:
            raise Refusal(
                f"the unquoted argument `{word.text}` cannot be resolved: {exc}"
            ) from exc
        if not value.strip() or len(value.split()) != 1:
            raise Refusal(
                f"the unquoted argument `{word.text}` expands to `{value}`, which the "
                "shell would split into a different number of words"
            )
    positionals: list[Word] = []
    idx = 0
    options_done = False
    while idx < len(add_args):
        word = add_args[idx]
        text = word.text
        idx += 1
        # An option is spelled with a leading dash, quoted or not; a word that
        # only expands to one (`"$X"`) is an operand, and is judged as one.
        first = word.parts[0].text if word.parts else ""
        if options_done or not first.startswith("-") or text == "-":
            positionals.append(word)
            continue
        if text == "--":
            options_done = True
            continue
        if text.startswith("--"):
            name, eq, _ = text[2:].partition("=")
            option = _long_option(name)
            if option in _ADD_LONG_VALUED:
                if not eq:
                    idx += 1
            elif eq:
                raise Refusal(f"`--{option}` takes no value, but `{text}` gives one")
            continue
        if text == "-h":
            return None  # usage text; nothing is created
        for pos, letter in enumerate(text[1:], start=1):
            if letter in _ADD_SHORT_FLAGS:
                continue
            if letter in _ADD_SHORT_VALUED:
                if pos == len(text) - 1:
                    idx += 1  # the value is the next word
                break  # otherwise the rest of this word is the value
            raise Refusal(
                f"`-{letter}` (in `{text}`) is not a `git worktree add` option "
                "this guard can read"
            )
    return positionals[0] if positionals else None


def _judge_add(
    invocation: _Invocation, state: _State, env: Mapping[str, str], root: Path | None
) -> str | None:
    """The resolved destination when admitted; raises Refusal otherwise."""
    target_word = _destination(invocation.add_args, _Scope(env, state.variables))
    if target_word is None:
        if invocation.via_wrapper:
            raise Refusal(
                "`git worktree add` is run by another program here and its path is "
                "not on the command line, so the destination cannot be judged"
            )
        return None
    try:
        raw = expand_word(target_word, _Scope(env, state.variables))
    except UnresolvableWord as exc:
        raise Refusal(
            f"the worktree path `{target_word.text}` cannot be resolved: {exc}"
        ) from exc
    if raw.startswith("-"):
        raise Refusal(
            f"the worktree path `{target_word.text}` expands to `{raw}`, which "
            "git would read as an option"
        )
    if root is None:
        raise Refusal(
            "cannot resolve the canonical worktree root. Set OMNI_HOME "
            "(preferred) or ONEX_WORKTREES_ROOT"
        )
    target = _join(invocation.directory, raw, "worktree path", invocation.unknown)
    resolved = Path(os.path.realpath(target))
    real_root = Path(os.path.realpath(root))
    if real_root not in resolved.parents:
        how = ""
        if not Path(raw).is_absolute():
            how = (
                f" (the relative path `{raw}` resolves against "
                f"`{invocation.directory}`, where git runs)"
            )
        elif raw != target_word.text:
            how = f" (`{target_word.text}` expands to `{raw}`)"
        raise Refusal(
            f"Worktrees must be created under {real_root}. Got: {resolved}{how}. "
            "To use a different root set ONEX_WORKTREES_ROOT"
        )
    return str(resolved)


def _embedded_command(words: list[Word]) -> list[Word] | None:
    """The git, shell or ``eval`` an unknown wrapper (``sudo``, ``timeout``) runs."""
    if os.path.basename(words[0].text) in _TEXT_ONLY:
        return None
    for idx in range(1, len(words)):
        name = os.path.basename(words[idx].text)
        if name == "git" or name in _SHELLS or name == "eval":
            return words[idx:]
    return None


def _nested(
    script: str,
    state: _State,
    env: Mapping[str, str],
    root: Path | None,
    judged: list[str],
    depth: int,
) -> None:
    """Judge a script another shell (or ``eval``) runs, in ``state``."""
    if not _WORKTREE_ADD_TEXT.search(script):
        return
    if depth >= _MAX_NESTING:
        raise Refusal("`worktree add` is nested too deeply in scripts to judge")
    _walk(script, state, env, root, judged, depth + 1)


def _child(
    state: _State,
    env: Mapping[str, str],
    assignments: Sequence[tuple[str, Word]] = (),
) -> _State:
    """The state a child starts in: this directory, these variables, and its own
    ``NAME=value`` prefix assignments, which the shell expands in the parent first."""
    child = _State(
        cwd=state.cwd, variables=dict(state.variables), unknown=state.unknown
    )
    scope = _Scope(env, state.variables)
    for name, value in assignments:
        try:
            child.variables[name] = expand_word(value, scope)
        except UnresolvableWord:
            child.variables[name] = None
    return child


def _shell_arguments(words: list[Word]) -> tuple[set[str], list[Word]]:
    """The option letters a shell was given and its operands, read the way a shell does."""
    letters: set[str] = set()
    operands: list[Word] = []
    idx = 1
    while idx < len(words):
        text = words[idx].text
        if operands:
            operands.append(words[idx])
        elif text == "--" or text == "-":
            operands.extend(words[idx + 1 :])
            break
        elif text in _SHELL_VALUE_OPTIONS:
            idx += 1
        elif text.startswith("--"):
            pass
        elif text[:1] in "-+" and len(text) > 1:
            if text[0] == "-":
                letters.update(text[1:])
        else:
            operands.append(words[idx])
        idx += 1
    return letters, operands


def _run_shell(
    words: list[Word],
    heredocs: list[HereDoc],
    state: _State,
    env: Mapping[str, str],
    root: Path | None,
    judged: list[str],
    depth: int,
) -> None:
    """Judge the script a ``bash``/``sh``/``zsh`` command runs, in a child ``state``."""
    program = os.path.basename(words[0].text)
    scope = _Scope(env, state.variables)
    letters, operands = _shell_arguments(words)
    if "c" in letters:
        if not operands:
            return  # the shell exits with a usage error
        try:
            script = expand_word(operands[0], scope)
        except UnresolvableWord as exc:
            raise Refusal(
                f"the `{program} -c` script `{operands[0].text}` cannot be "
                f"resolved: {exc}"
            ) from exc
        _nested(script, state, env, root, judged, depth)
        return
    if operands and "s" not in letters:
        return  # runs a script file, which is not judged here
    if not heredocs:
        raise Refusal(
            f"`{program}` reads its script from standard input here, so a "
            "`worktree add` it runs cannot be judged"
        )
    for heredoc in heredocs:
        try:
            body = expand_word(heredoc.as_word(), scope)
        except UnresolvableWord as exc:
            if _WORKTREE_ADD_TEXT.search(heredoc.body):
                raise Refusal(
                    f"the here-document `{program}` runs cannot be resolved: {exc}"
                ) from exc
            continue
        _nested(body, state, env, root, judged, depth)


def _run(
    words: list[Word],
    heredocs: list[HereDoc],
    state: _State,
    env: Mapping[str, str],
    root: Path | None,
    judged: list[str],
    depth: int,
) -> None:
    """Judge one simple command, updating ``state`` for assignments and ``cd``."""
    if not words or _apply_assignments(words, state, env):
        return
    try:
        _run_unwrapped(words, heredocs, state, env, root, judged, depth)
    finally:
        # `read X`, `for X in`, `unset X`, `export X=$(...)`: whatever this
        # command left in X, the environment no longer describes it.
        for name in shadowed_names([[w.text for w in words]]):
            state.variables[name] = None


def _run_unwrapped(
    words: list[Word],
    heredocs: list[HereDoc],
    state: _State,
    env: Mapping[str, str],
    root: Path | None,
    judged: list[str],
    depth: int,
) -> None:
    unwrapped = _unwrap(words)
    scope = _Scope(env, state.variables)
    if unwrapped.split is not None:
        try:
            script = expand_word(unwrapped.split, scope)
        except UnresolvableWord as exc:
            raise Refusal(
                f"an `env -S` command string cannot be resolved: {exc}"
            ) from exc
        child = _child(state, env, unwrapped.assignments)
        _nested(script, child, env, root, judged, depth)
        return
    local = state
    if unwrapped.chdirs:
        # `env -C` moves this command only, not the shell running it.
        local = _child(state, env)
        for operand in unwrapped.chdirs:
            try:
                local.cwd = _join(
                    local.cwd,
                    expand_word(operand, scope),
                    "`env -C` directory",
                    local.unknown,
                )
            except (UnresolvableWord, Refusal) as exc:
                local.cwd = None
                local.unknown = f"`env -C {operand.text}` cannot be resolved: {exc}"
    if not unwrapped.words or _apply_cd(unwrapped.words, local, env):
        return
    _dispatch(unwrapped, heredocs, local, env, root, judged, depth, via_wrapper=False)


def _dispatch(
    unwrapped: _Unwrapped,
    heredocs: list[HereDoc],
    state: _State,
    env: Mapping[str, str],
    root: Path | None,
    judged: list[str],
    depth: int,
    *,
    via_wrapper: bool,
) -> None:
    """Judge a git, shell or ``eval`` command, or look through an unknown wrapper."""
    words = unwrapped.words
    program = os.path.basename(words[0].text)
    if program in _SHELLS:
        child = _child(state, env, unwrapped.assignments)
        _run_shell(words, heredocs, child, env, root, judged, depth)
        return
    if program == "eval":
        scope = _Scope(env, state.variables)
        try:
            script = " ".join(expand_word(w, scope) for w in words[1:])
        except UnresolvableWord as exc:
            raise Refusal(f"an `eval` string cannot be resolved: {exc}") from exc
        target = (
            _child(state, env, unwrapped.assignments)
            if unwrapped.assignments
            else state
        )
        _nested(script, target, env, root, judged, depth)
        return
    if program != "git":
        inner = _embedded_command(words)
        if inner is not None and not via_wrapper:
            _dispatch(
                _Unwrapped(inner, [], None, []),
                heredocs,
                state,
                env,
                root,
                judged,
                depth,
                via_wrapper=True,
            )
        return
    invocation = _git_worktree_add(words, state, env, via_wrapper=via_wrapper)
    if invocation is None:
        return
    resolved = _judge_add(invocation, state, env, root)
    if resolved is not None:
        judged.append(resolved)


def _walk(
    command: str,
    state: _State,
    env: Mapping[str, str],
    root: Path | None,
    judged: list[str],
    depth: int,
) -> None:
    try:
        tokens = tokenize(command)
    except ShellSyntaxError as exc:
        raise Refusal(
            f"this command names `worktree add` but cannot be split into "
            f"words ({exc}), so its destination cannot be judged"
        ) from exc
    words: list[Word] = []
    heredocs: list[HereDoc] = []
    for token in tokens:
        if isinstance(token, Word):
            words.append(token)
            continue
        if isinstance(token, HereDoc):
            heredocs.append(token)
            continue
        _run(words, heredocs, state, env, root, judged, depth)
        words, heredocs = [], []
        if token.text == "(":
            state.stack.append((state.cwd, state.unknown))
        elif token.text == ")" and state.stack:
            state.cwd, state.unknown = state.stack.pop()
    _run(words, heredocs, state, env, root, judged, depth)


def evaluate(
    command: str, *, cwd: Path | None, root: Path | None, env: Mapping[str, str]
) -> Decision:
    """Judge every ``git worktree add`` destination in ``command``."""
    if not _WORKTREE_ADD_TEXT.search(command):
        return Decision(blocked=False)
    judged: list[str] = []
    state = _State(cwd=cwd, variables={}, unknown="the hook was given no cwd")
    try:
        _walk(command, state, env, root, judged, depth=0)
    except Refusal as exc:
        return Decision(blocked=True, reason=f"BLOCKED: {exc}. {DISABLE_HINT}")
    return Decision(blocked=False, judged=tuple(judged))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="OMN-19229 worktree add guard")
    parser.add_argument(
        "--root", required=True, help="canonical worktree root; empty when unresolvable"
    )
    parser.add_argument("--cwd", default=None, help="used when the payload has none")
    args = parser.parse_args(argv)

    def block(reason: str) -> int:
        print(json.dumps({"decision": "block", "reason": reason}))
        return 2

    try:
        payload = json.loads(sys.stdin.read())
    except (OSError, json.JSONDecodeError) as exc:
        return block(
            f"BLOCKED: the PreToolUse payload is not readable JSON ({exc}), so "
            f"a `git worktree add` in it cannot be judged. {DISABLE_HINT}"
        )
    tool_input = payload.get("tool_input") if isinstance(payload, dict) else None
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str) or not command:
        return 0
    cwd_raw = payload.get("cwd") or args.cwd
    cwd = Path(cwd_raw) if cwd_raw else None

    try:
        root = Path(args.root) if args.root else None
        decision = evaluate(command, cwd=cwd, root=root, env=os.environ)
    except Exception as exc:  # noqa: BLE001 - fail-closed boundary, deliberate
        return block(
            f"BLOCKED: the worktree guard could not evaluate this command ({exc}); "
            f"an unjudged `git worktree add` is refused. {DISABLE_HINT}"
        )
    if decision.blocked:
        return block(decision.reason)
    if decision.judged:
        print(json.dumps({"decision": "allow", "judged": list(decision.judged)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
