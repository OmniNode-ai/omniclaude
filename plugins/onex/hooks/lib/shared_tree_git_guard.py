#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
r"""Fail-closed shared-tree git admission gate for the shared registry clone (OMN-18798).

Why this exists
---------------
The repository registry clone at ``$OMNI_HOME`` is the ONE repository in
the fleet where many concurrent agent
lanes commit into the SAME working tree -- ``docs/tracking/``,
``docs/workflows/``, ``.claude/workflows/``, ``scripts/``. Code repos use
per-ticket worktrees and do not have this problem. Two failure classes were
measured in the shared clone and neither had a mechanical defence:

1. **Destruction.** ``git reflog`` recorded 20 ``reset: moving to
   origin/main`` entries in that clone on 2026-09-18 alone. Those resets
   twice re-orphaned a staged 1.9 MB ledger-roll archive holding 1,258
   append-only coordination rows -- leaving them untracked on one disk, with
   no copy in any commit, on any branch, on any remote, for 2h22m, where a
   ``git clean -fd`` would have destroyed them and left ``origin/main``
   showing a ledger that had never lost them. The same verbs twice dropped a
   peer lane's unpushed commit from local ``main`` and twice reverted a peer
   lane's uncommitted edit.

2. **Stranding**, which destroys nothing and is quieter. A feature branch
   checked out in the shared clone makes ``commit_lock.py`` refuse EVERY
   other lane's ledger commit -- exit 78, ``STRANDED CLONE`` -- for as long
   as it stays checked out. Three rows appended at 01:24Z reached a
   committed copy only at 11:17Z; the refusals at 02:37Z named the branch.
   The only signal is an exit code on somebody else's terminal, so a guard
   that refused only the destructive verbs would not have caught it. This is
   why ``git checkout -b`` and ``git switch`` are refused here too.

Operating Rule 19 of the workspace ``CLAUDE.md`` states the prohibition.
Until this module it was doctrine only -- it held exactly as long as each
lane remembered it, which the reflog shows was not long.

What this refuses, and what it deliberately does not
------------------------------------------------------
A shell segment whose program is ``git`` is refused when its effective git
root -- ``git rev-parse --show-toplevel`` semantics applied to the ``-C
<path>`` argument, or to the command's own ``cwd`` when no ``-C`` is given
-- IS the registry clone at ``$OMNI_HOME`` itself, AND its subcommand
matches a
refused shape declared in ``shared_tree_git_guard_policy.json``:

* ``reset``, ``switch``, ``clean``, ``rebase`` -- in every form;
* ``checkout`` -- except the Operating Rule 17 path-scoped restore recipe
  (``git checkout -- <path>``, ``git checkout <ref> -- <path>``), and except
  nothing else: a ``-b``/``-B`` creation is refused even with a ``--``, a
  whole-tree path operand is refused because it is a blanket checkout in
  path-scoped clothing, and operands with no ``--`` separator are refused
  because git itself cannot tell a ref from a path there;
* ``merge`` -- unless it carries ``--ff-only`` (the sanctioned sync verb,
  which advances a pointer or refuses and never runs a content merge) or one
  of the in-progress management flags ``--abort``/``--quit``/``--continue``;
* ``branch`` -- only a delete or rename whose target IS the checked-out
  branch, read from ``.git/HEAD`` rather than by running git.

Everything else passes untouched, because it never matches the vocabulary in
the first place: ``git merge --ff-only``, ``git fetch``, ``git pull
--ff-only``, and every read (``status``, ``log``, ``diff``, ``show``,
``rev-parse``, ``reflog``, ``worktree list``). There is no allowlist to fall
out of date and no escape entry -- no consent citation, no exempt marker --
because each refused verb has a sanctioned alternative reaching the same
outcome without touching state a peer lane owns.

Scope, stated so it is not over-read
--------------------------------------
This fires ONLY when the effective git root is the registry clone itself. A
worktree under ``omni_worktrees/`` has its own ``.git`` file and so its own
root; a code-repo canonical clone under ``$OMNI_HOME`` has root
``$OMNI_HOME/<repo>``, not ``$OMNI_HOME``. Neither is ever matched, and both
already have the OMN-7018/OMN-14330 worktree guard.

Token matching, not substring matching
---------------------------------------
Each shell segment is tokenised with ``shlex`` and matched by program plus
tokens, never by raw text -- the same reason the OMN-17334 git-stash guard
this module is patterned on does it that way: a comment or a grep that
merely *mentions* ``git reset`` is not a reset, and a raw-substring rule
would refuse both (workspace CLAUDE.md rule 15, the OCC#7213 shape).

Fail-closed boundary, stated deliberately
-------------------------------------------
* A command carrying neither a ``git`` token nor any refused verb never
  reaches this module -- the shell wrapper's pre-filter drops it. A bug here
  can never brick unrelated Bash traffic.
* A command that DOES carry the vocabulary and cannot then be resolved -- an
  unreadable policy, a target directory that cannot be stat'd, an unreadable
  ``HEAD`` behind a branch delete -- is REFUSED.
* An UNTOKENISABLE command is refused only when its raw text plainly names
  ``git`` and one of the refused verbs as whole words. An unbalanced quote
  in a command that has nothing to do with git is not this guard's business,
  and refusing it would be a bug wearing a fail-closed costume.

What this cannot do, stated rather than implied
-------------------------------------------------
It sees a command only at the Claude Code tool seam. A ``git reset`` typed
directly at a terminal, or run by a script this guard never sees, reaches
the shared tree unchallenged. And the hook loads at session start, so
sessions already open when it lands are not covered until they restart.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

__all__ = [
    "GATE_BIT_NAME",
    "TICKET",
    "Decision",
    "Policy",
    "PolicyError",
    "evaluate_bash_command",
    "load_policy",
    "main",
    "resolve_registry_root",
]

DEFAULT_POLICY_PATH: Final[Path] = (
    Path(__file__).resolve().parent.parent
    / "config"
    / "shared_tree_git_guard_policy.json"
)

#: The mask bit this guard is gated by, named in every refusal so a lane
#: that believes the guard is wrong has a documented route that is not
#: "work around it". BORROWED, exactly as the OMN-17334 git-stash guard
#: borrows SWEEP_PREFLIGHT and the OMN-17957 credential-rotation guard
#: borrows PRE_TOOL_AUTHORIZATION_SHIM: hook_bits.sh is GENERATED from
#: omnibase_core's hook_activations.yaml, so minting a dedicated bit is a
#: cross-repo change this guard does not need. SCOPE_GATE is the cleanest
#: borrow available -- it is bit_defined in hook_bits.sh, it is set in the
#: default mask, its namesake script (pre_tool_use_scope_gate.sh) is on disk
#: and UNREGISTERED in hooks.json, and no registered script gates on it. So
#: `onex hooks disable SCOPE_GATE` disables exactly this guard and nothing
#: else that is live. tests/hooks/test_shared_tree_git_guard.py pins the
#: borrow: registering the namesake would silently share one switch between
#: two independent controls, and must turn that test red first.
GATE_BIT_NAME: Final[str] = "SCOPE_GATE"

TICKET: Final[str] = "OMN-18798"

#: Shell separators that end one segment and begin another, matched on the
#: TOKEN stream shlex produces rather than on raw text.
_SEPARATORS: Final[frozenset[str]] = frozenset({";", "&&", "||", "|", "&"})

#: Wrapper programs stripped before a segment's program is read, so
#: `sudo git reset --hard` is still a git reset.
_WRAPPERS: Final[frozenset[str]] = frozenset(
    {"sudo", "env", "command", "time", "nohup", "nice", "doas"}
)

_ASSIGNMENT: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

#: git global flags that consume the NEXT token as a value, distinct from
#: `-C`, which this guard reads out separately as the target directory.
_GIT_VALUE_FLAGS: Final[frozenset[str]] = frozenset(
    {"-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}
)


class PolicyError(RuntimeError):
    """The policy file is missing, unreadable, or malformed."""


@dataclass(frozen=True)
class Policy:
    ticket: str
    rule: str
    safe_alternatives: str
    refused_subcommands: frozenset[str]
    unconditional_subcommands: frozenset[str]
    branch_destructive_flags: frozenset[str]
    branch_creation_flags: frozenset[str]
    merge_allowed_flags: frozenset[str]
    merge_allowed_targets: frozenset[str]
    merge_target_allowed_flags: frozenset[str]
    merge_allowed_on_branches: frozenset[str]
    branch_read_flags: frozenset[str]
    blanket_path_operands: frozenset[str]
    push_force_flags: frozenset[str]
    protected_path_operands: tuple[str, ...]
    registry_root_envs: tuple[str, ...]
    registry_root_markers: tuple[str, ...]


@dataclass(frozen=True)
class Decision:
    blocked: bool
    reason: str = ""
    #: Diagnostic-only notes that were not decisive. Never printed as a
    #: refusal reason.
    notes: tuple[str, ...] = field(default_factory=tuple)


def _require_str(raw: Any, key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise PolicyError(f"policy field {key!r} must be a non-empty string")
    return value


def _str_list(raw: Any, key: str) -> list[str]:
    value = raw.get(key)
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, str) and item for item in value)
    ):
        raise PolicyError(f"policy field {key!r} must be a non-empty list of strings")
    return value


def load_policy(path: Path | None = None) -> Policy:
    policy_path = path or DEFAULT_POLICY_PATH
    try:
        raw = json.loads(policy_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise PolicyError(f"cannot read policy at {policy_path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise PolicyError(f"malformed policy JSON at {policy_path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise PolicyError(f"policy at {policy_path} must be a JSON object")
    refused = frozenset(_str_list(raw, "refused_subcommands"))
    unconditional = frozenset(_str_list(raw, "unconditional_subcommands"))
    if not unconditional <= refused:
        raise PolicyError(
            "policy field 'unconditional_subcommands' must be a subset of "
            "'refused_subcommands'"
        )
    return Policy(
        ticket=_require_str(raw, "ticket"),
        rule=_require_str(raw, "rule"),
        safe_alternatives=_require_str(raw, "safe_alternatives"),
        refused_subcommands=refused,
        unconditional_subcommands=unconditional,
        branch_destructive_flags=frozenset(_str_list(raw, "branch_destructive_flags")),
        branch_creation_flags=frozenset(_str_list(raw, "branch_creation_flags")),
        merge_allowed_flags=frozenset(_str_list(raw, "merge_allowed_flags")),
        merge_allowed_targets=frozenset(_str_list(raw, "merge_allowed_targets")),
        merge_target_allowed_flags=frozenset(
            _str_list(raw, "merge_target_allowed_flags")
        ),
        merge_allowed_on_branches=frozenset(
            _str_list(raw, "merge_allowed_on_branches")
        ),
        branch_read_flags=frozenset(_str_list(raw, "branch_read_flags")),
        blanket_path_operands=frozenset(_str_list(raw, "blanket_path_operands")),
        push_force_flags=frozenset(_str_list(raw, "push_force_flags")),
        protected_path_operands=tuple(_str_list(raw, "protected_path_operands")),
        registry_root_envs=tuple(_str_list(raw, "registry_root_envs")),
        registry_root_markers=tuple(_str_list(raw, "registry_root_markers")),
    )


def _tokenize(command: str) -> list[str] | None:
    """Tokenise a command, or return None when it cannot be tokenised."""
    lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|")
    lexer.whitespace_split = True
    try:
        return list(lexer)
    except ValueError:
        return None


def _segments(command: str) -> list[list[str]] | None:
    tokens = _tokenize(command)
    if tokens is None:
        return None
    segments: list[list[str]] = []
    current: list[str] = []
    for tok in tokens:
        if tok in _SEPARATORS:
            if current:
                segments.append(current)
            current = []
        else:
            current.append(tok)
    if current:
        segments.append(current)
    return segments


def _strip_wrappers(tokens: list[str]) -> list[str]:
    result = list(tokens)
    while result:
        head = result[0]
        if _ASSIGNMENT.match(head):
            result = result[1:]
            continue
        if os.path.basename(head) in _WRAPPERS:
            result = result[1:]
            continue
        break
    return result


@dataclass(frozen=True)
class _GitInvocation:
    target_arg: str | None  # the `-C <path>` value, if any
    subcommand: str
    args: tuple[str, ...]  # everything after the subcommand


def _parse_git(tokens: list[str]) -> _GitInvocation | None:
    """Return the shape of one `git ...` segment, or None if it is not one."""
    stripped = _strip_wrappers(tokens)
    if not stripped or os.path.basename(stripped[0]) != "git":
        return None
    args = stripped[1:]
    target_arg: str | None = None
    idx = 0
    while idx < len(args):
        tok = args[idx]
        if tok == "-C":
            if idx + 1 < len(args):
                target_arg = args[idx + 1]
            idx += 2
            continue
        if tok in _GIT_VALUE_FLAGS:
            idx += 2
            continue
        if tok.startswith("-"):
            idx += 1
            continue
        break
    if idx >= len(args):
        return None
    return _GitInvocation(
        target_arg=target_arg,
        subcommand=args[idx],
        args=tuple(args[idx + 1 :]),
    )


def _resolve_target_dir(invocation: _GitInvocation, cwd: Path) -> Path:
    if invocation.target_arg:
        candidate = Path(invocation.target_arg)
        return candidate if candidate.is_absolute() else (cwd / candidate)
    return cwd


def _find_git_root(start: Path) -> Path | None:
    """Walk up from `start` and return the first directory with a `.git` entry."""
    current = start
    seen: set[Path] = set()
    while True:
        try:
            resolved = current.resolve()
        except OSError:
            return None
        if resolved in seen:
            return None
        seen.add(resolved)
        marker = resolved / ".git"
        if marker.exists() or marker.is_symlink():
            return resolved
        if resolved.parent == resolved:
            return None
        current = resolved.parent


def _has_markers(candidate: Path, markers: tuple[str, ...]) -> bool:
    try:
        return all((candidate / marker).exists() for marker in markers)
    except OSError:
        return False


def resolve_registry_root(
    policy: Policy, environ: dict[str, str] | None = None
) -> Path | None:
    """The shared registry clone, from the environment or None.

    Declared env vars are tried in order. A value that does not resolve to a
    directory is ignored rather than trusted -- a stale export must not make
    an unrelated tree look like the registry.
    """
    env = os.environ if environ is None else environ
    for name in policy.registry_root_envs:
        raw = env.get(name)
        if not raw:
            continue
        try:
            candidate = Path(raw).resolve()
        except OSError:
            continue
        if candidate.is_dir():
            return candidate
    return None


def _is_registry_root(
    git_root: Path, registry_root: Path | None, policy: Policy
) -> bool:
    """Is this git root the shared registry clone?

    The env-declared path is authoritative WHENEVER it resolves, and is then
    the only test: an exact path comparison, so the one tree many lanes share
    is matched and nothing else is.

    The marker test is a fallback used ONLY when no declared env var resolves,
    so the guard does not go DARK in a thin environment -- a hook process with
    no OMNI_HOME would otherwise admit every refused verb in the exact tree
    this guard exists to protect. It requires EVERY declared marker AND a
    `.git` DIRECTORY rather than a file. Both halves matter: the markers (the
    rolling work ledger and the doc-placement gate config) sit together only
    in a registry checkout, and the directory test is what keeps a WORKTREE
    of the registry out of scope -- that worktree carries the same two marker
    files, and it is the sanctioned remedy this guard points lanes at, so
    matching it would refuse the very thing the refusal recommends.
    """
    if registry_root is not None:
        return git_root == registry_root
    if not _has_markers(git_root, policy.registry_root_markers):
        return False
    try:
        return (git_root / ".git").is_dir()
    except OSError:
        return False


def _read_current_branch(git_root: Path) -> str | None:
    """The checked-out branch, read from .git/HEAD. None when unreadable.

    Read rather than shelled out to deliberately: this module runs inside a
    PreToolUse hook on every Bash call, and starting a git process there is
    both slower and a second failure mode. A detached HEAD has no branch and
    returns None, which the caller treats as unreadable and fails closed on.
    """
    head = git_root / ".git"
    try:
        if head.is_dir():
            text = (head / "HEAD").read_text(encoding="utf-8").strip()
        else:
            return None
    except OSError:
        return None
    prefix = "ref: refs/heads/"
    if text.startswith(prefix):
        return text[len(prefix) :].strip() or None
    return None


def _is_force_push_flag(token: str, policy: Policy) -> bool:
    """Does this token make a `git push` a FORCE push?

    Three spellings, all real: the exact long flag, the `=<value>` form that
    `--force-with-lease` and `--force-if-includes` both take, and a bundled
    short cluster such as `-fu`, which git accepts and a naive exact match
    would wave through.
    """
    if token in policy.push_force_flags:
        return True
    for flag in policy.push_force_flags:
        if flag.startswith("--") and token.startswith(f"{flag}="):
            return True
    if re.fullmatch(r"-[A-Za-z]+", token) and "f" in token[1:]:
        return True
    return False


def _protected_paths_named(
    invocation: _GitInvocation,
    policy: Policy,
    target_dir: Path,
    git_root: Path,
) -> list[str]:
    """Which protected paths, if any, this checkout's operands resolve to.

    The operands are relative to the CALLER's directory and the protected
    entries are declared relative to the REPO ROOT, so both are made
    absolute before they are compared -- conflating the two is how a guard
    refuses from the root and admits the same file from one level down.

    Comparison is by path component, never by string prefix: a declared
    directory matches everything beneath it, while a sibling whose name
    merely starts with the same characters does not.
    """
    args = list(invocation.args)
    if "--" not in args:
        return []
    operands = args[args.index("--") + 1 :]
    protected_abs = {
        os.path.normpath(os.path.join(str(git_root), entry)): entry
        for entry in policy.protected_path_operands
    }
    hits: list[str] = []
    for operand in operands:
        candidate = os.path.normpath(
            operand
            if Path(operand).is_absolute()
            else os.path.join(str(target_dir), operand)
        )
        for abs_entry, declared in protected_abs.items():
            if candidate == abs_entry or candidate.startswith(abs_entry + os.sep):
                if declared not in hits:
                    hits.append(declared)
    return hits


def _checkout_is_path_scoped(invocation: _GitInvocation, policy: Policy) -> bool:
    """True only for the Operating Rule 17 sanctioned restore shape."""
    args = list(invocation.args)
    if any(arg in policy.branch_creation_flags for arg in args):
        return False
    if "--" not in args:
        return False
    paths = args[args.index("--") + 1 :]
    if not paths:
        return False
    return not any(path in policy.blanket_path_operands for path in paths)


def _refusal_detail(
    invocation: _GitInvocation,
    policy: Policy,
    current_branch: str | None,
    target_dir: Path,
    git_root: Path,
) -> str | None:
    """Why this invocation is refused, or None when it is allowed.

    The returned string is the middle clause of the refusal message: what
    this specific command would do to the lanes sharing the tree.
    """
    sub = invocation.subcommand
    args = list(invocation.args)

    if sub in policy.unconditional_subcommands:
        if sub == "reset":
            return (
                "`git reset` rewrites the index, and a mixed or hard reset "
                "rewrites the working tree with it -- returning a peer "
                "lane's staged file to untracked and dropping unpushed "
                "commits from the local branch. Twenty resets to "
                "origin/main in this clone on 2026-09-18 re-orphaned a "
                "1,258-row ledger-roll archive and twice took a peer's work"
            )
        if sub == "clean":
            return (
                "`git clean` deletes untracked files outright, and in this "
                "tree the untracked files at any moment include another "
                "lane's in-flight work and a freshly rolled ledger archive "
                "that no commit yet holds"
            )
        if sub == "switch":
            return (
                "`git switch` moves the whole shared tree to another "
                "branch. Every other lane keeps working in the tree it "
                "moved, and while the clone is off `main` commit_lock.py "
                "refuses every peer lane's ledger commit with exit 78, "
                "STRANDED CLONE"
            )
        return (
            "`git rebase` rewrites history and checks each replayed commit "
            "out over the shared tree, so a peer lane reading or writing a "
            "file during the replay sees a version nobody asked for -- "
            "measured on 2026-09-18, when a rebase checked the pre-roll "
            "ledger out over the tree mid-roll"
        )

    if sub == "checkout":
        if not args:
            return None
        if any(arg in policy.branch_creation_flags for arg in args):
            return (
                "`git checkout -b` creates a feature branch in the clone "
                "every lane shares. Nothing is destroyed and that is what "
                "makes it dangerous: while the branch is checked out, "
                "commit_lock.py refuses EVERY other lane's ledger commit "
                "with exit 78, STRANDED CLONE, and the only signal is an "
                "exit code on somebody else's terminal. Measured once "
                "already -- three rows appended at 01:24Z reached a "
                "committed copy at 11:17Z"
            )
        protected = _protected_paths_named(invocation, policy, target_dir, git_root)
        if protected:
            return (
                f"the path operand resolves to {protected[0]}, the "
                "append-only coordination surface every lane appends to "
                "through commit_lock.py. A path-scoped restore is the "
                "Operating Rule 17 recipe and is allowed on every other "
                "path, but on THIS one it returns the file to HEAD -- not "
                "to what was in the working tree -- so every row appended "
                "since the last commit is discarded with no diff, no "
                "conflict and no failure. Rows were lost exactly this way "
                "in the 14:46-14:55Z window on 2026-09-19. Re-append the "
                "row through ledger_lock.py instead, or read the old "
                "version without writing the tree: git show <ref>:<path>"
            )
        if _checkout_is_path_scoped(invocation, policy):
            return None
        if "--" in args:
            blanket = [
                arg
                for arg in args[args.index("--") + 1 :]
                if arg in policy.blanket_path_operands
            ]
            if blanket:
                return (
                    f"a path operand of {blanket[0]!r} makes this a BLANKET "
                    "checkout wearing path-scoped syntax: it reverts every "
                    "uncommitted edit in the tree, including the ones peer "
                    "lanes are still writing. Name the individual paths "
                    "instead"
                )
            return (
                "`git checkout` with no path after `--` moves the shared "
                "tree rather than restoring a file in it"
            )
        return (
            "`git checkout <ref>` moves the whole shared tree to another "
            "commit, reverting peer lanes' uncommitted edits and stranding "
            "the clone off `main`, where commit_lock.py refuses every "
            "peer's ledger commit. Operands with no `--` separator are "
            "refused even when a path is meant, because git itself cannot "
            "tell a ref from a path there and neither can this guard -- use "
            "the explicit `git checkout <ref> -- <path>` form"
        )

    if sub == "merge":
        if any(arg in policy.merge_allowed_flags for arg in args):
            return None
        flags = [arg for arg in args if arg.startswith("-")]
        operands = [arg for arg in args if not arg.startswith("-")]
        is_publish_loop_shape = (
            len(operands) == 1
            and operands[0] in policy.merge_allowed_targets
            and all(flag in policy.merge_target_allowed_flags for flag in flags)
        )
        if is_publish_loop_shape:
            if current_branch is None:
                return (
                    "the checked-out branch of the shared clone could not be "
                    "read from .git/HEAD, and the sanctioned publish-loop "
                    f"merge of {operands[0]} is allowed only ON "
                    f"{sorted(policy.merge_allowed_on_branches)[0]!r}. "
                    "Whether this is that merge or the feature-branch merge "
                    "that dropped rows on 2026-09-19 is unknown, so it is "
                    "refused rather than assumed safe"
                )
            if current_branch in policy.merge_allowed_on_branches:
                return None
            return (
                f"this merges {operands[0]} into {current_branch!r}, NOT into "
                f"{sorted(policy.merge_allowed_on_branches)[0]!r}. On `main` "
                "this exact command is the sanctioned publish loop and is "
                "allowed; on a feature branch checked out in the shared "
                "clone it is the 2026-09-19 14:52:55Z shape, whose round "
                "trip back to `main` at 14:55:04Z did not carry rows "
                "appended between 14:48Z and 14:53Z. Put the clone back on "
                "`main` first, or do the work in a worktree"
            )
        return (
            "this `git merge` runs an unbounded three-way CONTENT merge on "
            "the shared tree, and the file most likely to diverge in it is "
            "the append-only ledger every lane writes to. A resolution can "
            "drop a peer lane's rows silently, with no conflict marker and "
            "no failure. Two merge shapes ARE allowed here and neither is "
            "this one: `git merge --ff-only origin/main`, which either "
            "advances the pointer or refuses; and the ruled ledger publish "
            "loop, `git merge --no-edit origin/main` ON `main` and nothing "
            "else, adopted on 2026-09-19 after the fast-forward step lost "
            "the race against concurrent appends eight cycles running. A "
            "different target, an extra operand or a strategy flag is "
            "neither. `--abort`, `--quit` and `--continue` manage a merge "
            "already in progress and are not refused"
        )

    if sub == "push":
        if not any(_is_force_push_flag(arg, policy) for arg in args):
            return None
        return (
            "a FORCE push from this clone can destroy published append-only "
            "coordination rows on the remote. Every other verb this guard "
            "refuses costs the tree's UNCOMMITTED state; this one rewrites "
            "history that is already safe, and after a ledger roll the "
            "remote copy is the only surviving one. Nothing here needs it: "
            "append rows through commit_lock.py, sync with "
            "`git merge --ff-only origin/main`, push to a FRESH branch, "
            "open a pull request and land it by squash"
        )

    if sub == "branch":
        destructive = [arg for arg in args if arg in policy.branch_destructive_flags]
        operands = [arg for arg in args if not arg.startswith("-")]
        if not destructive:
            reading = any(
                arg.split("=", 1)[0] in policy.branch_read_flags for arg in args
            )
            if operands and not reading:
                return (
                    f"`git branch {operands[0]}` CREATES a branch in the clone "
                    "every lane shares. It moves nothing by itself, which is "
                    "why it reads as harmless -- but a branch created here "
                    "exists to be checked out, and the moment it is, "
                    "commit_lock.py refuses EVERY other lane's ledger commit "
                    "with exit 78, STRANDED CLONE, and the only signal is an "
                    "exit code on somebody else's terminal. Create the branch "
                    "with the worktree that will hold it instead: git -C "
                    "$OMNI_HOME/<repo> worktree add "
                    "$OMNI_HOME/omni_worktrees/<ticket>/<repo> -b <branch>"
                )
            return None
        renaming = any(arg in ("-m", "-M", "--move") for arg in destructive)
        if current_branch is None:
            return (
                f"`git branch {destructive[0]}` was refused because the "
                "checked-out branch of the shared clone could not be read "
                "from .git/HEAD, so whether this targets the branch every "
                "lane is committing on is unknown. An unverifiable "
                "shared-tree mutation is refused, never assumed safe"
            )
        if renaming and len(operands) < 2:
            return (
                f"`git branch {destructive[0]}` with one operand renames the "
                f"CURRENT branch, {current_branch!r} -- the branch every "
                "other lane in this tree is committing on. Their next "
                "commit is refused and their push target is gone"
            )
        if current_branch in operands:
            return (
                f"this deletes or renames {current_branch!r}, the branch "
                "the shared clone is checked out on and every other lane is "
                "committing to"
            )
        return None

    return None


def _render_block_reason(
    policy: Policy, invocation: _GitInvocation, git_root: Path, detail: str
) -> str:
    return (
        f"BLOCKED: `git {invocation.subcommand}` in {git_root}, the shared "
        f"registry clone ({policy.ticket}, {policy.rule}). Many "
        "concurrent lanes work in this ONE tree, so a command that moves it "
        "takes their work with it: "
        f"{detail}. Use a sanctioned alternative instead -- "
        f"{policy.safe_alternatives}. Reads are never gated, and neither is "
        "`git fetch`, `git merge --ff-only` or `git pull --ff-only`. To "
        f"disable this guard: onex hooks disable {GATE_BIT_NAME}"
    )


def _plainly_names_refused_verb(command: str, policy: Policy) -> bool:
    """Does raw text name `git` and a refused verb as whole words?

    Used only on the untokenisable path. Deliberately narrow: an unbalanced
    quote in a command with nothing to do with git is not this guard's
    business, and refusing it would be a bug wearing a fail-closed costume.
    """
    if not re.search(r"(?<![\w/-])git(?![\w-])", command):
        return False
    return any(
        re.search(rf"(?<![\w-]){re.escape(verb)}(?![\w-])", command)
        for verb in policy.refused_subcommands
    )


def evaluate_bash_command(
    command: str, policy: Policy, cwd: Path, registry_root: Path | None
) -> Decision:
    notes: list[str] = []
    segments = _segments(command)
    if segments is None:
        if _plainly_names_refused_verb(command, policy):
            return Decision(
                blocked=True,
                reason=(
                    "BLOCKED: this Bash command could not be tokenised (an "
                    "unbalanced quote, most likely) and its raw text names "
                    "git together with one of the verbs refused in the "
                    f"shared registry clone ({policy.ticket}, "
                    f"{policy.rule}), so whether it moves the tree every "
                    "other lane is working in cannot be determined. An "
                    "unverifiable shared-tree mutation is refused, never "
                    "assumed safe. Fix the quoting and re-run, or use a "
                    f"sanctioned alternative -- {policy.safe_alternatives}. "
                    f"To disable this guard: onex hooks disable {GATE_BIT_NAME}"
                ),
            )
        return Decision(
            blocked=False,
            notes=("untokenisable command naming no refused git verb",),
        )

    for segment in segments:
        invocation = _parse_git(segment)
        if invocation is None:
            continue
        if invocation.subcommand not in policy.refused_subcommands:
            continue
        try:
            target_dir = _resolve_target_dir(invocation, cwd)
        except OSError as exc:
            return Decision(
                blocked=True,
                reason=(
                    f"BLOCKED: `git {invocation.subcommand}` could not have "
                    "its target directory resolved "
                    f"({exc}), so whether it targets the shared "
                    f"registry clone is unknown ({policy.ticket}, "
                    f"{policy.rule}). An unverifiable shared-tree mutation "
                    "is refused, never assumed safe. To disable this guard: "
                    f"onex hooks disable {GATE_BIT_NAME}"
                ),
            )
        git_root = _find_git_root(target_dir)
        if git_root is None:
            # Not inside any git repository this guard can identify -- git
            # itself will refuse the command; nothing to gate here.
            continue
        if not _is_registry_root(git_root, registry_root, policy):
            notes.append(
                f"`git {invocation.subcommand}` targets {git_root}, which is "
                "not the shared registry clone"
            )
            continue
        detail = _refusal_detail(
            invocation,
            policy,
            _read_current_branch(git_root),
            target_dir=target_dir,
            git_root=git_root,
        )
        if detail is None:
            continue
        return Decision(
            blocked=True,
            reason=_render_block_reason(policy, invocation, git_root, detail),
        )
    return Decision(blocked=False, notes=tuple(notes))


def _block(reason: str) -> int:
    print(json.dumps({"decision": "block", "reason": reason}))
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="OMN-18798 shared-tree git guard")
    parser.add_argument(
        "--policy",
        type=Path,
        default=None,
        help="override the policy JSON path (defaults to the co-located config)",
    )
    args = parser.parse_args(argv)

    try:
        raw = sys.stdin.read()
    except OSError as exc:
        return _block(
            "BLOCKED: could not read the PreToolUse payload for this Bash "
            f"call, so it cannot be checked for a shared-tree git mutation ({exc})."
        )

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        return _block(
            "BLOCKED: the PreToolUse payload for this Bash call is not "
            "readable JSON, so it cannot be checked for a shared-tree git "
            f"mutation ({exc})."
        )
    if not isinstance(payload, dict):
        return _block(
            "BLOCKED: the PreToolUse payload for this Bash call is not a "
            "JSON object, so it cannot be checked for a shared-tree git mutation."
        )

    tool_input = payload.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str) or not command:
        # No command to evaluate -- nothing for this guard to do.
        return 0

    try:
        policy = load_policy(args.policy)
    except PolicyError as exc:
        return _block(
            "BLOCKED: the OMN-18798 shared-tree git admission gate's policy "
            f"could not be loaded, so this command cannot be checked ({exc})."
        )

    cwd_raw = payload.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    cwd = Path(cwd_raw)
    registry_root = resolve_registry_root(policy)

    try:
        decision = evaluate_bash_command(command, policy, cwd, registry_root)
    except Exception as exc:  # noqa: BLE001 - fail-closed boundary, deliberate
        return _block(
            "BLOCKED: the OMN-18798 shared-tree git admission gate could not "
            f"evaluate this command ({exc}); an unverifiable shared-tree "
            "mutation is refused rather than assumed safe."
        )

    if decision.blocked:
        return _block(decision.reason)

    if decision.notes:
        print(json.dumps({"decision": "allow", "notes": list(decision.notes)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
