#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""PreToolUse guard: block work inside canonical omni_home repo clones.

omni_home is the canonical repository registry. The nested repo clones under it
(omni_home/omniclaude, omni_home/omnibase_core, ...) must stay on main and are
never worked in directly — all feature work happens in worktrees under
$OMNI_HOME/omni_worktrees/<ticket>/<repo>/.

This standalone guard (registered in ~/.claude/settings.json, independent of the
onex plugin hook stack) denies the two ways "work" leaks into a canonical clone:

  1. Edit / Write / NotebookEdit to a file inside a canonical clone.
  2. A git *mutation* run with the effective git directory inside a canonical
     clone — porcelain (checkout, switch, add, commit, merge, rebase, reset,
     cherry-pick, revert, stash, restore, rm, mv, am, apply, push) AND the
     plumbing that moves refs / index / worktree underneath porcelain
     (update-ref, symbolic-ref <write>, read-tree, checkout-index, update-index
     <non-refresh>, replace, filter-branch, branch <create/-f/-D/-m/-c/-u>,
     clean <non-dry-run>, fetch/pull with a refspec into a local branch, and
     worktree remove/move whose worktree path is inside the clone).
     `git update-ref refs/heads/dev origin/dev` in a canonical clone is the
     live 2026-08-23 incident this closes (OMN-16496).

It deliberately ALLOWS (per omni_home/CLAUDE.md "What you CAN do directly"):
  - reads / dev servers / docker / CLI / tests (any non-mutating Bash),
  - `git pull` / `git fetch` (the sanctioned sync path, e.g. pull-all.sh),
  - `git worktree add` (the sanctioned escape into a worktree) and
    `git worktree remove|move|prune` of worktrees that live OUTSIDE the clone
    (closeout hygiene),
  - read-only forms of the argument-aware verbs (branch listing, symbolic-ref
    read, clean -n, stash list|show, update-index --refresh, replace -l),
  - the ONE sanctioned convergence command,
    omniclaude/scripts/converge-canonical-clone.sh (preserve-then-reset; writes
    its own evidence directory and ledger row),
  - Edit/Write to omni_home's own top-level files (docs, CLAUDE.md, ...),
  - anything under $OMNI_HOME/omni_worktrees/ and anything outside $OMNI_HOME.

Path resolution expands `$VAR` / `${VAR}` / `${VAR:-default}` / `~` in `cd`,
`pushd` and `git -C` arguments using the hook's environment plus `VAR=value`
assignments seen earlier in the same command. A path that is still not
resolvable (unset variable, `$(...)`) is an UNKNOWN location: it is logged and
never glued onto cwd — doing that produced false denials of legitimate
worktree commands (guard log lines 155/181/206).

Source of truth: omniclaude/scripts/user-hooks/canonical-clone-guard.py,
installed to ~/.claude/hooks/ by omniclaude/scripts/install-canonical-clone-guard.sh.
Do not edit the installed copy in place.

Contract (current Claude Code): to DENY, print
  {"hookSpecificOutput": {"hookEventName": "PreToolUse",
   "permissionDecision": "deny", "permissionDecisionReason": "..."}}
to stdout and exit 0. To ALLOW, exit 0 with no stdout.

Fails OPEN on any unexpected error (never freeze the session); the deny path
only fires on a clear positive match.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shlex
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import NoReturn

CONVERGE_SCRIPT = "converge-canonical-clone.sh"

# git subcommands that always create local divergence in a clone. Read-only
# subcommands (status, log, diff, show, fetch, pull, rev-parse, remote, config,
# clone, worktree list/add/prune, ...) are intentionally absent so the
# sanctioned operations pass. Verbs with both read and write forms are
# classified by their arguments in _ARG_AWARE below.
_GIT_MUTATIONS = {
    "commit",
    "add",
    "checkout",  # always mutates working tree or HEAD
    "switch",
    "merge",
    "rebase",
    "cherry-pick",
    "revert",
    "reset",
    "restore",
    "rm",
    "mv",
    "am",
    "apply",
    "push",
    # plumbing: moves refs / index / worktree without going through porcelain
    "update-ref",
    "read-tree",
    "checkout-index",
    "filter-branch",
}

# git global options that take a value, so we can skip past them to the subcommand.
_GIT_OPTS_WITH_VALUE = {
    "-C",
    "-c",
    "--git-dir",
    "--work-tree",
    "--namespace",
    "--exec-path",
}

_SEGMENT_SPLIT_RE = re.compile(r"&&|\|\||;|\n|\|")
_REDIRECT_RE = re.compile(r"^(\d*>{1,2}|<|&>|\|)")
_ASSIGN_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", re.DOTALL)
_VAR_RE = re.compile(
    r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::?([-?+=])([^}]*))?\}|\$([A-Za-z_][A-Za-z0-9_]*)"
)
_REFSPEC_URL_RE = re.compile(r"://|^[\w.+-]+@[\w.-]+:")
_SAFE_REFSPEC_DST = ("refs/remotes/", "refs/tags/", "refs/notes/")

_BRANCH_MUTATING_LONG = {
    "--force",
    "--delete",
    "--move",
    "--copy",
    "--set-upstream-to",
    "--unset-upstream",
    "--edit-description",
    "--create-reflog",
}
_BRANCH_LISTING_LONG = {
    "--list",
    "--show-current",
    "--contains",
    "--no-contains",
    "--merged",
    "--no-merged",
    "--points-at",
    "--all",
    "--remotes",
    "--verbose",
    "--format",
    "--sort",
    "--column",
    "--no-column",
    "--color",
    "--no-color",
    "--abbrev",
    "--no-abbrev",
    "--ignore-case",
}
_BRANCH_MUTATING_SHORT = set("fdDmMcCu")
_BRANCH_LISTING_SHORT = set("alrvi")
_UPDATE_INDEX_REFRESH_ONLY = {
    "--refresh",
    "--really-refresh",
    "-q",
    "--quiet",
    "--unmerged",
    "--ignore-missing",
    "--ignore-submodules",
    "--verbose",
}


def _log(msg: str) -> None:
    # logging must never break the guard: any failure here is swallowed
    with contextlib.suppress(Exception):
        log_dir = Path.home() / ".claude" / "hooks" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        with (log_dir / "canonical-clone-guard.log").open("a") as fh:
            fh.write(msg.rstrip("\n") + "\n")


def _deny(reason: str) -> NoReturn:
    print(  # noqa: T201 — stdout IS the hook protocol
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            }
        )
    )
    sys.exit(0)


def _allow() -> NoReturn:
    sys.exit(0)


# --- path resolution ------------------------------------------------------


def _expand(text: str, env: dict[str, str]) -> str | None:
    """Expand shell parameter references in *text*; None when unresolvable.

    Handles ``$VAR``, ``${VAR}``, ``${VAR:-word}``/``${VAR-word}``/``${VAR:=word}``,
    ``${VAR:?msg}`` and ``${VAR:+word}``. Anything left that still looks like a
    parameter or command substitution (``$(...)``, backticks, an unset variable)
    makes the whole value unresolvable — the guard must not guess a location.
    """
    unresolved = False

    def substitute(match: re.Match[str]) -> str:
        nonlocal unresolved
        name = match.group(1) or match.group(4)
        op, word = match.group(2), match.group(3)
        value = env.get(name)
        if op == "+":
            return _expand(word, env) or "" if value else ""
        if value:
            return value
        if op in ("-", "="):
            replacement = _expand(word, env)
            if replacement is None:
                unresolved = True
                return ""
            return replacement
        if value is None or op == "?":
            unresolved = True
            return ""
        return value

    expanded = _VAR_RE.sub(substitute, text)
    if unresolved or "$" in expanded or "`" in expanded:
        return None
    return expanded


def _resolve_shell_path(raw: str, base: str | None, env: dict[str, str]) -> str | None:
    """Resolve a cd / -C / file argument to an absolute path; None if unknowable."""
    text = raw.strip().strip("\"'")
    expanded = _expand(text, env)
    if not expanded:
        return None
    expanded = os.path.expanduser(expanded)
    if expanded.startswith("~"):
        return None
    if not Path(expanded).is_absolute():
        if base is None:
            return None
        expanded = os.path.join(base, expanded)
    return os.path.normpath(os.path.abspath(expanded))


def _path_in_canonical_clone(abspath: str, omni_home: str) -> str | None:
    """Return the canonical-clone repo name if *abspath* is inside one, else None.

    A canonical clone is a direct child directory of $OMNI_HOME that is itself a
    git repo (has a .git entry), excluding the omni_worktrees work-root and
    omni_home's own top-level files.
    """
    omni_home = os.path.normpath(os.path.abspath(omni_home))
    try:
        rel = os.path.relpath(abspath, omni_home)
    except ValueError:
        return None  # different drive, etc.
    parts = Path(rel).parts
    first = parts[0] if parts else "."
    if first in ("", ".", ".."):
        return None  # omni_home root file or outside the tree
    if first == "omni_worktrees":
        return None  # sanctioned work root
    if os.path.exists(os.path.join(omni_home, first, ".git")):
        return first
    return None


# --- argument-aware git verb classification --------------------------------


def _is_operand(tok: str) -> bool:
    return not tok.startswith("-") and not _REDIRECT_RE.match(tok) and tok != "&"


def _git_args(tokens: list[str], start: int) -> list[str]:
    args: list[str] = []
    for tok in tokens[start:]:
        if tok.startswith("|"):
            break
        args.append(tok)
    return args


def _branch_mutates(args: list[str]) -> bool:
    listing = False
    for tok in args:
        if tok.startswith("--"):
            name = tok.split("=", 1)[0]
            if name in _BRANCH_MUTATING_LONG:
                return True
            if name in _BRANCH_LISTING_LONG:
                listing = True
        elif tok.startswith("-") and len(tok) > 1:
            letters = set(tok[1:])
            if letters & _BRANCH_MUTATING_SHORT:
                return True
            if letters & _BRANCH_LISTING_SHORT:
                listing = True
    return any(_is_operand(t) for t in args) and not listing


def _symbolic_ref_mutates(args: list[str]) -> bool:
    if any(t in ("-d", "--delete") for t in args):
        return True
    return sum(1 for t in args if _is_operand(t)) >= 2


def _clean_mutates(args: list[str]) -> bool:
    for tok in args:
        if tok == "--dry-run":
            return False
        if tok.startswith("-") and not tok.startswith("--") and "n" in tok[1:]:
            return False
    return True


def _fetch_or_pull_mutates(args: list[str]) -> bool:
    """True when a refspec writes into a local branch (``src:dst`` with a
    destination outside refs/remotes|tags|notes) — that is ``update-ref`` by
    another name."""
    for tok in args:
        if not _is_operand(tok) or _REFSPEC_URL_RE.search(tok):
            continue
        _src, sep, dst = tok.lstrip("+").partition(":")
        if not sep or not dst or dst.startswith(_SAFE_REFSPEC_DST):
            continue
        return True
    return False


def _update_index_mutates(args: list[str]) -> bool:
    return any(t.split("=", 1)[0] not in _UPDATE_INDEX_REFRESH_ONLY for t in args)


def _replace_mutates(args: list[str]) -> bool:
    if any(t in ("-l", "--list") for t in args):
        return False
    if any(
        t in ("-d", "--delete", "--edit", "--graft", "--convert-graft-file")
        for t in args
    ):
        return True
    return any(_is_operand(t) for t in args)


def _stash_mutates(args: list[str]) -> bool:
    operands = [t for t in args if _is_operand(t)]
    return not (operands and operands[0] in ("list", "show"))


_ARG_AWARE: dict[str, Callable[[list[str]], bool]] = {
    "branch": _branch_mutates,
    "symbolic-ref": _symbolic_ref_mutates,
    "clean": _clean_mutates,
    "fetch": _fetch_or_pull_mutates,
    "pull": _fetch_or_pull_mutates,
    "update-index": _update_index_mutates,
    "replace": _replace_mutates,
    "stash": _stash_mutates,
}


def _worktree_operation(args: list[str]) -> tuple[str, list[str]]:
    """Return (op, worktree-path args) for ``worktree remove|move``; ('', []) otherwise."""
    operands = [t for t in args if _is_operand(t)]
    if not operands:
        return "", []
    if operands[0] == "remove":
        return "remove", operands[1:2]
    if operands[0] == "move":
        return "move", operands[1:3]
    return "", []


# --- Bash command walk ------------------------------------------------------


class _Shell:
    """Tracks the effective directory across a compound Bash command."""

    def __init__(self, cwd: str, env: dict[str, str]) -> None:
        self.cwd: str | None = cwd
        self.env = env
        self.stack: list[str | None] = []

    def assign(self, tok: str) -> bool:
        match = _ASSIGN_RE.match(tok)
        if not match:
            return False
        name, value = match.group(1), match.group(2)
        expanded = _expand(value.strip("\"'"), self.env)
        if expanded is None:
            self.env.pop(name, None)
        else:
            self.env[name] = expanded
        return True

    def change_dir(self, tokens: list[str]) -> None:
        head = tokens[0]
        if head == "popd":
            self.cwd = self.stack.pop() if self.stack else self.cwd
            return
        if head == "pushd":
            self.stack.append(self.cwd)
        args = [t for t in tokens[1:] if not t.startswith("-")]
        if not args:
            self.cwd = self.env.get("HOME") or None
            return
        if tokens[1] == "-":
            self.cwd = None
            return
        resolved = _resolve_shell_path(args[0], self.cwd, self.env)
        if resolved is None:
            _log(f"UNRESOLVED {head} target {args[0]!r}; treating location as unknown")
        self.cwd = resolved


def _segment_tokens(segment: str) -> list[str]:
    try:
        tokens = shlex.split(segment)
    except ValueError:
        tokens = segment.split()
    while tokens and tokens[0] in ("(", "{", "!"):
        tokens.pop(0)
    if tokens and tokens[0].startswith("("):
        tokens[0] = tokens[0][1:]
        if not tokens[0]:
            tokens.pop(0)
    while tokens and tokens[-1] in (")", "}"):
        tokens.pop()
    if tokens and tokens[-1].endswith(")") and not tokens[-1].startswith("$("):
        tokens[-1] = tokens[-1].rstrip(")")
        if not tokens[-1]:
            tokens.pop()
    return tokens


def _iter_bash_checks(
    command: str, cwd: str, env: dict[str, str]
) -> Iterator[tuple[str, str | None]]:
    """Yield (label, path) for every git mutation in *command*.

    *path* is the directory (or, for ``worktree remove|move``, the worktree
    path) the mutation acts on — None when it could not be resolved, in which
    case the caller logs and skips it (fail-open, never a guessed location).
    """
    shell = _Shell(cwd, env)
    for raw_segment in _SEGMENT_SPLIT_RE.split(command):
        segment = raw_segment.strip()
        if not segment:
            continue
        tokens = _segment_tokens(segment)
        while tokens and shell.assign(tokens[0]):
            tokens.pop(0)
        if not tokens:
            continue
        if tokens[0] == "export":
            for tok in tokens[1:]:
                shell.assign(tok)
            continue
        if tokens[0] in ("cd", "pushd", "popd"):
            shell.change_dir(tokens)
            continue
        if any(os.path.basename(t) == CONVERGE_SCRIPT for t in tokens):
            _log(f"ALLOW sanctioned {CONVERGE_SCRIPT} invocation: {segment[:200]}")
            continue
        if "git" not in tokens:
            continue
        yield from _git_checks(tokens, shell)


def _git_checks(tokens: list[str], shell: _Shell) -> Iterator[tuple[str, str | None]]:
    i = tokens.index("git") + 1
    effective = shell.cwd
    while i < len(tokens):
        tok = tokens[i]
        if tok in _GIT_OPTS_WITH_VALUE:
            if tok == "-C" and i + 1 < len(tokens):
                effective = _resolve_shell_path(tokens[i + 1], shell.cwd, shell.env)
                if effective is None:
                    _log(
                        f"UNRESOLVED git -C target {tokens[i + 1]!r}; treating location as unknown"
                    )
            i += 2
            continue
        if tok.startswith("-"):
            i += 1
            continue
        break
    if i >= len(tokens):
        return
    subcommand = tokens[i]
    args = _git_args(tokens, i + 1)
    if subcommand == "worktree":
        op, paths = _worktree_operation(args)
        for raw in paths:
            yield f"git worktree {op}", _resolve_shell_path(raw, effective, shell.env)
        return
    classifier = _ARG_AWARE.get(subcommand)
    if subcommand in _GIT_MUTATIONS or (classifier is not None and classifier(args)):
        yield f"git {subcommand}", effective


# --- entry point ------------------------------------------------------------


def main() -> None:
    try:
        raw = sys.stdin.read()
    except Exception:  # noqa: BLE001 — fail open
        _allow()
    if not raw.strip():
        _allow()

    try:
        data = json.loads(raw)
    except Exception:  # noqa: BLE001 — fail open
        _allow()

    omni_home = os.environ.get("OMNI_HOME")
    if not omni_home:
        _allow()  # guard is omni_home-scoped; out of scope without it

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {}) or {}
    cwd = data.get("cwd") or os.getcwd()
    env = dict(os.environ)

    worktree_hint = (
        "Create a worktree first:\n"
        '  git -C "$OMNI_HOME/<repo>" worktree add '
        '"$OMNI_HOME/omni_worktrees/<ticket>/<repo>" -b <branch>\n'
        "then do all edits/commits there. omni_home/<repo> is a canonical clone "
        "that must stay on main (omni_home/CLAUDE.md rule #9)."
    )
    converge_hint = (
        "To converge a DIRTY canonical clone back to its upstream, use the ONE "
        "sanctioned command (preserves the full diff + untracked files under "
        "$OMNI_HOME/.onex_state/canonical-clone-converge/ and writes a ledger row):\n"
        '  bash "$OMNI_HOME/omniclaude/scripts/converge-canonical-clone.sh" <repo> --execute\n'
        "Never reach for plumbing (update-ref, read-tree, checkout-index) or shell "
        "writes to get around this guard — that is how the 2026-08-23 omnimarket "
        "incident happened."
    )

    # --- Edit / Write / NotebookEdit -------------------------------------
    if tool_name in ("Edit", "Write", "NotebookEdit", "MultiEdit"):
        target = tool_input.get("file_path") or tool_input.get("notebook_path")
        if not target:
            _allow()
        abspath = _resolve_shell_path(str(target), cwd, env)
        if abspath is None:
            _log(f"UNRESOLVED {tool_name} target {target!r}; allowing")
            _allow()
        repo = _path_in_canonical_clone(abspath, omni_home)
        if repo:
            _log(f"DENY {tool_name} -> {abspath} (canonical clone: {repo})")
            _deny(
                f"BLOCKED: '{abspath}' is inside the canonical clone "
                f"'{repo}' under omni_home. Never edit canonical clones directly.\n\n"
                + worktree_hint
            )
        _allow()

    # --- Bash git mutations ----------------------------------------------
    if tool_name == "Bash":
        command = tool_input.get("command", "") or ""
        if "git" not in command:
            _allow()
        try:
            for label, path in _iter_bash_checks(command, cwd, env):
                if path is None:
                    _log(
                        f"UNRESOLVED location for '{label}'; not matched against canonical clones"
                    )
                    continue
                repo = _path_in_canonical_clone(path, omni_home)
                if repo:
                    _log(f"DENY Bash '{label}' in {path} (canonical clone: {repo})")
                    _deny(
                        f"BLOCKED: '{label}' targets the canonical clone "
                        f"'{repo}' ({path}). Canonical clones stay on main — "
                        f"no branches, staging, commits, or ref/index/worktree "
                        f"plumbing there.\n\n"
                        f"Allowed in a canonical clone: reads, tests, dev servers, "
                        f"git pull/fetch (sync), git worktree add, git worktree "
                        f"remove of a worktree under omni_worktrees/.\n\n"
                        + converge_hint
                        + "\n\n"
                        + worktree_hint
                    )
        except Exception as exc:  # noqa: BLE001 — never block on a parser bug
            _log(f"ERROR parsing Bash command, failing open: {exc!r}")
            _allow()
        _allow()

    _allow()


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 — absolute fail-open backstop
        _log(f"FATAL, failing open: {exc!r}")
        sys.exit(0)
