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
from collections.abc import Iterator, Mapping
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
_WRAPPERS = frozenset({"command", "exec", "nohup", "time", "builtin", "nice"})
_SHELLS = frozenset({"bash", "sh", "zsh", "dash"})
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


def _unwrap(words: list[Word]) -> _Unwrapped:
    """Drop leading assignments and wrapper programs such as ``env`` and ``nohup``."""
    result = list(words)
    chdirs: list[Word] = []
    split: Word | None = None
    while result:
        head = result[0]
        if head.assignment() is not None:
            result = result[1:]
            continue
        name = os.path.basename(head.text)
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
            if text in ("-C", "--chdir", "-S", "--split-string") and len(result) > 1:
                if text in ("-C", "--chdir"):
                    chdirs.append(result[1])
                else:
                    split = result[1]
                result = result[2:]
                continue
            if text.startswith("--chdir="):
                chdirs.append(_literal(text.partition("=")[2]))
            elif text.startswith("--split-string="):
                split = _literal(text.partition("=")[2])
            elif text.startswith("-C") and len(text) > 2:
                chdirs.append(_literal(text[2:]))
            elif text.startswith("-S") and len(text) > 2:
                split = _literal(text[2:])
            elif text in ("-u", "--unset"):
                result = result[1:]
            elif not text.startswith("-") and result[0].assignment() is None:
                break
            result = result[1:]
    return _Unwrapped(result, chdirs, split)


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


def _git_worktree_add(
    words: list[Word], state: _State, env: Mapping[str, str]
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
    return _Invocation(directory, unknown, list(args[idx + 2 :]))


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


def _destination(add_args: list[Word]) -> Word | None:
    """The ``<path>`` operand of ``git worktree add``, or None when git makes nothing."""
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
    target_word = _destination(invocation.add_args)
    if target_word is None:
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


def _embedded_git(words: list[Word]) -> list[Word] | None:
    """The ``git ... worktree add`` inside a command run by an unknown wrapper."""
    texts = [w.text for w in words]
    for idx, text in enumerate(texts):
        if os.path.basename(text) != "git":
            continue
        rest = texts[idx + 1 :]
        if any(rest[j : j + 2] == ["worktree", "add"] for j in range(len(rest))):
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


def _child(state: _State) -> _State:
    """The state a child shell starts in: this directory and these variables."""
    return _State(cwd=state.cwd, variables=dict(state.variables), unknown=state.unknown)


def _run_shell(
    words: list[Word],
    heredocs: list[HereDoc],
    state: _State,
    env: Mapping[str, str],
    root: Path | None,
    judged: list[str],
    depth: int,
) -> None:
    """Judge the script a ``bash``/``sh``/``zsh`` command runs."""
    program = os.path.basename(words[0].text)
    scope = _Scope(env, state.variables)
    for idx, word in enumerate(words[1:-1], start=1):
        text = word.text
        if text.startswith("-") and not text.startswith("--") and "c" in text[1:]:
            try:
                script = expand_word(words[idx + 1], scope)
            except UnresolvableWord as exc:
                raise Refusal(
                    f"the `{program} -c` script `{words[idx + 1].text}` cannot be "
                    f"resolved: {exc}"
                ) from exc
            _nested(script, _child(state), env, root, judged, depth)
            return
    if any(not w.text.startswith("-") for w in words[1:]):
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
        _nested(body, _child(state), env, root, judged, depth)


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
    unwrapped = _unwrap(words)
    stripped = unwrapped.words
    scope = _Scope(env, state.variables)
    if unwrapped.split is not None:
        try:
            script = expand_word(unwrapped.split, scope)
        except UnresolvableWord as exc:
            raise Refusal(
                f"an `env -S` command string cannot be resolved: {exc}"
            ) from exc
        _nested(script, _child(state), env, root, judged, depth)
        return
    local = state
    if unwrapped.chdirs:
        # `env -C` moves this command only, not the shell running it.
        local = _child(state)
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
    if not stripped or _apply_cd(stripped, local, env):
        return
    program = os.path.basename(stripped[0].text)
    if program in _SHELLS:
        _run_shell(stripped, heredocs, local, env, root, judged, depth)
        return
    if program == "eval":
        try:
            script = " ".join(expand_word(w, scope) for w in stripped[1:])
        except UnresolvableWord as exc:
            raise Refusal(f"an `eval` string cannot be resolved: {exc}") from exc
        _nested(script, local, env, root, judged, depth)
        return
    git_words = stripped if program == "git" else _embedded_git(stripped)
    if git_words is None:
        return
    invocation = _git_worktree_add(git_words, local, env)
    if invocation is None:
        return
    resolved = _judge_add(invocation, local, env, root)
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
