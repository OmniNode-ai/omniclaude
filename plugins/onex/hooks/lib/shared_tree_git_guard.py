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
   checked out in the shared clone makes ``onex-commit-lock`` refuse EVERY
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
Each shell segment is tokenised with the shared shell tokenizer and matched by program plus
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
  and refusing it would be a bug wearing a fail-closed costume. Untokenisable
  means what the shell means (OMN-17427): an unterminated quote or
  substitution. An apostrophe in a here-document body or a comment is text,
  and a newline ends a command.

The lane git-fetch arm (OMN-20495)
-----------------------------------
A third arm, scoped to lanes rather than to a tree: ``git fetch``, ``git
pull``, ``git ls-remote`` and ``git remote update`` reading a GitHub remote are
refused in a lane context, because a worktree shares its canonical clone's
refs and the canonical-clone sync keeps them current. The refusal names
``canonical_clone_sync.py refresh``. The full contract is at
``_lane_fetch_refusal``.

The dirty-path restore arm (OMN-18874), and why its scope is wider
--------------------------------------------------------------------
Everything above is about the ONE tree many lanes share. This arm is about a
hazard every lane has in its OWN tree: a path-scoped restore --
``git checkout [<ref>] -- <path>``, ``git checkout <ref> <path>``,
``git restore [--source=<ref>] <path>`` -- returns the file to the
REFERENCE, not to what is in the working tree. Over a path carrying
uncommitted work it discards that work silently: exit 0, no output, and no
reflog, because a working tree that was never committed has none. Operating
Rule 17 names the trap and prescribes the RED-proof sequence that springs
it whenever HEAD is still the base. Four lanes lost work that way, each
after reading the rule: OMN-18566, the OMN-18863 lane, OMN-18992 and
OMN-19237.

So the arm refuses a path restore when any content it would overwrite -- the
working-tree file, and the index entry when the restore writes the index --
exists nowhere else: not in the restore's own source, and not in any ref
declared in ``restore_reachable_refs`` (HEAD, the upstream, ``origin/dev``,
``origin/main``). That comparison, rather than a bare "is it dirty", is what
lets the committed-first Rule 17 sequence through: its closing
``git checkout HEAD -- <path>`` runs over a path that differs from HEAD, but
holds ``origin/dev``'s content, so restoring it loses nothing. Staged
changes count as uncommitted -- a staged blob is reachable from no ref. A
clean path, a path that does not exist yet, a deleted file brought back, and
an untracked file the source does not name are never refused, and neither is
the read the refusal prescribes, ``git show <rev>:<path> > <scratch file>``,
which never writes the tree.

Scope is every git root the guard can place under the fleet: the registry
clone, any canonical clone or worktree beneath ``$OMNI_HOME``, anything under
a declared worktrees root (``worktree_root_envs``), and any git WORKTREE at
all (a ``.git`` file), matching the OMN-17334 stash guard so a thin hook
environment cannot switch it off where lanes work. A plain clone elsewhere
on the disk is left alone.

Unlike the rest of this module, this arm has to run git: dirtiness lives in
the index and the object store. Every probe runs with the location variables
scrubbed, optional locks off, and a declared timeout, and it fails CLOSED --
a probe that errors or times out, an unresolvable ``cd`` ahead of the
restore, ``--pathspec-from-file``, and a ``--git-dir``/``--work-tree``
override -- flag or ``GIT_DIR``/``GIT_WORK_TREE`` assignment -- are all
refused, because in each case whether the command destroys work cannot be
determined.

An operand the shell computes (a variable, ``~``, a substitution, brace
expansion) is not refused for being computed (OMN-17427). A variable the
environment or an earlier assignment in the command resolves is read. A path
operand that cannot be resolved is refused as indeterminate (OMN-19380),
even over a clean tree: pass literal paths, or commit first and restore by
path per Operating Rule 17. An unresolved source operand credits nothing as
already saved; the declared reachable refs still determine whether its
literal paths hold uncommitted work. A bare ``git checkout <name>`` after an unresolvable ``cd`` is
refused on the same ground, since it may be a branch switch or a path
restore; the refusal names ``git switch`` as the unambiguous verb. A
conflicted path is judged too: ``--ours``/``--theirs``/``-m`` rewrite its
working-tree file from the index stages. Probes run
only for a restore shape in scope, so ordinary Bash traffic never pays for
them.

What this cannot do, stated rather than implied
-------------------------------------------------
The restore arm cannot tell a deliberate probe mutation from work: an
uncommitted edit typed into a tracked file is refused however disposable the
lane considers it, and the refusal points at the scratch-copy read that
never needs a restore. A ``git show <rev>:<path> > <path>`` redirected over
the dirty file itself is the same loss by other means and is not seen.

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
import subprocess
import sys
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Final

_HOOKS_LIB = Path(__file__).parent
if str(_HOOKS_LIB) not in sys.path:
    sys.path.insert(0, str(_HOOKS_LIB))

from collections import ChainMap  # noqa: E402
from collections.abc import Mapping  # noqa: E402

from shell_words import (  # noqa: E402
    Operator,
    ShellSyntaxError,
    UnresolvableWord,
    Word,
    WordPart,
    apply_assignments,
    directory_target,
    expand_word,
    git_directory,
    shadow,
    shadowed_names,
    tokenize,
    unquoted,
)


class _ShellWord(str):
    """String-compatible policy token retaining the tokenizer's quoting."""

    word: Word

    def __new__(cls, word: Word) -> _ShellWord:
        token = super().__new__(cls, word.text)
        token.word = word
        return token


def _word(token: str) -> Word:
    return token.word if isinstance(token, _ShellWord) else unquoted(token)


#: What a path token may expand from: the hook's environment, with every
#: name the command itself sets marked unresolvable.
Scope = Mapping[str, "str | None"]

__all__ = [
    "GATE_BIT_NAME",
    "TICKET",
    "Decision",
    "GitProbeError",
    "Policy",
    "PolicyError",
    "evaluate_bash_command",
    "load_policy",
    "main",
    "resolve_registry_root",
    "resolve_worktree_roots",
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

#: Shell operators that end one segment and begin another, matched on the
#: OPERATOR tokens the shared tokenizer produces (OMN-17427) and never on the
#: text of a word, so a quoted semicolon (an argument of `find -exec`) ends
#: nothing. A newline ends a command exactly as a semicolon does.
_SEPARATORS: Final[frozenset[str]] = frozenset(
    {";", ";;", "&", "&&", "|", "||", "|&", "\n"}
)

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


class GitProbeError(RuntimeError):
    """A git probe behind the restore arm failed or timed out."""


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
    protected_push_refs: frozenset[str]
    directory_changing_programs: frozenset[str]
    blanket_path_operands: frozenset[str]
    push_force_flags: frozenset[str]
    protected_path_operands: tuple[str, ...]
    registry_root_envs: tuple[str, ...]
    registry_root_markers: tuple[str, ...]
    restore_ticket: str
    restore_rule: str
    restore_subcommands: frozenset[str]
    restore_reachable_refs: tuple[str, ...]
    restore_max_dirty_paths: int
    restore_safe_alternatives: str
    git_probe_timeout_seconds: float
    worktree_root_envs: tuple[str, ...]
    # The lane git-fetch arm (OMN-20495). See _lane_fetch_refusal.
    fetch_ticket: str = ""
    fetch_subcommands: frozenset[str] = frozenset()
    fetch_github_hosts: frozenset[str] = frozenset()
    fetch_lane_envs: tuple[str, ...] = ()
    fetch_lane_path_markers: tuple[str, ...] = ()
    fetch_allow_env: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class Decision:
    blocked: bool
    reason: str = ""
    #: Diagnostic-only notes that were not decisive. Never printed as a
    #: refusal reason.
    notes: tuple[str, ...] = field(default_factory=tuple)
    #: Set by the lane git-fetch arm (OMN-20495) for its refusal log line.
    fetch_verb: str = ""
    fetch_repo: str = ""


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


def _positive_number(raw: Any, key: str) -> float:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise PolicyError(f"policy field {key!r} must be a positive number")
    return float(value)


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
        protected_push_refs=frozenset(_str_list(raw, "protected_push_refs")),
        directory_changing_programs=frozenset(
            _str_list(raw, "directory_changing_programs")
        ),
        blanket_path_operands=frozenset(_str_list(raw, "blanket_path_operands")),
        push_force_flags=frozenset(_str_list(raw, "push_force_flags")),
        protected_path_operands=tuple(_str_list(raw, "protected_path_operands")),
        registry_root_envs=tuple(_str_list(raw, "registry_root_envs")),
        registry_root_markers=tuple(_str_list(raw, "registry_root_markers")),
        restore_ticket=_require_str(raw, "restore_ticket"),
        restore_rule=_require_str(raw, "restore_rule"),
        restore_subcommands=frozenset(_str_list(raw, "restore_subcommands")),
        restore_reachable_refs=tuple(_str_list(raw, "restore_reachable_refs")),
        restore_max_dirty_paths=int(_positive_number(raw, "restore_max_dirty_paths")),
        restore_safe_alternatives=_require_str(raw, "restore_safe_alternatives"),
        git_probe_timeout_seconds=_positive_number(raw, "git_probe_timeout_seconds"),
        worktree_root_envs=tuple(_str_list(raw, "worktree_root_envs")),
        fetch_ticket=_require_str(raw, "fetch_ticket"),
        fetch_subcommands=frozenset(_str_list(raw, "fetch_subcommands")),
        fetch_github_hosts=frozenset(
            h.lower() for h in _str_list(raw, "fetch_github_hosts")
        ),
        fetch_lane_envs=tuple(_str_list(raw, "fetch_lane_envs")),
        fetch_lane_path_markers=tuple(_str_list(raw, "fetch_lane_path_markers")),
        fetch_allow_env=_str_pairs(raw, "fetch_allow_env"),
    )


def _str_pairs(raw: Any, key: str) -> tuple[tuple[str, str], ...]:
    value = raw.get(key)
    if (
        not isinstance(value, dict)
        or not value
        or not all(isinstance(k, str) and isinstance(v, str) for k, v in value.items())
    ):
        raise PolicyError(f"policy field {key!r} must map names to strings")
    return tuple(sorted(value.items()))


def _segments(command: str) -> list[list[str]] | None:
    """The simple commands of ``command``, each as its dequoted words.

    OMN-17427. This read the command with ``shlex``, which is not a shell
    reader. An apostrophe in a here-document body made the whole command
    "untokenisable", and the raw-text fallback then refused any command whose
    prose said ``git`` next to ``merge``, ``push`` or ``branch``. A newline
    was plain whitespace, so the second line of ``cd x`` then
    ``git -C <registry clone> reset --hard`` joined the first line's segment
    and was never read as a git command at all. The shared tokenizer the
    worktree and PR-body guards already use ends a command at a newline, keeps
    a here-document body and a comment out of the command list, and fails
    only on a genuine syntax error (an unterminated quote or substitution).
    A subshell parenthesis stays a word of its own, which ``_peel_grouping``
    reads.
    """
    try:
        tokens = tokenize(command)
    except ShellSyntaxError:
        return None
    segments: list[list[str]] = []
    current: list[str] = []
    for tok in tokens:
        if isinstance(tok, Operator):
            if tok.text in _SEPARATORS:
                if current:
                    segments.append(current)
                current = []
            else:
                current.append(tok.text)
        elif isinstance(tok, Word):
            current.append(_ShellWord(tok))
        # A HereDoc is data handed to a program, never a command line.
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
    #: global flags before the subcommand, `-C` excluded; values of the
    #: separated two-token forms are folded in as `<flag>=<value>`.
    global_flags: tuple[str, ...] = ()
    directories: tuple[Word, ...] = ()


def _parse_git(tokens: list[str]) -> _GitInvocation | None:
    """Return the shape of one `git ...` segment, or None if it is not one."""
    stripped = _strip_wrappers(tokens)
    if not stripped or os.path.basename(stripped[0]) != "git":
        return None
    args = stripped[1:]
    target_arg: str | None = None
    directories: list[Word] = []
    global_flags: list[str] = []
    idx = 0
    while idx < len(args):
        tok = args[idx]
        if tok == "-C":
            if idx + 1 < len(args):
                target_arg = args[idx + 1]
                directories.append(_word(target_arg))
            idx += 2
            continue
        if tok.startswith("-C") and len(tok) > 2:
            original = _word(tok)
            head = original.parts[0]
            operand = Word((WordPart(head.text[2:], head.quote),) + original.parts[1:])
            target_arg = _ShellWord(operand)
            directories.append(operand)
            idx += 1
            continue
        if tok in _GIT_VALUE_FLAGS:
            value = args[idx + 1] if idx + 1 < len(args) else ""
            global_flags.append(f"{tok}={value}")
            idx += 2
            continue
        if tok.startswith("-"):
            global_flags.append(tok)
            idx += 1
            continue
        break
    if idx >= len(args):
        return None
    if target_arg is None:
        # OMN-19852. `--work-tree=<dir>` names the tree git operates on, so
        # it is the effective directory when no `-C` is given.
        for flag in global_flags:
            if flag.startswith("--work-tree=") and flag != "--work-tree=":
                target_arg = flag[len("--work-tree=") :]
                break
    return _GitInvocation(
        target_arg=target_arg,
        subcommand=args[idx],
        args=tuple(args[idx + 1 :]),
        global_flags=tuple(global_flags),
        directories=tuple(directories),
    )


def _expand_path(token: str, scope: Scope) -> str | None:
    """``token`` as the shell will see it, or None when that is unknown.

    The shared OMN-19229 helper expands ``~``, ``$NAME`` and ``${NAME}``. An
    unset variable, one the command itself sets, a shell-managed one such as
    ``$PWD``, or a substitution is unknown, never guessed. A token whose only
    obstacle is a glob is taken literally, as this guard always did, so a
    refusal that held before still holds.
    """
    try:
        return expand_word(_word(token), scope)
    except UnresolvableWord:
        if "$" in token or "`" in token:
            return None
        literal = os.path.expanduser(token)
        return None if literal.startswith("~") else literal


def _resolve_target_dir(
    invocation: _GitInvocation, cwd: Path, scope: Scope | None = None
) -> Path:
    if invocation.directories:
        try:
            resolved = git_directory(
                list(invocation.directories),
                scope if scope is not None else os.environ,
                cwd,
            )
            return Path(resolved) if resolved is not None else cwd
        except UnresolvableWord:
            return cwd / (invocation.target_arg or "")
    if invocation.target_arg:
        expanded = _expand_path(
            invocation.target_arg, scope if scope is not None else os.environ
        )
        raw = expanded or invocation.target_arg
        candidate = Path(raw)
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
        elif head.is_file():
            # A WORKTREE: `.git` is a file holding `gitdir: <admin dir>`,
            # and HEAD lives in that admin directory. OMN-18974 -- without
            # this branch every worktree reads as "HEAD unreadable", which
            # the protected-force-push arm fails closed on, refusing a lane
            # pushing its own branch. That is the defect this ticket is
            # about, reintroduced one layer down.
            pointer = head.read_text(encoding="utf-8").strip()
            marker = "gitdir:"
            if not pointer.startswith(marker):
                return None
            admin = Path(pointer[len(marker) :].strip())
            if not admin.is_absolute():
                admin = git_root / admin
            text = (admin / "HEAD").read_text(encoding="utf-8").strip()
        else:
            return None
    except OSError:
        return None
    prefix = "ref: refs/heads/"
    if text.startswith(prefix):
        return text[len(prefix) :].strip() or None
    return None


def _resolve_cd_target(
    tokens: list[str], policy: Policy, current: Path, scope: Scope
) -> Path | None:
    """The directory a `cd` segment moves to, or None when unresolvable.

    OMN-18974. The harness resets a Bash call's working directory between
    calls, so a lane working in its own worktree -- which Operating Rule 9
    requires -- reaches it with a `cd <worktree> &&` prefix and the payload
    cwd still at the registry root. A guard that reads only the payload cwd
    refuses that lane and then advises it to move to the worktree it is
    already in, which is the whole of the reported defect.

    `shlex` does not expand variables, so `cd "$WT"` arrives as an
    unexpanded token. It is expanded from this guard's own environment by the
    shared helper (OMN-19229): `~`, `$NAME` and `${NAME}` resolve, and an
    unset variable, a substitution or a glob returns None. `cd` with no
    operand goes HOME. A relative operand resolves against the directory in
    force at that point, so a chain composes.
    """
    stripped = _strip_wrappers(tokens)
    try:
        return Path(directory_target([_word(t) for t in stripped], scope, current))
    except UnresolvableWord:
        return None


def _push_destination_refs(invocation: _GitInvocation) -> list[str]:
    """The branch names a push would WRITE, normalised.

    Only the destination half of a refspec matters: `lane/mine:dev`
    rewrites `dev`, and `dev:lane/mine` does not. A leading `+` is force
    in refspec spelling, and `refs/heads/` is the same ref written long.
    """
    operands = [arg for arg in invocation.args if not arg.startswith("-")]
    if len(operands) < 2:
        return []
    refs: list[str] = []
    for spec in operands[1:]:
        dst = spec.split(":")[-1]
        dst = dst.lstrip("+")
        if dst.startswith("refs/heads/"):
            dst = dst[len("refs/heads/") :]
        if dst:
            refs.append(dst)
    return refs


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
                "moved, and while the clone is off `main` onex-commit-lock "
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
                "onex-commit-lock refuses EVERY other lane's ledger commit "
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
                "through onex-commit-lock. A path-scoped restore is the "
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
            "the clone off `main`, where onex-commit-lock refuses every "
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
            "append rows through onex-commit-lock, sync with "
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
                    "onex-commit-lock refuses EVERY other lane's ledger commit "
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


def _protected_push_detail(
    invocation: _GitInvocation,
    policy: Policy,
    git_root: Path,
    registry_root: Path | None,
) -> str | None:
    """Why a force push is refused OUTSIDE the registry clone, or None.

    OMN-18974 arm two. Everything else this guard refuses is about one
    shared working tree, so a per-ticket worktree -- which has exactly one
    owner -- is rightly out of scope and stays that way. `dev` and `main`
    are the exception: they are shared by every lane and by CI, and
    rewriting one is not a per-lane decision however private the tree the
    command is typed in. Measured allowed before this change from the
    worktree in the report.

    Scope is the registry root's own subtree. A clone elsewhere on the disk
    is nobody's business here.
    """
    if invocation.subcommand != "push":
        return None
    if not any(_is_force_push_flag(arg, policy) for arg in invocation.args):
        return None
    if registry_root is None:
        return None
    try:
        git_root.relative_to(registry_root)
    except ValueError:
        return None
    refs = _push_destination_refs(invocation)
    if not refs:
        # No refspec: git pushes the CURRENT branch. Without reading HEAD
        # this form would be the hole in the arm.
        current = _read_current_branch(git_root)
        if current is None:
            return (
                "a FORCE push with no refspec pushes the CHECKED-OUT branch, "
                "and .git/HEAD could not be read here, so whether it rewrites "
                f"{sorted(policy.protected_push_refs)} is unknown. An "
                "unverifiable force push to a shared branch is refused, never "
                "assumed safe -- name the destination explicitly"
            )
        refs = [current]
    hit = [ref for ref in refs if ref in policy.protected_push_refs]
    if not hit:
        return None
    return (
        f"this force-pushes {hit[0]!r}, a branch every lane and CI share. "
        "Rewriting it is not a per-lane decision however private the tree "
        "this was typed in, and it can destroy commits no local clone has "
        "a copy of. Force-pushing your OWN feature branch is untouched and "
        "is the normal way to land a rebase -- name it explicitly, as in "
        "`git push --force-with-lease origin HEAD:<your-branch>`. To change "
        f"{hit[0]!r} itself, open a pull request and land it"
    )


def _render_protected_push_reason(policy: Policy, git_root: Path, detail: str) -> str:
    """The refusal used OUTSIDE the registry clone.

    It may not reuse the shared-clone wording. That message opens by naming
    the directory "the shared registry clone" and closes by advising the
    reader to move to a worktree -- said to a lane standing in its worktree,
    both halves are false and the advice is the loop OMN-18974 AC-4 exists
    to remove. This one names the real directory and recommends something
    the reader can actually do from it.
    """
    return (
        f"BLOCKED: `git push --force` in {git_root} ({policy.ticket}, "
        f"{policy.rule}). This is your own tree and almost everything in it "
        f"is your business -- but {detail}. To disable this guard: onex "
        f"hooks disable {GATE_BIT_NAME}"
    )


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


# ---------------------------------------------------------------------------
# The dirty-path restore arm (OMN-18874)
# ---------------------------------------------------------------------------

#: Environment variables that would point a probe at a different repository
#: than the one resolved from the command. Scrubbed from every probe.
_GIT_LOCATION_ENV: Final[frozenset[str]] = frozenset(
    {
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_COMMON_DIR",
        "GIT_NAMESPACE",
        "GIT_PREFIX",
    }
)

#: Global flags that make git write a different repository or tree than the
#: one this guard resolves from `-C` and the cwd.
_RELOCATING_GLOBAL_FLAGS: Final[frozenset[str]] = frozenset(
    {"--git-dir", "--work-tree", "--namespace"}
)

#: `git checkout` options that make it a branch operation, not a restore.
_CHECKOUT_BRANCH_FLAGS: Final[frozenset[str]] = frozenset({"--orphan", "--detach"})

_PATHSPEC_FROM_FILE: Final[str] = "--pathspec-from-file"


class _Indeterminate(Exception):
    """Whether a restore would discard work cannot be determined."""


@dataclass(frozen=True)
class _RestoreShape:
    source: str | None  # a tree-ish, or None when the source is the index
    paths: tuple[str, ...]
    writes_index: bool
    writes_worktree: bool
    #: overlay mode leaves a path the source does not carry untouched;
    #: no-overlay removes it. `checkout` defaults to overlay, `restore` not.
    overlay: bool
    #: OMN-17427. The source is a tree-ish the shell computes (`$SHA`,
    #: `$(git rev-parse ...)`), so what it carries is unknown. Every named
    #: path is then assumed overwritten with content the guard cannot credit
    #: as a copy of what is being lost.
    source_unknown: bool = False


def resolve_worktree_roots(
    policy: Policy, environ: dict[str, str] | None = None
) -> tuple[Path, ...]:
    """Declared worktrees roots that resolve to a directory, in order.

    A value that does not resolve to a directory is ignored rather than
    trusted, as for the registry root.
    """
    env = os.environ if environ is None else environ
    roots: list[Path] = []
    for name in policy.worktree_root_envs:
        raw = env.get(name)
        if not raw:
            continue
        try:
            candidate = Path(raw).resolve()
        except OSError:
            continue
        if candidate.is_dir() and candidate not in roots:
            roots.append(candidate)
    return tuple(roots)


def _restore_in_scope(
    git_root: Path,
    registry_root: Path | None,
    worktree_roots: tuple[Path, ...],
    policy: Policy,
) -> bool:
    """Is this git root one the fleet works in?

    Anything under the registry root or a declared worktrees root, the
    registry clone itself found by its markers, and any git WORKTREE at all
    -- the OMN-17334 stash guard's scope, so a hook process with no
    OMNI_HOME still guards the place lanes actually edit. A plain clone
    elsewhere is out of scope.
    """
    for base in (registry_root, *worktree_roots):
        if base is None:
            continue
        try:
            git_root.relative_to(base)
        except ValueError:
            continue
        return True
    if _is_registry_root(git_root, registry_root, policy):
        return True
    try:
        return (git_root / ".git").is_file()
    except OSError:
        # Unreadable: fail closed and treat it as a worktree.
        return True


def _run_git(
    args: list[str], cwd: Path, timeout: float, stdin: bytes | None = None
) -> subprocess.CompletedProcess[bytes]:
    """Run one read-only git probe, or raise GitProbeError.

    Location variables are scrubbed so the probe reads the repository the
    command names, and GIT_OPTIONAL_LOCKS=0 keeps `git status` from taking
    the index lock a peer's commit may be waiting on.
    """
    env = {k: v for k, v in os.environ.items() if k not in _GIT_LOCATION_ENV}
    env["GIT_OPTIONAL_LOCKS"] = "0"
    try:
        return subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            env=env,
            input=stdin,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise GitProbeError(
            f"`git {args[0]}` did not answer within {timeout:g}s"
        ) from exc
    except OSError as exc:
        raise GitProbeError(f"`git {args[0]}` could not be started ({exc})") from exc


def _probe_failure(
    result: subprocess.CompletedProcess[bytes], what: str
) -> GitProbeError:
    detail = result.stderr.decode("utf-8", "replace").strip()[:200]
    return GitProbeError(f"`git {what}` exited {result.returncode}: {detail}")


def _is_revision(token: str, cwd: Path, policy: Policy) -> bool:
    """Does git read this checkout operand as a tree-ish rather than a path?"""
    result = _run_git(
        ["rev-parse", "--verify", "-q", "--end-of-options", f"{token}^{{tree}}"],
        cwd,
        policy.git_probe_timeout_seconds,
    )
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    raise _probe_failure(result, "rev-parse")


def _checkout_shape(
    args: list[str], policy: Policy, is_revision: Any
) -> _RestoreShape | None:
    """The restore a `git checkout` performs, or None when it is not one."""
    if "--" in args:
        split = args.index("--")
        before, after, has_separator = args[:split], args[split + 1 :], True
    else:
        before, after, has_separator = args, [], False
    operands: list[str] = []
    overlay = True
    idx = 0
    while idx < len(before):
        tok = before[idx]
        if tok in policy.branch_creation_flags or tok in _CHECKOUT_BRANCH_FLAGS:
            return None
        if tok == "--no-overlay":
            overlay = False
        elif tok == "--overlay":
            overlay = True
        elif tok == "--conflict":
            idx += 1
        elif tok.startswith("-") and tok != "-":
            pass
        else:
            operands.append(tok)
        idx += 1
    if has_separator:
        if not after:
            return None
        source = operands[0] if operands else None
        paths = tuple(after)
    else:
        if not operands or operands[0] == "-":
            return None
        if is_revision(operands[0]):
            if len(operands) == 1:
                # A branch switch. git refuses one that would overwrite
                # local changes unless forced; it is not a path restore.
                return None
            source, paths = operands[0], tuple(operands[1:])
        else:
            source, paths = None, tuple(operands)
    return _RestoreShape(
        source=source,
        paths=paths,
        writes_index=source is not None,
        writes_worktree=True,
        overlay=overlay,
    )


def _restore_shape(args: list[str]) -> _RestoreShape | None:
    """The restore a `git restore` performs, or None when it names no path."""
    staged = worktree = overlay = False
    source: str | None = None
    paths: list[str] = []
    after_separator = False
    idx = 0
    while idx < len(args):
        tok = args[idx]
        if after_separator:
            paths.append(tok)
        elif tok == "--":
            after_separator = True
        elif tok in ("-s", "--source"):
            source = args[idx + 1] if idx + 1 < len(args) else None
            idx += 1
        elif tok.startswith("--source="):
            source = tok.split("=", 1)[1]
        elif tok == "--staged":
            staged = True
        elif tok == "--worktree":
            worktree = True
        elif tok == "--overlay":
            overlay = True
        elif tok == "--no-overlay":
            overlay = False
        elif tok == "--conflict":
            idx += 1
        elif tok.startswith("--"):
            pass
        elif tok.startswith("-") and len(tok) > 1:
            cluster = tok[1:]
            for pos, letter in enumerate(cluster):
                if letter == "s":
                    rest = cluster[pos + 1 :]
                    if rest:
                        source = rest
                    else:
                        source = args[idx + 1] if idx + 1 < len(args) else None
                        idx += 1
                    break
                if letter == "S":
                    staged = True
                elif letter == "W":
                    worktree = True
        else:
            paths.append(tok)
        idx += 1
    if not paths:
        return None
    if source is None and staged:
        source = "HEAD"
    return _RestoreShape(
        source=source,
        paths=tuple(paths),
        writes_index=staged,
        writes_worktree=worktree or not staged,
        overlay=overlay,
    )


def _parse_restore(
    invocation: _GitInvocation, policy: Policy, is_revision: Any
) -> _RestoreShape | None:
    args = list(invocation.args)
    if any(
        arg == _PATHSPEC_FROM_FILE or arg.startswith(f"{_PATHSPEC_FROM_FILE}=")
        for arg in args
    ):
        raise _Indeterminate(
            "it reads its paths from --pathspec-from-file, which this guard "
            "does not open"
        )
    if invocation.subcommand == "checkout":
        return _checkout_shape(args, policy, is_revision)
    return _restore_shape(args)


def _is_shell_computed(operand: str) -> bool:
    """Does the shell compute this operand, so the command text cannot name it?

    `{a,b}` is brace expansion: git would be asked about a literal pathspec
    that matches nothing, while the shell hands the real command both files.
    Globs are left alone -- git's own pathspec globbing matches a superset of
    what the shell expands.
    """
    if isinstance(operand, _ShellWord) and operand.word.is_plain:
        return False
    return (
        "$" in operand
        or "`" in operand
        or operand.startswith("~")
        or ("{" in operand and "}" in operand)
    )


def _read_operand(operand: str, scope: Scope) -> str:
    """The operand as the shell will hand it to git, when it can be read.

    OMN-17427. An operand naming a variable the environment or an earlier
    assignment in this command resolves to one word is that word. Anything
    else is returned unchanged and is left to ``_check_computed_operands``.
    """
    if "$" not in operand and not operand.startswith("~"):
        return operand
    value = _expand_path(operand, scope)
    if value is None or (_word(operand).splits and len(value.split()) != 1):
        return operand
    return _ShellWord(Word((WordPart(value, "literal"),)))


def _check_computed_operands(shape: _RestoreShape) -> _RestoreShape:
    """Refuse unresolved restore paths; an unknown source credits no saved work.

    OMN-19380. Resolvable paths have already passed through ``_read_operand``
    and the shared expansion helper. Probing the whole tree for an unresolved
    path cannot establish which paths the shell will hand to git.
    """
    for path in shape.paths:
        if _is_shell_computed(path):
            raise _Indeterminate(
                f"the restore path {path!r} cannot be resolved by the shared "
                "shell expansion helper"
            )
    source_unknown = shape.source is not None and _is_shell_computed(shape.source)
    return replace(shape, source_unknown=source_unknown)


def _parse_porcelain(raw: bytes) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    seen: set[str] = set()
    for entry in raw.decode("utf-8", "surrogateescape").split("\0"):
        if len(entry) < 4:
            continue
        status, path = entry[:2], entry[3:]
        if path not in seen:
            seen.add(path)
            entries.append((status, path))
    return entries


def _index_blobs(
    git_root: Path, paths: list[str], timeout: float
) -> tuple[dict[str, str], set[str]]:
    result = _run_git(
        ["--literal-pathspecs", "ls-files", "-s", "-z", "--", *paths],
        git_root,
        timeout,
    )
    if result.returncode != 0:
        raise _probe_failure(result, "ls-files")
    blobs: dict[str, str] = {}
    conflicted: set[str] = set()
    for entry in result.stdout.decode("utf-8", "surrogateescape").split("\0"):
        if "\t" not in entry:
            continue
        meta, path = entry.split("\t", 1)
        fields = meta.split()
        if len(fields) != 3:
            continue
        if fields[2] == "0":
            blobs[path] = fields[1]
        else:
            conflicted.add(path)
    return blobs, conflicted


def _tree_blobs(
    git_root: Path, ref: str, paths: list[str], timeout: float
) -> dict[str, str] | None:
    """Blob ids the tree-ish carries for these paths, or None if it is absent."""
    result = _run_git(
        ["--literal-pathspecs", "ls-tree", "-r", "-z", ref, "--", *paths],
        git_root,
        timeout,
    )
    if result.returncode != 0:
        return None
    blobs: dict[str, str] = {}
    for entry in result.stdout.decode("utf-8", "surrogateescape").split("\0"):
        if "\t" not in entry:
            continue
        meta, path = entry.split("\t", 1)
        fields = meta.split()
        if len(fields) == 3:
            blobs[path] = fields[2]
    return blobs


def _worktree_blobs(git_root: Path, paths: list[str], timeout: float) -> dict[str, str]:
    """Blob ids the working-tree files WOULD have; nothing is written."""
    present = [
        p for p in paths if (git_root / p).is_file() or (git_root / p).is_symlink()
    ]
    if not present:
        return {}
    result = _run_git(
        ["hash-object", "--stdin-paths"],
        git_root,
        timeout,
        stdin=("\n".join(present) + "\n").encode("utf-8", "surrogateescape"),
    )
    if result.returncode != 0:
        raise _probe_failure(result, "hash-object")
    hashes = result.stdout.decode("ascii", "replace").split()
    if len(hashes) != len(present):
        raise GitProbeError(
            f"`git hash-object` answered {len(hashes)} ids for {len(present)} paths"
        )
    return dict(zip(present, hashes, strict=True))


def _paths_losing_work(
    shape: _RestoreShape, target_dir: Path, git_root: Path, policy: Policy
) -> list[tuple[str, list[str]]]:
    """Each named path whose overwritten content exists nowhere else.

    Content is safe when the restore's own source, or one of the declared
    reachable refs, carries exactly that blob for that path -- then nothing
    is lost, even over a path that differs from HEAD, which is the Rule 17
    committed-first sequence.
    """
    timeout = policy.git_probe_timeout_seconds
    status = _run_git(
        [
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
            "--no-renames",
            "--",
            *shape.paths,
        ],
        target_dir,
        timeout,
    )
    if status.returncode != 0:
        raise _probe_failure(status, "status")
    dirty = _parse_porcelain(status.stdout)
    if not dirty:
        return []
    if len(dirty) > policy.restore_max_dirty_paths:
        raise _Indeterminate(
            f"{len(dirty)} matched paths carry changes, more than the "
            f"{policy.restore_max_dirty_paths} this guard evaluates"
        )
    paths = [path for _, path in dirty]
    if any("\n" in path for path in paths):
        raise _Indeterminate("a matched path contains a newline")
    index_blobs, conflicted = _index_blobs(git_root, paths, timeout)
    worktree_blobs = _worktree_blobs(git_root, paths, timeout)
    if shape.source_unknown:
        # Every dirty path is assumed rewritten from a tree whose content
        # matches nothing, so only a declared reachable ref can save it.
        source_blobs = dict.fromkeys(paths, "")
    elif shape.source is None:
        source_blobs = index_blobs
    else:
        read = _tree_blobs(git_root, shape.source, paths, timeout)
        if read is None:
            raise _Indeterminate(
                f"its source {shape.source!r} could not be read as a tree"
            )
        source_blobs = read
    reachable_maps = [
        blobs
        for ref in policy.restore_reachable_refs
        if (blobs := _tree_blobs(git_root, ref, paths, timeout)) is not None
    ]

    lost: list[tuple[str, list[str]]] = []
    for _, path in dirty:
        tracked = path in index_blobs or path in conflicted
        in_source = path in source_blobs
        conflict_rewrite = shape.source is None and path in conflicted
        if not (in_source or conflict_rewrite or (tracked and not shape.overlay)):
            # Overlay mode never touches a path its source does not carry.
            continue
        reachable = {blobs[path] for blobs in reachable_maps if path in blobs}
        if in_source:
            reachable.add(source_blobs[path])
        kinds: list[str] = []
        worktree_blob = worktree_blobs.get(path)
        index_blob = index_blobs.get(path)
        if shape.writes_worktree and worktree_blob and worktree_blob not in reachable:
            if not tracked:
                kinds.append("untracked file")
            elif worktree_blob == index_blob:
                kinds.append("staged change")
            else:
                kinds.append("unstaged edit")
        if (
            shape.writes_index
            and index_blob
            and index_blob not in reachable
            and (shape.writes_worktree or index_blob != worktree_blob)
            and "staged change" not in kinds
        ):
            kinds.append("staged change")
        if kinds:
            lost.append((path, kinds))
    return lost


def _render_restore_reason(
    policy: Policy,
    invocation: _GitInvocation,
    git_root: Path,
    lost: list[tuple[str, list[str]]],
) -> str:
    shown = "; ".join(f"{path} ({', '.join(kinds)})" for path, kinds in lost[:5])
    if len(lost) > 5:
        shown += f"; and {len(lost) - 5} more"
    refs = ", ".join(policy.restore_reachable_refs)
    return (
        f"BLOCKED: `git {invocation.subcommand}` in {git_root} would discard "
        f"uncommitted work ({policy.restore_ticket}, {policy.restore_rule}). "
        "These paths hold content that exists nowhere else -- not in the "
        f"restore's source and not in {refs}: {shown}. A path-scoped restore "
        "returns the file to the reference, not to what is in your working "
        "tree; it prints nothing, exits 0, and a working tree that was never "
        "committed has no reflog to recover it from. Four lanes lost work "
        "exactly this way (OMN-18566, OMN-18863, OMN-18992, OMN-19237). "
        f"Instead: {policy.restore_safe_alternatives}. A restore over a clean "
        f"path is never refused. To disable this guard: onex hooks disable "
        f"{GATE_BIT_NAME}"
    )


def _render_restore_indeterminate(
    policy: Policy, invocation: _GitInvocation, why: str
) -> str:
    return (
        f"BLOCKED: `git {invocation.subcommand}` is a path-scoped restore, and "
        "whether it would discard uncommitted work could not be determined: "
        f"{why} ({policy.restore_ticket}, {policy.restore_rule}). "
        "Remedy: pass literal paths, or commit first and restore by path per "
        "Operating Rule 17. An "
        "unverifiable restore is refused, never assumed safe, because the "
        "loss it risks is silent and unrecoverable. Instead: "
        f"{policy.restore_safe_alternatives}. Or name each path literally, "
        "from a directory the guard can resolve (an absolute -C <path>, or a "
        "literal cd), and a restore over a clean path passes. To disable this "
        f"guard: onex hooks disable {GATE_BIT_NAME}"
    )


def _assigns_git_location(tokens: list[str]) -> bool:
    """Does this segment set a git location variable for what it runs?

    Covers `GIT_DIR=x git ...`, `env GIT_WORK_TREE=x git ...`, and a bare
    `export GIT_DIR=x` or `GIT_DIR=x` segment that sets it for the rest of
    the command. `_strip_wrappers` drops these tokens, and the probes scrub
    the same variables, so without this the probe would read one repository
    while the command wrote another.
    """
    for tok in tokens:
        name = tok.split("=", 1)[0]
        if _ASSIGNMENT.match(tok) and name in _GIT_LOCATION_ENV:
            return True
        if _ASSIGNMENT.match(tok) or os.path.basename(tok) in (*_WRAPPERS, "export"):
            continue
        break
    return False


def _restore_refusal(
    invocation: _GitInvocation,
    policy: Policy,
    target_dir: Path,
    target_known: bool,
    registry_root: Path | None,
    worktree_roots: tuple[Path, ...],
    scope: Scope,
    env_relocated: bool = False,
) -> str | None:
    """Why this path restore is refused, or None when it discards nothing."""
    if invocation.subcommand not in policy.restore_subcommands:
        return None
    invocation = replace(
        invocation, args=tuple(_read_operand(arg, scope) for arg in invocation.args)
    )
    relocated = env_relocated or any(
        flag.split("=", 1)[0] in _RELOCATING_GLOBAL_FLAGS
        for flag in invocation.global_flags
    )
    git_root: Path | None = None
    if target_known and not relocated:
        git_root = _find_git_root(target_dir)
        if git_root is None:
            # Not a repository: git itself refuses the command.
            return None
        if not _restore_in_scope(git_root, registry_root, worktree_roots, policy):
            return None

    def is_revision(token: str) -> bool:
        if git_root is None:
            raise _Indeterminate(
                f"whether `git checkout {token}` switches branches or restores "
                "a path depends on a repository this guard could not resolve "
                "(to switch branches, `git switch` is unambiguous and is not "
                "evaluated by this arm)"
            )
        return _is_revision(token, target_dir, policy)

    try:
        shape = _parse_restore(invocation, policy, is_revision)
        if shape is None:
            return None
        if relocated:
            raise _Indeterminate(
                "it carries --git-dir, --work-tree or --namespace, or sets "
                "GIT_DIR, GIT_WORK_TREE or GIT_INDEX_FILE, so the tree it "
                "writes is not the one resolved from the command"
            )
        if git_root is None:
            raise _Indeterminate(
                "an earlier cd, or its -C operand, could not be resolved, so "
                "neither can the tree it writes"
            )
        shape = _check_computed_operands(shape)
        lost = _paths_losing_work(shape, target_dir, git_root, policy)
    except _Indeterminate as exc:
        return _render_restore_indeterminate(policy, invocation, str(exc))
    except GitProbeError as exc:
        return _render_restore_indeterminate(
            policy, invocation, f"a git probe failed ({exc})"
        )
    if not lost:
        return None
    return _render_restore_reason(policy, invocation, git_root, lost)


def _cd_operand_is_absolute(tokens: list[str], policy: Policy, scope: Scope) -> bool:
    """Does this `cd` land somewhere independent of the directory before it?"""
    operands = [tok for tok in _strip_wrappers(tokens)[1:] if not tok.startswith("-")]
    if not operands:
        return True
    expanded = _expand_path(operands[0], scope)
    return expanded is not None and Path(expanded).is_absolute()


def _is_directory_change(tokens: list[str], policy: Policy) -> bool:
    stripped = _strip_wrappers(tokens)
    return bool(stripped) and (
        os.path.basename(stripped[0]) in policy.directory_changing_programs
    )


def _target_is_absolute(invocation: _GitInvocation, scope: Scope) -> bool:
    if invocation.directories:
        try:
            return git_directory(list(invocation.directories), scope, None) is not None
        except UnresolvableWord:
            return False
    raw = _expand_path(invocation.target_arg, scope) if invocation.target_arg else None
    return raw is not None and Path(raw).is_absolute()


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


def _peel_grouping(segment: list[str]) -> tuple[list[str], int, int]:
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
        if head in {"{", "do"}:
            # OMN-19380: a loop body begins with do before its first command.
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


def _track_assignments(segment: list[str], scope: Scope) -> None:
    """Record ``NAME=value`` in ``scope`` when the value is fully resolvable.

    OMN-19852. The names a command assigns start unresolvable (the hook's own
    environment holds the value from BEFORE the command). A pure assignment
    segment -- ``WT=<path>`` or ``export WT=<path>`` -- whose value expands
    from what is already known gives the name its real value from that point
    on, so an assignment of a worktree path followed by ``git -C "$WT"`` is
    judged where git will run. A value with a substitution, an unset or
    unresolved variable or a glob stays unresolvable. A segment with a
    command word (``WT=x <command>``) assigns only for that one command and
    is not tracked.
    """
    if isinstance(scope, ChainMap):
        apply_assignments([_word(t) for t in segment], scope, scope.maps[0])


# ---------------------------------------------------------------------------
# The lane git-fetch arm (OMN-20495)
# ---------------------------------------------------------------------------
# A git worktree's `.git` is a file pointing at its canonical clone, so the
# worktree shares every ref of that clone, refs/remotes/origin/* included. The
# canonical-clone sync (OMN-19607: launchd ai.omninode.canonical-clone-sync
# every 180 s, plus the PostToolUse merge trigger) fetches every canonical
# clone, so a worktree already sees the new origin/<branch> without fetching.
# A lane's own fetch is redundant GitHub traffic that races the sync for the
# same tracking ref. Operator request 2026-10-04 ~01:35Z; RULING
# 2026-10-04T01:33:03Z lane=orchestrator (OMN-19470).
#
# Refused: `git fetch`, `git pull`, `git ls-remote` and `git remote update`
# reading a GitHub remote, in a lane context -- a lane variable set in the
# hook environment (ONEX_LANE, which remote lanes carry), or the payload cwd,
# a `cd` target or the `-C` target under a lane workdir (an `omni_worktrees`
# or `lab-run/runs` path segment, or a declared worktrees root). With no
# remote named, the branch's remote (else origin) is read; `--all` and a bare
# `remote update` read every remote. The refusal names the sanctioned refresh,
# canonical_clone_sync.py refresh, which fetches under the sync's own lock.
#
# Not refused: push; a non-GitHub remote (a lab mirror, a local path); any of
# these outside a lane; and a process whose HOOK environment carries an
# allow marker (the PR watcher, the sync). An assignment typed in front of the
# command is not the hook environment. Nothing is rewritten: it refuses, or
# says nothing. Inside a lane, a remote that cannot be resolved (a computed
# word, an unknown name) is refused, never assumed safe; outside one nothing
# is read at all.

#: The refresh a refusal points at, beside this module in every install.
CLONE_SYNC_ENGINE: Final[Path] = (
    Path(__file__).resolve().parent / "canonical_clone_sync.py"
)
FETCH_LOG_NAME: Final[str] = "git-fetch-guard.log"

_FETCH_VALUE_FLAGS: Final[dict[str, frozenset[str]]] = {
    "fetch": frozenset(
        {
            "--depth",
            "--deepen",
            "--shallow-since",
            "--shallow-exclude",
            "--refmap",
            "-o",
            "--server-option",
            "--upload-pack",
            "--negotiation-tip",
            "-j",
            "--jobs",
            "--recurse-submodules-default",
            "--filter",
            "--submodule-prefix",
        }
    ),
    "pull": frozenset(
        {
            "--depth",
            "--deepen",
            "--shallow-since",
            "--shallow-exclude",
            "-o",
            "--server-option",
            "--upload-pack",
            "--negotiation-tip",
            "-j",
            "--jobs",
            "-s",
            "--strategy",
            "-X",
            "--strategy-option",
            "--cleanup",
        }
    ),
    "ls-remote": frozenset({"--upload-pack", "-o", "--server-option", "--sort"}),
    "remote": frozenset(),
}
_SCP_LIKE: Final[re.Pattern[str]] = re.compile(r"^(?:[^@/\s]+@)?([^:/\s]+):(?!//)")
_URL_HOST: Final[re.Pattern[str]] = re.compile(
    r"^[a-z][a-z0-9+.-]*://(?:[^@/\s]+@)?([^:/\s]+)", re.I
)
_CONFIG_SECTION: Final[re.Pattern[str]] = re.compile(
    r'^\[\s*([A-Za-z0-9.-]+)(?:\s+"((?:[^"\\]|\\.)*)")?\s*\]\s*$'
)
_GITHUB_SLUG: Final[re.Pattern[str]] = re.compile(
    r"github\.com[:/]+([^/\s:]+)/([^/\s]+?)(?:\.git)?/*$", re.I
)


def _drop_timeout(tokens: list[str]) -> list[str]:
    """``timeout [opts] DURATION cmd...`` as ``cmd...``; anything else unchanged."""
    words = _strip_wrappers(tokens)
    if not words or os.path.basename(words[0]) != "timeout":
        return tokens
    rest = words[1:]
    while rest and rest[0].startswith("-"):
        rest = rest[1:]
    return rest[1:]


def _git_common_dir(start: Path) -> tuple[Path, Path | None] | None:
    """(common dir, this worktree's own git dir) of the repo holding ``start``."""
    current = start
    for _ in range(64):
        marker = current / ".git"
        if marker.is_dir():
            return marker, marker
        if marker.is_file():
            text = marker.read_text(encoding="utf-8", errors="replace").strip()
            if not text.startswith("gitdir:"):
                return None
            gitdir = Path(text[len("gitdir:") :].strip())
            if not gitdir.is_absolute():
                gitdir = (current / gitdir).resolve()
            commondir = gitdir / "commondir"
            if commondir.is_file():
                rel = Path(commondir.read_text(encoding="utf-8").strip())
                return (rel if rel.is_absolute() else (gitdir / rel).resolve()), gitdir
            return gitdir, gitdir
        if (current / "HEAD").is_file() and (current / "objects").is_dir():
            return current, None  # a bare repository
        if current.parent == current:
            return None
        current = current.parent
    return None


@dataclass
class _RemoteConfig:
    sections: dict[tuple[str, str], dict[str, list[str]]]
    head_branch: str | None
    where: Path

    def remotes(self) -> list[str]:
        return [sub for (sec, sub) in self.sections if sec == "remote" and sub]

    def url(self, name: str) -> str | None:
        values = self.sections.get(("remote", name), {}).get("url")
        return values[-1] if values else None

    def group(self, name: str) -> list[str] | None:
        values = self.sections.get(("remotes", ""), {}).get(name.lower())
        return [n for v in values for n in v.split()] if values else None

    def default_remote(self) -> str:
        if self.head_branch:
            values = self.sections.get(("branch", self.head_branch), {}).get("remote")
            if values and values[-1] and values[-1] != ".":
                return values[-1]
        return "origin"


def _read_remote_config(directory: Path) -> _RemoteConfig | None:
    """The remotes of the repository holding ``directory``, read from disk."""
    found = _git_common_dir(directory)
    if found is None:
        return None
    common, own = found
    sections: dict[tuple[str, str], dict[str, list[str]]] = {}
    current: dict[str, list[str]] | None = None
    text = (common / "config").read_text(encoding="utf-8", errors="replace")
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line[0] in "#;":
            continue
        match = _CONFIG_SECTION.match(line)
        if match:
            current = sections.setdefault(
                (match.group(1).lower(), match.group(2) or ""), {}
            )
            continue
        if current is None or "=" not in line:
            continue
        name, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] == '"':
            value = value[1:-1]
        current.setdefault(name.strip().lower(), []).append(value)
    head_branch = None
    try:
        head = ((own or common) / "HEAD").read_text(encoding="utf-8").strip()
    except OSError:
        head = ""
    if head.startswith("ref: refs/heads/"):
        head_branch = head[len("ref: refs/heads/") :]
    return _RemoteConfig(sections=sections, head_branch=head_branch, where=common)


def _remote_host(url: str) -> str | None:
    match = _URL_HOST.match(url)
    if match:
        return match.group(1).lower()
    if "://" in url or url.startswith(("/", ".", "~")):
        return None
    match = _SCP_LIKE.match(url)
    return match.group(1).lower() if match else None


def _names_a_location(word: str) -> bool:
    return (
        "://" in word
        or word.startswith(("/", ".", "~"))
        or _SCP_LIKE.match(word) is not None
    )


def _fetch_operands(subcommand: str, args: list[str]) -> tuple[list[str], bool]:
    """(remote words named, reads every remote) for one fetch-family call."""
    value_flags = _FETCH_VALUE_FLAGS.get(subcommand.split(maxsplit=1)[0], frozenset())
    positionals: list[str] = []
    every = multiple = skip = after_dashdash = False
    for arg in args:
        if skip:
            skip = False
            continue
        if not after_dashdash and arg == "--":
            after_dashdash = True
            continue
        if not after_dashdash and arg.startswith("-") and arg != "-":
            name = arg.split("=", 1)[0]
            if name == "--all":
                every = True
            elif name == "--multiple":
                multiple = True
            elif name in value_flags and "=" not in arg:
                skip = True
            continue
        positionals.append(arg)
    if subcommand == "remote update":
        return positionals, not positionals
    if every:
        return [], True
    if multiple:
        return positionals, False
    return positionals[:1], False


def _is_lane_path(path: Path, policy: Policy, worktree_roots: tuple[Path, ...]) -> bool:
    texts = {str(path)}
    try:
        texts.add(str(path.resolve()))
    except OSError:
        pass
    for text in texts:
        probe = text.rstrip("/") + "/"
        if any(marker in probe for marker in policy.fetch_lane_path_markers):
            return True
        if any(
            probe.startswith(str(root).rstrip("/") + "/") for root in worktree_roots
        ):
            return True
    return False


def _lane_name(policy: Policy, environ: Mapping[str, str]) -> str:
    for name in policy.fetch_lane_envs:
        if environ.get(name):
            return environ[name]
    return ""


def _fetch_refusal_text(
    policy: Policy, verb: str, repo: str, detail: str, branch: str | None
) -> str:
    refresh = f"python3 {CLONE_SYNC_ENGINE} refresh {repo or '<owner>/<repo>'} --wait"
    if branch:
        refresh += f" --branch {branch}"
    return (
        f"BLOCKED ({policy.fetch_ticket}): `git {verb}` against GitHub from a lane. "
        f"{detail}origin refs here are shared with the canonical clone and kept "
        "current by canonical-clone-sync (merge-triggered + 3-min); use "
        f"origin/<branch> as is, or run `{refresh}`. git push and non-GitHub "
        f"remotes are not gated. To disable this guard: onex hooks disable "
        f"{GATE_BIT_NAME}"
    )


def _branch_hint(subcommand: str, args: list[str], named: int) -> str | None:
    if subcommand not in ("fetch", "pull") or not named:
        return None
    positionals = [a for a in args if not a.startswith("-")]
    for spec in positionals[named:]:
        src = spec.lstrip("+").split(":", 1)[0].removeprefix("refs/heads/")
        if src and not src.startswith("refs/"):
            return src
    return None


def _lane_fetch_refusal(
    invocation: _GitInvocation,
    policy: Policy,
    payload_cwd: Path,
    effective_cwd: Path,
    cwd_known: bool,
    scope: Scope,
    worktree_roots: tuple[Path, ...],
    environ: Mapping[str, str],
) -> Decision | None:
    """The OMN-20495 refusal for one fetch-family call, or None to let it run."""
    subcommand = invocation.subcommand
    args = list(invocation.args)
    if subcommand == "remote":
        named = [a for a in args if not a.startswith("-")]
        if not named or named[0] != "update":
            return None
        subcommand = "remote update"
        args = args[args.index("update") + 1 :]
    if any(environ.get(k) == v for k, v in policy.fetch_allow_env):
        return None
    target: Path | None = effective_cwd if cwd_known else None
    if invocation.directories:
        try:
            resolved = git_directory(list(invocation.directories), scope, target)
            target = Path(resolved) if resolved is not None else None
        except UnresolvableWord:
            target = None
    elif invocation.target_arg is not None:
        expanded = _expand_path(invocation.target_arg, scope)
        if expanded is None:
            target = None
        elif Path(expanded).is_absolute():
            target = Path(expanded)
        elif target is not None:
            target = target / expanded
    lane = (
        bool(_lane_name(policy, environ))
        or _is_lane_path(payload_cwd, policy, worktree_roots)
        or (cwd_known and _is_lane_path(effective_cwd, policy, worktree_roots))
        or (target is not None and _is_lane_path(target, policy, worktree_roots))
    )
    if not lane:
        return None

    def refuse(detail: str, repo: str = "", branch: str | None = None) -> Decision:
        return Decision(
            blocked=True,
            reason=_fetch_refusal_text(policy, subcommand, repo, detail, branch),
            fetch_verb=subcommand,
            fetch_repo=repo,
        )

    if target is None:
        return refuse(
            "Its directory (a `cd` or `-C` word) could not be resolved, so the "
            "remote it reads is unknown. "
        )
    words: list[str] = []
    for arg in args:
        expanded = _expand_path(arg, scope)
        if expanded is None:
            return refuse(
                f"Its argument `{arg}` could not be expanded, so whether it names "
                "GitHub is unknown. "
            )
        words.append(expanded)
    names, every = _fetch_operands(subcommand, words)
    needs_config = every or not names or not all(_names_a_location(n) for n in names)
    config = _read_remote_config(target) if needs_config else None
    if needs_config and config is None:
        return None  # not a repository: git fails a remote name here itself
    urls: list[tuple[str, str]] = []
    if every and config is not None:
        urls = [(n, config.url(n) or "") for n in config.remotes()]
    else:
        wanted = names or ([config.default_remote()] if config is not None else [])
        for name in wanted:
            if _names_a_location(name):
                urls.append((name, name))
                continue
            assert config is not None
            url = config.url(name)
            if url is not None:
                urls.append((name, url))
                continue
            group = config.group(name)
            if group is not None:
                urls.extend((g, config.url(g) or "") for g in group)
                continue
            return refuse(
                f"Remote `{name}` is not configured in {config.where}, so whether "
                "it is GitHub is unknown. "
            )
    for name, url in urls:
        host = _remote_host(url)
        if host is not None and host in policy.fetch_github_hosts:
            match = _GITHUB_SLUG.search(url.strip())
            repo = f"{match.group(1)}/{match.group(2)}" if match else ""
            return refuse(
                f"Remote `{name}` is {repo or url}. ",
                repo,
                _branch_hint(subcommand, words, len(names)),
            )
    return None


def _log_fetch_refusal(
    decision: Decision, policy: Policy, cwd: Path, environ: Mapping[str, str]
) -> None:
    """One TSV line per lane-fetch refusal, like the gh shim's call log: never argv."""
    state = environ.get("ONEX_STATE_DIR")
    if not state or not decision.fetch_verb:
        return
    lane, source = _lane_name(policy, environ), "env"
    if not lane:
        parts = cwd.parts
        if "omni_worktrees" in parts:
            idx = parts.index("omni_worktrees")
            lane, source = "/".join(parts[idx + 1 : idx + 3]), "worktree"
        else:
            lane, source = environ.get("CLAUDE_CODE_SESSION_ID") or "unknown", "session"
    host = environ.get("ONEX_LANE_HOST") or os.uname().nodename.split(".")[0]
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    fields = [stamp, lane, source, f"git {decision.fetch_verb}"]
    fields += [decision.fetch_repo or "-", host, "refused"]
    try:
        path = Path(state) / "logs" / FETCH_LOG_NAME
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write("\t".join(fields) + "\n")
    except OSError:
        pass


def evaluate_bash_command(
    command: str,
    policy: Policy,
    cwd: Path,
    registry_root: Path | None,
    worktree_roots: tuple[Path, ...] = (),
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

    scope = shadow(os.environ, shadowed_names(segments))
    effective_cwd = cwd
    # Whether effective_cwd is really where the shell will be. An
    # unresolvable `cd` leaves effective_cwd where it was, which keeps every
    # shared-tree refusal in force; the restore arm needs the real directory
    # and fails closed when it is not known (OMN-18874).
    cwd_known = True
    # A location variable the hook itself inherits, or one exported earlier
    # in this command, relocates every later git call.
    exported_relocation = any(os.environ.get(name) for name in _GIT_LOCATION_ENV)
    # OMN-19852. Each `(` saves the directory in force so a `cd` inside the
    # subshell cannot leak out of its `)`.
    subshell_stack: list[tuple[Path, bool]] = []
    pending_close = 0
    for raw_segment in segments:
        # A `)` takes effect after the segment that carries it.
        for _ in range(pending_close):
            if subshell_stack:
                effective_cwd, cwd_known = subshell_stack.pop()
        segment, opened, pending_close = _peel_grouping(raw_segment)
        subshell_stack.extend([(effective_cwd, cwd_known)] * opened)
        if not segment:
            continue
        _track_assignments(segment, scope)
        if _assigns_git_location(segment):
            stripped_program = _strip_wrappers(segment)
            if (
                not stripped_program
                or os.path.basename(stripped_program[0]) == "export"
            ):
                exported_relocation = True
                continue
        if _is_directory_change(segment, policy):
            moved_to = _resolve_cd_target(segment, policy, effective_cwd, scope)
            if moved_to is None:
                cwd_known = False
            else:
                cwd_known = cwd_known or _cd_operand_is_absolute(segment, policy, scope)
                effective_cwd = moved_to
            continue
        invocation = _parse_git(segment)
        fetch_call = invocation or _parse_git(_drop_timeout(segment))
        if fetch_call is not None and fetch_call.subcommand in policy.fetch_subcommands:
            fetched = _lane_fetch_refusal(
                fetch_call,
                policy,
                cwd,
                effective_cwd,
                cwd_known,
                scope,
                worktree_roots,
                os.environ,
            )
            if fetched is not None:
                return fetched
        if invocation is None:
            continue
        if invocation.subcommand not in policy.refused_subcommands:
            continue
        if invocation.directories:
            try:
                target_known = (
                    git_directory(
                        list(invocation.directories),
                        scope,
                        effective_cwd if cwd_known else None,
                    )
                    is not None
                )
            except UnresolvableWord:
                target_known = False
        elif invocation.target_arg is None:
            target_known = cwd_known
        else:
            target_known = _target_is_absolute(invocation, scope) or (
                cwd_known and _expand_path(invocation.target_arg, scope) is not None
            )
        if not target_known:
            # Unknown location cannot justify a mutation that could hit the registry.
            restore = _restore_refusal(
                invocation,
                policy,
                effective_cwd,
                False,
                registry_root,
                worktree_roots,
                scope,
                env_relocated=exported_relocation or _assigns_git_location(segment),
            )
            if restore is not None:
                return Decision(blocked=True, reason=restore)
            detail = _refusal_detail(
                invocation,
                policy,
                None,
                target_dir=effective_cwd,
                git_root=registry_root or effective_cwd,
            )
            if detail is not None:
                return Decision(
                    blocked=True,
                    reason=(
                        f"BLOCKED: `git {invocation.subcommand}` directory cannot be resolved; "
                        "the guard cannot determine whether it mutates the shared registry clone. "
                        "Prepare the directory in a separate Bash call or pass a literal absolute -C target"
                    ),
                )
        try:
            target_dir = _resolve_target_dir(invocation, effective_cwd, scope)
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
        in_registry = git_root is not None and _is_registry_root(
            git_root, registry_root, policy
        )
        if git_root is not None and in_registry:
            detail = _refusal_detail(
                invocation,
                policy,
                _read_current_branch(git_root),
                target_dir=target_dir,
                git_root=git_root,
            )
            if detail is not None:
                return Decision(
                    blocked=True,
                    reason=_render_block_reason(policy, invocation, git_root, detail),
                )
        elif git_root is not None:
            protected = _protected_push_detail(
                invocation, policy, git_root, registry_root
            )
            if protected is not None:
                return Decision(
                    blocked=True,
                    reason=_render_protected_push_reason(policy, git_root, protected),
                )
        # OMN-18874. Runs in every tree the fleet works in, the registry
        # clone included, after that clone's own refusals have had their say.
        restore = _restore_refusal(
            invocation,
            policy,
            target_dir,
            target_known,
            registry_root,
            worktree_roots,
            scope,
            env_relocated=exported_relocation or _assigns_git_location(segment),
        )
        if restore is not None:
            return Decision(blocked=True, reason=restore)
        if git_root is not None and not in_registry:
            notes.append(
                f"`git {invocation.subcommand}` targets {git_root}, which is "
                "not the shared registry clone"
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
    worktree_roots = resolve_worktree_roots(policy)

    try:
        decision = evaluate_bash_command(
            command, policy, cwd, registry_root, worktree_roots
        )
    except Exception as exc:  # noqa: BLE001 - fail-closed boundary, deliberate
        return _block(
            "BLOCKED: the OMN-18798 shared-tree git admission gate could not "
            f"evaluate this command ({exc}); an unverifiable shared-tree "
            "mutation is refused rather than assumed safe."
        )

    if decision.blocked:
        _log_fetch_refusal(decision, policy, cwd, os.environ)
        return _block(decision.reason)

    if decision.notes:
        print(json.dumps({"decision": "allow", "notes": list(decision.notes)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
