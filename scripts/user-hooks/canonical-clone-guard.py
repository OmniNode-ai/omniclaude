#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""PreToolUse guard: block work inside canonical omni_home repo clones.

omni_home is the canonical repository registry. The nested repo clones under it
(omni_home/omniclaude, omni_home/omnibase_core, ...) must stay on main and are
never worked in directly — all feature work happens in worktrees under
$OMNI_HOME/omni_worktrees/<ticket>/<repo>/.

This standalone guard (registered in ~/.claude/settings.json, independent of the
onex plugin hook stack) denies the two ways "work" leaks into a canonical clone
(1-2 below), plus a third, orthogonal class: commands that disable the local
gate chain itself, anywhere (3, OMN-16725).

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
  3. A gate escape, denied REGARDLESS of location (OMN-16725): a
     `core.hooksPath` override (`git -c core.hooksPath=`, `--config-env=`, or a
     persisted `git config core.hooksPath <value>`), `--no-verify` on any git
     subcommand, `-n` on `git commit` (which IS --no-verify there), a `[skip-`
     bypass token in a commit message, and the pre-push escape variables
     `PREPUSH_FULL_SUITE=`, `PREPUSH_ALLOW_*`, `PREPUSH_LOAD_THRESHOLD=`,
     `ENABLE_SMART_TESTS=off`. The hooksPath override is the live
     2026-08-25/27 incident this closes: in a worktree `.git` is a FILE, the
     override resolves to nothing, git finds zero hooks, and the commit
     succeeds silently unverified. Every deny message names the failure mode
     AND the mechanical alternative, because a bare prohibition gets worked
     around (memory feedback_workers_disregard_negative_directives).

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
Do not edit the installed copy in place. Decisions are logged to
$ONEX_STATE_DIR/hooks/canonical-clone-guard.log (default
$OMNI_HOME/.onex_state/hooks/canonical-clone-guard.log), never under ~/.claude/.

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


def _log_path() -> Path | None:
    """Guard log lives with the other hook state, never under ~/.claude/."""
    state_dir = os.environ.get("ONEX_STATE_DIR")
    if not state_dir:
        omni_home = os.environ.get("OMNI_HOME")
        if not omni_home:
            return None
        state_dir = os.path.join(omni_home, ".onex_state")
    return Path(state_dir) / "hooks" / "canonical-clone-guard.log"


def _log(msg: str) -> None:
    # logging must never break the guard: any failure here is swallowed
    with contextlib.suppress(Exception):
        path = _log_path()
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as fh:
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
    git repo (has a .git entry), excluding any omni_worktrees work-root and
    omni_home's own top-level files.

    The ``omni_worktrees`` test covers the segment WHEREVER it appears, not just
    directly under $OMNI_HOME (OMN-16826). A relative-path ``git worktree add``
    run from inside a canonical clone lands the worktree at
    ``<clone>/omni_worktrees/<ticket>/<repo>``; when only the first segment was
    tested, the canonical-clone prefix match won there and the resulting
    registration was one that NO sanctioned command could remove --
    ``worktree remove`` was refused as a canonical-clone mutation while
    ``worktree prune`` skips a registration whose directory still exists. The
    stray is a worktree, not the clone's own checkout, so it is out of scope for
    this guard at any depth.
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
    if "omni_worktrees" in parts:
        # Sanctioned work root -- at ANY depth, so a clone-internal stray
        # (<clone>/omni_worktrees/...) stays removable. Ordered before the
        # canonical-clone prefix check below, which would otherwise claim it.
        return None
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
        if len(tokens) > 1 and tokens[1] == "-":
            _log(f"UNRESOLVED {head} - (OLDPWD unknown); treating location as unknown")
            self.cwd = None
            return
        args = [t for t in tokens[1:] if not t.startswith("-")]
        if not args:
            self.cwd = self.env.get("HOME") or None
            return
        resolved = _resolve_shell_path(args[0], self.cwd, self.env)
        if resolved is None:
            _log(f"UNRESOLVED {head} target {args[0]!r}; treating location as unknown")
        self.cwd = resolved


_COMMAND_WRAPPERS = {"bash", "sh", "zsh", "env", "nohup", "time", "command", "exec"}


def _invokes_converge_script(tokens: list[str]) -> bool:
    """True only when the sanctioned script is the command word itself.

    Matching any token would let ``git add converge-canonical-clone.sh`` or
    ``git commit -m converge-canonical-clone.sh`` launder a mutation.
    """
    i = 0
    while i < len(tokens) and tokens[i] in _COMMAND_WRAPPERS:
        i += 1
    return i < len(tokens) and os.path.basename(tokens[i]) == CONVERGE_SCRIPT


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
        if _invokes_converge_script(tokens):
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


# --- bypass-pattern deny list (OMN-16725) -----------------------------------
#
# A second, INDEPENDENT class of denial: commands that disable the local gate
# chain itself. Orthogonal to the canonical-clone check above — these patterns
# are denied wherever they run, inside a canonical clone or not, because the
# failure mode (a commit or push that silently skipped every hook) is the same
# everywhere.
#
# PRECISION OVER RECALL. Every matcher works on git-command STRUCTURE (command
# word, global options, subcommand, that subcommand's own argument grammar),
# never on a raw substring of the command line, and the scan skips heredoc
# bodies and text-emitting command words so that WRITING or SEARCHING
# documentation that quotes a forbidden flag is never mistaken for RUNNING it.
#
# Deliberate non-matches (verified against `git <sub> -h`, 2026-08-27):
#   git push -n / --dry-run   -n on push is --dry-run, NOT --no-verify. Allowed.
#   git commit -n             -n on commit IS --no-verify. Denied.
#   git commit -m"no-op"      value attached to a value-taking short option is
#                             the message, not a flag cluster. Allowed.
#   grep --no-verify ...      command word is not git. Allowed.
#   git config --get core.hooksPath / --unset core.hooksPath   reads and the
#                             restore-default form. Allowed.
#
# KNOWN BLIND SPOTS (honest limits, stated on OMN-16725 rather than papered
# over). The matcher cannot see inside:
#   - a quoted sub-shell string: `bash -c "git commit --no-verify"` tokenises to
#     one opaque argument, so no git structure is visible;
#   - a variable or command substitution: `$FLAG`, `$(printf -- --no-verify)`;
#   - a script FILE that itself runs the bypass — only the invocation is seen;
#   - `echo ... | bash` laundering, since the pipe splits the segments.
# These are the same limits the canonical-clone scan above already has. This
# guard raises the cost of an accidental bypass; it is not an adversarial
# sandbox against a caller deliberately hiding one.

_HOOKSPATH_KEY = "core.hookspath"  # git config key lookup is case-insensitive
_SKIP_MARKER_PREFIX = "[skip-"
_SMART_TESTS_OFF = {"off", "0", "false", "no", "n", "disabled"}

# Command words whose job is to EMIT or SEARCH text. A git bypass flag among
# their arguments is documentation or a search pattern, not an execution
# attempt, so the bypass scan skips the whole segment. (Doc/test-authoring
# escape, per the OMN-16725 precision requirement.)
_TEXT_EMITTING = {
    "echo",
    "printf",
    "cat",
    "tee",
    "grep",
    "egrep",
    "fgrep",
    "rg",
    "ag",
    "ack",
    "sed",
    "awk",
    "head",
    "tail",
    "less",
    "more",
    "diff",
    "comm",
    "sort",
    "uniq",
    "wc",
    "jq",
    "yq",
    "column",
    "fold",
    "pbcopy",
}

# `git config` forms that only READ (or restore the default) — never a bypass.
_CONFIG_READ_FLAGS = {
    "--get",
    "--get-all",
    "--get-regexp",
    "--get-urlmatch",
    "--list",
    "-l",
    "--unset",
    "--unset-all",
}

# Short options of `git commit` that consume a value, so the remainder of a
# cluster (or the next token) is that value and must not be read as flags.
_COMMIT_VALUE_SHORTS = set("mFcCt")

_HEREDOC_RE = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")

_FIX_THE_HOOK = (
    "DO THIS INSTEAD: run the plain command and let the hooks run. If a hook "
    "FAILS, that is the gate working — fix the cause it reports. If hooks are "
    "genuinely missing or broken, repair them and say so; never route around "
    "them (omni_home/CLAUDE.md rule #10: a local gate is never bypassed as a "
    "convenience)."
)

_DENY_HOOKSPATH = (
    "BLOCKED: this command overrides `core.hooksPath`, which disables the hook "
    "chain for the command it is attached to.\n\n"
    "FAILURE MODE: inside a git worktree `.git` is a FILE, not a directory. An "
    "overridden hooksPath resolves to nothing, git finds ZERO hooks, and the "
    "commit or push succeeds with no warning and no trace in the log. It is a "
    "silent `--no-verify` that leaves no evidence it ever happened — which is "
    "strictly worse than `--no-verify`, because a reviewer cannot tell from the "
    "history that verification was skipped. This was hit twice in the "
    "2026-08-25/27 window and both recoveries were luck, not mechanism "
    "(OMN-16725, memory reference_worktree_hookspath_override_is_silent_no_verify).\n\n"
    + _FIX_THE_HOOK
    + "\nTo see where a worktree's hooks actually resolve:\n"
    "  git -C <worktree> rev-parse --git-path hooks"
)

_DENY_HOOKSPATH_CONFIG = (
    "BLOCKED: `git config core.hooksPath <value>` PERSISTS a hook-chain "
    "override into the repository config — every later commit and push from "
    "this checkout runs unverified, not just this one command.\n\n"
    "FAILURE MODE: identical to the `-c core.hooksPath=` form, but durable and "
    "invisible to anyone who did not run the config command. In a worktree the "
    "overridden path resolves to nothing, git finds ZERO hooks, and everything "
    "afterwards commits silently unverified (OMN-16725).\n\n"
    + _FIX_THE_HOOK
    + "\nReading the value is allowed:  git config --get core.hooksPath\n"
    "Restoring the default is allowed: git config --unset core.hooksPath"
)

_DENY_NO_VERIFY = (
    "BLOCKED: `git {sub} --no-verify` bypasses the local hook chain.\n\n"
    "FAILURE MODE: pre-commit and pre-push are the ONLY local enforcement of "
    "lint, format, mypy, the governed impacted-test selector, and the "
    "canonical-clone and skip-token guards. Skipping them does not remove the "
    "problem — it relocates it to CI as a red PR (slower and more expensive to "
    "fix), or lands unverified code that the next lane inherits.\n\n" + _FIX_THE_HOOK
)

_DENY_COMMIT_DASH_N = (
    "BLOCKED: `-n` on `git commit` IS `--no-verify` (see `git commit -h`: "
    "'-n, --no-verify  bypass pre-commit and commit-msg hooks'). It is not a "
    "dry-run.\n\n"
    "FAILURE MODE: pre-commit and commit-msg are the only local enforcement of "
    "lint, format, mypy, and the canonical-clone and skip-token guards. A "
    "commit made with `-n` looks identical in the history to a verified one, so "
    "nothing downstream can tell the difference.\n\n"
    + _FIX_THE_HOOK
    + "\nIf you wanted a dry run: `git commit --dry-run` (commit has no short "
    "form for it). Note `git push -n` IS `--dry-run` and is allowed."
)

_DENY_SKIP_MARKER = (
    "BLOCKED: the commit message contains a `{marker}` bypass marker.\n\n"
    "FAILURE MODE: `[skip-deploy-gate: ...]` and friends are rejected by the "
    "pre-commit hook and by a required GitHub status check, so this commit "
    "cannot merge — it only costs a round trip. A self-written justification is "
    "self-judgement, not evidence (omni_home/CLAUDE.md rule #10; two workers "
    "did exactly this on 2026-04-25, which is why the gate is mechanical now).\n\n"
    "DO THIS INSTEAD: fix what the gate is complaining about — add the missing "
    "dod_evidence, or narrow an over-broad matcher. The ONE sanctioned escape "
    "is a staged-content comment carrying a real user-issued approval handle:\n"
    "  # skip-token-allowed: <user-approval-receipt-id>\n"
    "That escape lives in the STAGED CONTENT, not in the commit message, so it "
    "does not require the token you are being blocked for here."
)

_DENY_PREPUSH_FULL_SUITE = (
    "BLOCKED: `PREPUSH_FULL_SUITE=` hand-forces the full local suite, "
    "overriding the governed impacted-test selector.\n\n"
    "FAILURE MODE: the selector (scripts/hooks/prepush_smart_tests.sh) is "
    "already FAIL-CLOSED — it escalates to the full suite by itself whenever "
    "narrowing cannot be proven safe. Forcing it by hand does not add safety; "
    "it burns hours of runner time and, worse, destroys the signal, because an "
    "escalation the selector ORDERED becomes indistinguishable from one a "
    "worker chose (omni_home/CLAUDE.md rule #4).\n\n"
    "DO THIS INSTEAD: run plain `git push` and let the selector decide. If you "
    "believe it narrowed unsafely, that is a defect in the selector — capture "
    "the case and fix the selector, do not override it per-push."
)

_DENY_PREPUSH_LOAD_THRESHOLD = (
    "BLOCKED: `PREPUSH_LOAD_THRESHOLD=` overrides the pre-push host-load gate.\n\n"
    "FAILURE MODE: that threshold is what stops a heavy suite from being "
    "launched onto an already-saturated host. Raising it does not make the host "
    "faster — it produces a run whose timings and flake profile are worthless "
    "as evidence, on the machine that is also carrying the CI runner fleet.\n\n"
    "DO THIS INSTEAD: wait for load to drop, or run on a fit host. If capacity "
    "is genuinely degraded and the work cannot wait, use the hook's own "
    "single-use degraded-capacity override grant, which records that the "
    "evidence is weaker — do not silently move the threshold."
)

_DENY_PREPUSH_ALLOW = (
    "BLOCKED: `{name}` is a `PREPUSH_ALLOW_*` escape variable.\n\n"
    "FAILURE MODE: the pre-push hook REJECTS any `PREPUSH_ALLOW_*` variable "
    "found in its environment at entry (OMN-16480), precisely so that a new "
    "`PREPUSH_ALLOW_SOMETHING` cannot quietly reopen the class. Setting it will "
    "not work; it will fail closed and cost you a round trip. Worse, an "
    "exported one is INHERITED by every child process, so it can silently widen "
    "far past the command you meant it for.\n\n"
    "DO THIS INSTEAD: run plain `git push`. If the gate blocks something it "
    "should not, fix the gate's condition and land that fix — an allow-variable "
    "is not an approval."
)

_DENY_SMART_TESTS_OFF = (
    "BLOCKED: disabling `ENABLE_SMART_TESTS` overrides the governed "
    "impacted-test selector and forces the full suite.\n\n"
    "FAILURE MODE: same as PREPUSH_FULL_SUITE — the selector is already "
    "fail-closed and escalates on its own when narrowing cannot be proven safe. "
    "Turning it off does not add safety, it burns runner hours and erases the "
    "distinction between an escalation the selector ordered and one a worker "
    "chose (omni_home/CLAUDE.md rule #4).\n\n"
    "DO THIS INSTEAD: run plain `git push`. Setting `ENABLE_SMART_TESTS` to an "
    "ENABLING value is not blocked; only the off/0/false forms are."
)


def _strip_heredocs(command: str) -> str:
    """Drop heredoc BODIES, keeping the line that opens them.

    ``cat > runbook.md <<'EOF' ... EOF`` writing a document that quotes
    ``git commit --no-verify`` is authoring text, not an execution attempt.
    The opening line is retained so the command that opens the heredoc is
    still scanned normally.
    """
    kept: list[str] = []
    delimiter: str | None = None
    for line in command.split("\n"):
        if delimiter is not None:
            if line.strip() == delimiter:
                delimiter = None
            continue
        kept.append(line)
        match = _HEREDOC_RE.search(line)
        if match:
            delimiter = match.group(2)
    return "\n".join(kept)


def _env_bypass_reason(name: str, value: str) -> str | None:
    """Deny reason for a gate-escape environment assignment, else None.

    Only ASSIGNMENTS match. Reading one (``echo $PREPUSH_FULL_SUITE``,
    ``grep PREPUSH_ALLOW_ file``) is not an escape and is never denied.
    """
    text = value.strip().strip("\"'")
    if name == "PREPUSH_FULL_SUITE" and text:
        # An EMPTY value is the safe direction (the hook tests -n), so allow it.
        return _DENY_PREPUSH_FULL_SUITE
    if name.startswith("PREPUSH_ALLOW_"):
        return _DENY_PREPUSH_ALLOW.format(name=name)
    if name == "PREPUSH_LOAD_THRESHOLD" and text:
        return _DENY_PREPUSH_LOAD_THRESHOLD
    if name == "ENABLE_SMART_TESTS" and text.lower() in _SMART_TESTS_OFF:
        return _DENY_SMART_TESTS_OFF
    return None


def _config_writes_hookspath(args: list[str]) -> bool:
    """True only for ``git config core.hooksPath <value>`` (a WRITE)."""
    if any(tok.split("=", 1)[0] in _CONFIG_READ_FLAGS for tok in args):
        return False
    operands = [tok for tok in args if _is_operand(tok)]
    return len(operands) >= 2 and operands[0].strip().lower() == _HOOKSPATH_KEY


def _commit_short_flags(args: list[str]) -> Iterator[str]:
    """Yield the short-option letters of ``git commit``, value-aware.

    A cluster stops at the first value-taking letter, because everything after
    it is that option's attached value — so ``-m"no-op"`` (shlex: ``-mno-op``)
    never leaks an 'n' into the flag set.
    """
    skip_next = False
    for tok in args:
        if skip_next:
            skip_next = False
            continue
        if tok == "--":
            return
        if not tok.startswith("-") or tok.startswith("--") or len(tok) < 2:
            continue
        letters = tok[1:]
        for idx, char in enumerate(letters):
            if char in _COMMIT_VALUE_SHORTS:
                skip_next = idx == len(letters) - 1
                break
            yield char


def _commit_messages(args: list[str]) -> Iterator[str]:
    """Yield the ``-m`` / ``--message`` values of a ``git commit``."""
    expect = False
    for tok in args:
        if expect:
            yield tok
            expect = False
            continue
        if tok == "--":
            return
        if tok.startswith("--message="):
            yield tok.split("=", 1)[1]
            continue
        if tok == "--message":
            expect = True
            continue
        if not tok.startswith("-") or tok.startswith("--") or len(tok) < 2:
            continue
        letters = tok[1:]
        for idx, char in enumerate(letters):
            if char == "m":
                rest = letters[idx + 1 :]
                if rest:
                    yield rest
                else:
                    expect = True
                break
            if char in _COMMIT_VALUE_SHORTS:
                break


def _git_bypass_reason(tokens: list[str]) -> str | None:
    """Deny reason for a gate-escape inside one git invocation, else None."""
    if "git" not in tokens:
        return None
    i = tokens.index("git") + 1
    while i < len(tokens):
        tok = tokens[i]
        if tok == "-c" and i + 1 < len(tokens):
            # GLOBAL -c only (before the subcommand). `git commit -c HEAD`
            # reuses a commit message and never reaches this loop.
            if tokens[i + 1].split("=", 1)[0].strip().lower() == _HOOKSPATH_KEY:
                return _DENY_HOOKSPATH
            i += 2
            continue
        if tok.startswith("--config-env="):
            parts = tok.split("=", 2)
            if len(parts) > 1 and parts[1].strip().lower() == _HOOKSPATH_KEY:
                return _DENY_HOOKSPATH
            i += 1
            continue
        if tok in _GIT_OPTS_WITH_VALUE:
            i += 2
            continue
        if tok.startswith("-"):
            i += 1
            continue
        break
    if i >= len(tokens):
        return None
    subcommand = tokens[i]
    args = _git_args(tokens, i + 1)
    if "--no-verify" in args:
        return _DENY_NO_VERIFY.format(sub=subcommand)
    if subcommand == "config" and _config_writes_hookspath(args):
        return _DENY_HOOKSPATH_CONFIG
    if subcommand == "commit":
        if "n" in set(_commit_short_flags(args)):
            return _DENY_COMMIT_DASH_N
        for message in _commit_messages(args):
            if _SKIP_MARKER_PREFIX in message:
                return _DENY_SKIP_MARKER.format(marker=_SKIP_MARKER_PREFIX)
    return None


def _iter_bypass_checks(command: str) -> Iterator[tuple[str, str]]:
    """Yield (label, deny reason) for every gate-escape in *command*."""
    for raw_segment in _SEGMENT_SPLIT_RE.split(_strip_heredocs(command)):
        segment = raw_segment.strip()
        if not segment:
            continue
        tokens = _segment_tokens(segment)
        if not tokens:
            continue
        if tokens[0] == "export":
            for tok in tokens[1:]:
                match = _ASSIGN_RE.match(tok)
                if match:
                    reason = _env_bypass_reason(match.group(1), match.group(2))
                    if reason:
                        yield f"export {match.group(1)}", reason
            continue
        # Leading `VAR=value` assignments and command wrappers, in any order.
        idx = 0
        while idx < len(tokens):
            match = _ASSIGN_RE.match(tokens[idx])
            if match:
                reason = _env_bypass_reason(match.group(1), match.group(2))
                if reason:
                    yield f"env {match.group(1)}", reason
                idx += 1
                continue
            if tokens[idx] in _COMMAND_WRAPPERS:
                idx += 1
                continue
            break
        if idx >= len(tokens):
            continue
        if os.path.basename(tokens[idx]) in _TEXT_EMITTING:
            continue  # doc/test-authoring escape: emitting or searching text
        reason = _git_bypass_reason(tokens[idx:])
        if reason:
            yield "git gate-escape flag", reason


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

        # Gate-escape scan (OMN-16725) runs FIRST and independently of the
        # canonical-clone scan: these patterns are denied wherever they run, and
        # some of them (PREPUSH_*, ENABLE_SMART_TESTS) carry no 'git' token at
        # all, so they must be checked before the git early-out below.
        try:
            for label, reason in _iter_bypass_checks(command):
                _log(f"DENY Bash gate-escape [{label}]: {command[:200]}")
                _deny(reason)
        except Exception as exc:  # noqa: BLE001 — never block on a parser bug
            _log(f"ERROR parsing Bash command for gate-escapes, failing open: {exc!r}")

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
