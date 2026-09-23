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
restore, a path operand the shell would expand, ``--pathspec-from-file``,
and a ``--git-dir``/``--work-tree`` override are all refused, because in
each case whether the command destroys work cannot be determined. Probes run
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
import shlex
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

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
    #: global flags before the subcommand, `-C` excluded; values of the
    #: separated two-token forms are folded in as `<flag>=<value>`.
    global_flags: tuple[str, ...] = ()


def _parse_git(tokens: list[str]) -> _GitInvocation | None:
    """Return the shape of one `git ...` segment, or None if it is not one."""
    stripped = _strip_wrappers(tokens)
    if not stripped or os.path.basename(stripped[0]) != "git":
        return None
    args = stripped[1:]
    target_arg: str | None = None
    global_flags: list[str] = []
    idx = 0
    while idx < len(args):
        tok = args[idx]
        if tok == "-C":
            if idx + 1 < len(args):
                target_arg = args[idx + 1]
            idx += 2
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
    return _GitInvocation(
        target_arg=target_arg,
        subcommand=args[idx],
        args=tuple(args[idx + 1 :]),
        global_flags=tuple(global_flags),
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


def _resolve_cd_target(tokens: list[str], policy: Policy, current: Path) -> Path | None:
    """The directory a `cd` segment moves to, or None when unresolvable.

    OMN-18974. The harness resets a Bash call's working directory between
    calls, so a lane working in its own worktree -- which Operating Rule 9
    requires -- reaches it with a `cd <worktree> &&` prefix and the payload
    cwd still at the registry root. A guard that reads only the payload cwd
    refuses that lane and then advises it to move to the worktree it is
    already in, which is the whole of the reported defect.

    Resolution is deliberately literal. `shlex` does not expand variables,
    so `cd "$WT"` arrives as an unexpanded token; `$OMNI_HOME`, `$HOME` and
    `~` are the three this guard can answer from its own environment, and
    anything else returns None. `cd` with no operand goes HOME. A relative
    operand resolves against the directory in force at that point, so a
    chain composes.
    """
    stripped = _strip_wrappers(tokens)
    if not stripped:
        return None
    if os.path.basename(stripped[0]) not in policy.directory_changing_programs:
        return None
    operands = [tok for tok in stripped[1:] if not tok.startswith("-")]
    if not operands:
        home = os.environ.get("HOME")
        return Path(home) if home else None
    if len(operands) > 1:
        return None
    target = operands[0]
    if target == "-":
        # `cd -` returns to the PREVIOUS directory, which this guard does
        # not track. Unresolvable rather than guessed.
        return None
    for name in ("OMNI_HOME", "ONEX_REGISTRY_ROOT", "HOME"):
        value = os.environ.get(name)
        if not value:
            continue
        for spelling in (f"${name}", "${" + name + "}"):
            if target == spelling:
                target = value
            elif target.startswith(spelling + os.sep):
                target = value + target[len(spelling) :]
    if target.startswith("~"):
        expanded = os.path.expanduser(target)
        if expanded.startswith("~"):
            return None
        target = expanded
    if "$" in target:
        # An unexpanded variable this guard cannot answer. Returning None
        # leaves the effective directory where it was, which is exactly the
        # behaviour before this change: nothing in the shared tree stops
        # being refused, and nothing outside it starts being refused.
        return None
    candidate = Path(target)
    if not candidate.is_absolute():
        candidate = current / candidate
    return Path(os.path.normpath(str(candidate)))


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


def _require_literal(shape: _RestoreShape) -> None:
    for operand in (*shape.paths, *([shape.source] if shape.source else [])):
        if "$" in operand or "`" in operand or operand.startswith("~"):
            raise _Indeterminate(
                f"the operand {operand!r} is expanded by the shell, so what "
                "it names cannot be read from the command"
            )


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
    if shape.source is None:
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
        if not (in_source or (tracked and not shape.overlay)):
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
        f"{why} ({policy.restore_ticket}, {policy.restore_rule}). An "
        "unverifiable restore is refused, never assumed safe, because the "
        "loss it risks is silent and unrecoverable. Instead: "
        f"{policy.restore_safe_alternatives}. Or name each path literally, "
        "from a directory the guard can resolve (an absolute -C <path>, or a "
        "literal cd), and a restore over a clean path passes. To disable this "
        f"guard: onex hooks disable {GATE_BIT_NAME}"
    )


def _restore_refusal(
    invocation: _GitInvocation,
    policy: Policy,
    target_dir: Path,
    target_known: bool,
    registry_root: Path | None,
    worktree_roots: tuple[Path, ...],
) -> str | None:
    """Why this path restore is refused, or None when it discards nothing."""
    if invocation.subcommand not in policy.restore_subcommands:
        return None
    relocated = any(
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
                "whether its first operand is a ref or a path depends on a "
                "repository this guard could not resolve"
            )
        return _is_revision(token, target_dir, policy)

    try:
        shape = _parse_restore(invocation, policy, is_revision)
        if shape is None:
            return None
        if relocated:
            raise _Indeterminate(
                "it carries --git-dir, --work-tree or --namespace, so the tree "
                "it writes is not the one resolved from the command"
            )
        if git_root is None:
            raise _Indeterminate(
                "an earlier cd, or its -C operand, could not be resolved, so "
                "neither can the tree it writes"
            )
        _require_literal(shape)
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


def _cd_operand_is_absolute(tokens: list[str], policy: Policy) -> bool:
    """Does this `cd` land somewhere independent of the directory before it?"""
    operands = [tok for tok in _strip_wrappers(tokens)[1:] if not tok.startswith("-")]
    if not operands:
        return True
    return operands[0].startswith(("/", "~", "$"))


def _is_directory_change(tokens: list[str], policy: Policy) -> bool:
    stripped = _strip_wrappers(tokens)
    return bool(stripped) and (
        os.path.basename(stripped[0]) in policy.directory_changing_programs
    )


def _target_is_literal(invocation: _GitInvocation) -> bool:
    arg = invocation.target_arg
    if arg is None:
        return False
    return Path(arg).is_absolute() and "$" not in arg and "`" not in arg


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

    effective_cwd = cwd
    # Whether effective_cwd is really where the shell will be. An
    # unresolvable `cd` leaves effective_cwd where it was, which keeps every
    # shared-tree refusal in force; the restore arm needs the real directory
    # and fails closed when it is not known (OMN-18874).
    cwd_known = True
    for segment in segments:
        if _is_directory_change(segment, policy):
            moved_to = _resolve_cd_target(segment, policy, effective_cwd)
            if moved_to is None:
                cwd_known = False
            else:
                cwd_known = cwd_known or _cd_operand_is_absolute(segment, policy)
                effective_cwd = moved_to
            continue
        invocation = _parse_git(segment)
        if invocation is None:
            continue
        if invocation.subcommand not in policy.refused_subcommands:
            continue
        if invocation.target_arg is None:
            target_known = cwd_known
        else:
            target_known = _target_is_literal(invocation) or (
                cwd_known
                and "$" not in invocation.target_arg
                and "`" not in invocation.target_arg
                and not invocation.target_arg.startswith("~")
            )
        try:
            target_dir = _resolve_target_dir(invocation, effective_cwd)
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
        return _block(decision.reason)

    if decision.notes:
        print(json.dumps({"decision": "allow", "notes": list(decision.notes)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
