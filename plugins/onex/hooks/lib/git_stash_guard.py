#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
r"""Fail-closed git-stash worktree admission gate (OMN-17334).

Why this exists
---------------
git's stash is ONE repo-wide stack. A git *worktree*'s ``.git`` is a FILE
pointing back at the parent clone's real git directory, so ``git stash push``
and ``git stash pop`` run inside a worktree operate on the SAME stash list
every other worktree of that clone shares -- and so does a canonical clone
directly under ``$OMNI_HOME``, where many concurrent agent lanes work in the
same tree.

The push/pop idiom lanes reach for to prove a test is RED-without-the-fix is
therefore unsafe by construction: a scoped ``git stash push -- <path>`` on a
tree with no changes to that path silently creates NO entry and still exits
0, so the paired ``git stash pop`` pops whatever is at ``stash@{0}`` --
another lane's work -- and even a push that DOES create an entry can lose a
race to a peer lane's own push/pop pair landing in between. Measured six
times by 2026-09-16 (rolling work ledger, existing=OMN-17334 rows on
2026-09-15T03:10Z, 2026-09-15T23:23Z, 2026-09-16T01:38Z among them), twice
destroying a peer lane's uncommitted work outright.

The safe, non-destructive alternative already recorded in the ledger by the
lane that hit the sixth occurrence never touches the shared stash ref at
all::

    git checkout origin/dev -- <path>
    <run the test>
    git checkout HEAD -- <path>

What this refuses, and what it deliberately does not
------------------------------------------------------
A shell segment whose program is ``git`` and whose stash subcommand is one of
the ``mutating_subcommands`` declared in ``git_stash_guard_policy.json`` is
refused when its target directory -- the argument of a ``-C <path>`` global
flag, or the command's own ``cwd`` when no ``-C`` is given -- resolves to
EITHER:

* a git **worktree** (walking up from the target, the first ``.git`` entry
  found is a regular FILE, not a directory), or
* a canonical clone directly under ``$OMNI_HOME`` (the first ``.git`` entry
  found is a directory, and its parent directory *is* ``$OMNI_HOME``).

There is deliberately NO escape entry -- no consent citation, no wildcard
shape, no exempt marker. A lane working in an ordinary git clone that is
neither of the above is outside both conditions and is never gated, and
``git stash list`` / ``git stash show`` are read-only against the stash ref
and are never gated either -- they are not allowlisted, they simply never
match the mutating-subcommand vocabulary declared in the policy.

Token matching, not substring matching
---------------------------------------
Each shell segment (split on ``;``, ``&&``, ``||``, ``|``, ``&``) is
tokenised with ``shlex`` and matched by program plus tokens, never by raw
text, for the same reason the OMN-17957 credential-rotation guard this module
is patterned on does it that way: a comment or a grep that merely *mentions*
"git stash pop" is not a stash invocation, and a raw-substring rule would
refuse both (workspace CLAUDE.md rule 15, the OCC#7213 shape).

Fail-closed boundary, stated deliberately
-------------------------------------------
* A command carrying no ``stash`` token never reaches this module -- the
  shell wrapper's pre-filter drops it. A bug here can never brick unrelated
  Bash traffic.
* A command that DOES carry ``stash`` vocabulary and cannot then be resolved
  -- an unreadable policy, an untokenisable segment, a target directory that
  cannot be stat'd -- is REFUSED. An unverifiable stash mutation is refused,
  never assumed safe.

What this cannot do, stated rather than implied
-------------------------------------------------
This guard only ever looks at the command and its resolved target directory.
It cannot see a *different* worktree of the same clone reaching for the same
stash ref at the same moment from outside this tool seam (a hand-typed
terminal session, for instance), and it does not address lanes racing each
other inside the SAME canonical clone with two different concurrent
sessions -- that shared-tree half is tracked separately as OMN-18433.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sys
from dataclasses import dataclass
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
]

DEFAULT_POLICY_PATH: Final[Path] = (
    Path(__file__).resolve().parent.parent / "config" / "git_stash_guard_policy.json"
)

#: The mask bit this guard is gated by. Named in every refusal so a lane that
#: believes the guard is wrong has a documented route that is not "work
#: around it". BORROWED, like the OMN-17957 credential-rotation guard's
#: PRE_TOOL_AUTHORIZATION_SHIM: a dedicated bit is unavailable (all 60
#: default-mask ordinals in hook_bits.sh are allocated), so this reuses
#: SWEEP_PREFLIGHT -- defined in hook_bits.sh (bit_defined: true, unlike
#: SKILL_SUBSTITUTION_GUARD, which is bit_defined: false and so can never
#: actually gate anything), whose namesake script
#: (pre_tool_use_sweep_preflight.sh) is on disk and UNREGISTERED, and which
#: no other registered script gates on. See the shell wrapper's header for
#: the full rationale.
GATE_BIT_NAME: Final[str] = "SWEEP_PREFLIGHT"

TICKET: Final[str] = "OMN-17334"

#: Shell separators that end one segment and begin another, matched on the
#: TOKEN stream shlex produces rather than on raw text.
_SEPARATORS: Final[frozenset[str]] = frozenset({";", "&&", "||", "|", "&"})

#: Wrapper programs stripped before a segment's program is read, so
#: `sudo git stash pop` is still a git-stash invocation.
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
    safe_alternative: str
    mutating_subcommands: frozenset[str]
    safe_subcommands: frozenset[str]
    worktree_root_env: str
    worktree_root_env_legacy: str
    omni_home_env: str


@dataclass(frozen=True)
class Decision:
    blocked: bool
    reason: str = ""
    #: Diagnostic-only notes about the command that were not decisive. Never
    #: printed as a refusal reason.
    notes: tuple[str, ...] = ()


def _require_str(raw: Any, key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise PolicyError(f"policy field {key!r} must be a non-empty string")
    return value


def _str_frozenset(raw: Any, key: str) -> frozenset[str]:
    value = raw.get(key)
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, str) and item for item in value)
    ):
        raise PolicyError(f"policy field {key!r} must be a non-empty list of strings")
    return frozenset(value)


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
    return Policy(
        ticket=_require_str(raw, "ticket"),
        safe_alternative=_require_str(raw, "safe_alternative"),
        mutating_subcommands=_str_frozenset(raw, "mutating_subcommands"),
        safe_subcommands=_str_frozenset(raw, "safe_subcommands"),
        worktree_root_env=_require_str(raw, "worktree_root_env"),
        worktree_root_env_legacy=_require_str(raw, "worktree_root_env_legacy"),
        omni_home_env=_require_str(raw, "omni_home_env"),
    )


def _tokenize(command: str) -> list[str]:
    lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|")
    lexer.whitespace_split = True
    try:
        return list(lexer)
    except ValueError:
        # Untokenisable (unbalanced quote, etc). Caller treats an empty
        # token list as "no segments", which never matches the stash shape --
        # the shell wrapper's own fail-closed boundary handles the case where
        # that silence is wrong by refusing on ANY exception from this module.
        return []


def _segments(command: str) -> list[list[str]]:
    tokens = _tokenize(command)
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
class _StashInvocation:
    target_arg: str | None  # the `-C <path>` value, if any
    stash_subcommand: str  # normalised: "push" for a bare `git stash`


def _parse_git_stash(tokens: list[str]) -> _StashInvocation | None:
    """Return the stash invocation shape of one `git ...` segment, or None."""
    stripped = _strip_wrappers(tokens)
    if not stripped or os.path.basename(stripped[0]) not in ("git",):
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
    if idx >= len(args) or args[idx] != "stash":
        return None
    idx += 1
    if idx >= len(args):
        return _StashInvocation(target_arg=target_arg, stash_subcommand="push")
    nxt = args[idx]
    if nxt.startswith("-"):
        # `git stash -u`, `git stash --include-untracked ...` -- shorthand
        # for `git stash push ...`.
        return _StashInvocation(target_arg=target_arg, stash_subcommand="push")
    return _StashInvocation(target_arg=target_arg, stash_subcommand=nxt)


def _resolve_target_dir(invocation: _StashInvocation, cwd: Path) -> Path:
    if invocation.target_arg:
        candidate = Path(invocation.target_arg)
        return candidate if candidate.is_absolute() else (cwd / candidate)
    return cwd


def _find_git_marker(start: Path) -> Path | None:
    """Walk up from `start` and return the first path with a `.git` entry."""
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


def _is_worktree(git_root: Path) -> bool:
    marker = git_root / ".git"
    try:
        return marker.is_file()
    except OSError:
        # Unreadable -- fail closed, treat as a worktree so the caller
        # refuses rather than guesses.
        return True


def _is_canonical_omni_home_clone(git_root: Path, omni_home_dir: Path | None) -> bool:
    if omni_home_dir is None:
        return False
    try:
        omni_home_resolved = omni_home_dir.resolve()
    except OSError:
        return False
    return git_root.parent == omni_home_resolved


def _resolve_omni_home() -> Path | None:
    raw = os.environ.get("OMNI_HOME")
    if not raw:
        return None
    return Path(raw)


def evaluate_bash_command(
    command: str, policy: Policy, cwd: Path, omni_home_dir: Path | None
) -> Decision:
    notes: list[str] = []
    for segment in _segments(command):
        invocation = _parse_git_stash(segment)
        if invocation is None:
            continue
        if invocation.stash_subcommand in policy.safe_subcommands:
            continue
        if invocation.stash_subcommand not in policy.mutating_subcommands:
            # An unrecognised stash subcommand. Fail closed: treat it as
            # mutating rather than silently admitting an unknown shape.
            notes.append(
                f"unrecognised stash subcommand {invocation.stash_subcommand!r} "
                "treated as mutating"
            )
        try:
            target_dir = _resolve_target_dir(invocation, cwd)
        except OSError as exc:
            return Decision(
                blocked=True,
                reason=_render_block_reason(
                    policy,
                    invocation,
                    detail=f"the target directory could not be resolved ({exc})",
                ),
            )
        git_root = _find_git_marker(target_dir)
        if git_root is None:
            # Not inside any git repository this guard can identify -- git
            # itself will refuse the command; nothing to gate here.
            continue
        if _is_worktree(git_root):
            return Decision(
                blocked=True,
                reason=_render_block_reason(
                    policy,
                    invocation,
                    detail=(
                        f"{git_root} is a git WORKTREE (its .git is a file "
                        "pointing at the parent clone's shared stash list)"
                    ),
                ),
            )
        if _is_canonical_omni_home_clone(git_root, omni_home_dir):
            return Decision(
                blocked=True,
                reason=_render_block_reason(
                    policy,
                    invocation,
                    detail=(
                        f"{git_root} is a canonical clone directly under "
                        "$OMNI_HOME, shared by every concurrent lane"
                    ),
                ),
            )
    return Decision(blocked=False, notes=tuple(notes))


def _render_block_reason(
    policy: Policy, invocation: _StashInvocation, detail: str
) -> str:
    subcommand = invocation.stash_subcommand
    return (
        f"BLOCKED: `git stash {subcommand}` operates on a stash ref shared "
        f"across every worktree of a clone ({policy.ticket}). {detail}. A "
        "push here can be popped by another lane, and a pop can take another "
        "lane's stash instead of your own -- this exact collision has "
        "recurred repeatedly, twice destroying a peer lane's uncommitted "
        "work outright. Use the path-scoped safe alternative instead: "
        f"{policy.safe_alternative}. `git stash list` / `git stash show` are "
        f"never gated. To disable this guard: onex hooks disable {GATE_BIT_NAME}"
    )


def _block(reason: str) -> int:
    print(json.dumps({"decision": "block", "reason": reason}))
    return 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
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
            f"call, so it cannot be checked for a git-stash mutation ({exc})."
        )

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        return _block(
            "BLOCKED: the PreToolUse payload for this Bash call is not "
            f"readable JSON, so it cannot be checked for a git-stash "
            f"mutation ({exc})."
        )
    if not isinstance(payload, dict):
        return _block(
            "BLOCKED: the PreToolUse payload for this Bash call is not a "
            "JSON object, so it cannot be checked for a git-stash mutation."
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
            f"BLOCKED: the OMN-17334 git-stash admission gate's policy could "
            f"not be loaded, so this command cannot be checked ({exc})."
        )

    cwd_raw = payload.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    cwd = Path(cwd_raw)
    omni_home_dir = _resolve_omni_home()

    try:
        decision = evaluate_bash_command(command, policy, cwd, omni_home_dir)
    except Exception as exc:  # noqa: BLE001 - fail-closed boundary, deliberate
        return _block(
            "BLOCKED: the OMN-17334 git-stash admission gate could not "
            f"evaluate this command ({exc}); an unverifiable stash mutation "
            "is refused rather than assumed safe."
        )

    if decision.blocked:
        return _block(decision.reason)

    if decision.notes:
        print(json.dumps({"decision": "allow", "notes": list(decision.notes)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
