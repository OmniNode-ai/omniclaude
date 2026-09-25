# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Keep the canonical clones current after every merge (OMN-19607).

Two callers, one engine:

* ``hook`` -- the PostToolUse hook ``post_tool_use_merge_clone_sync.sh`` pipes
  the tool payload here. When the tool call was a merge (``gh pr merge``, the
  REST merge endpoint by PUT, the bulk throttle's arm operation, or the GitHub
  MCP merge tool) this starts a DETACHED ``sync`` of every canonical clone of
  that repository and returns at once.
* ``sync`` -- fetch and fast-forward canonical clones. The launchd agent
  ``ai.omninode.canonical-clone-sync`` runs it over every clone on a short
  interval, which catches the merges this Mac did not make: auto-merge
  completions and other people's merges.

Why this exists
---------------
The operator ruled on 2026-09-25 that lanes query the canonical clones instead
of spending GitHub API reads, which only works while the clones are current.
The only automatic sync on the Mac at the time was the OMN-17190 PostToolUse
tick, which delegates to ``reconcile-host.sh``. That run couples the clone pull
to the venv reconcile: on 2026-09-25 one run sat inside the venv step from
13:25Z, every tick after it declined, and no clone moved for over an hour. This
engine is git only, so nothing it waits on can hold a clone back.

What a clone must be before it moves
------------------------------------
A canonical clone is a mirror (CLAUDE.md, "What This Workspace Is"). It is
advanced ONLY by ``git merge --ff-only`` onto the fetched upstream of the
branch it already has checked out, and only when that branch is a tracking
branch (``main``, ``dev``, ``master``). Everything else is REFUSED, logged with
the reason, and left exactly as found -- no reset, no checkout, no stash, no
clean, no force:

* bare (``core.bare=true``): fetch succeeds and checkout never lands (OMN-17291)
* detached HEAD, or checked out on a lane branch
* no upstream configured for the branch
* a merge, rebase, cherry-pick, revert or bisect in progress, or a live
  ``index.lock``
* the local branch carries commits the upstream does not (ahead or diverged)
* tracked changes. The one exception is a shared tree that uses the
  ``scripts/commit_lock.py`` protocol (the registry root's own clone, rule 19): there the
  fast-forward runs under that same commit lock, staged changes still refuse,
  and unstaged changes refuse only when the fast-forward would touch the same
  path. Rule 19 names ``git merge --ff-only origin/main`` as the sanctioned sync
  for that tree, and its rolling ledger is almost never clean.

Which branch a clone follows
----------------------------
The one it has checked out. ``pull-all.sh`` leaves every clone whose origin has
a ``dev`` branch on ``dev`` and the rest on ``main`` (OMN-16502), and the
OMN-17190 reconciler reconciles ``dev``. On the release-synced repositories PRs
land on ``dev`` and ``main`` only moves at a release, so ``dev`` is where merged
code appears first and is the right branch to query. This engine never switches
branches: moving HEAD between branches is the one thing the canonical-clone ref
guard refuses, and pull-all is the sanctioned door for it.

Verification
------------
A result is never read from ``git merge``'s exit status. ``HEAD`` is re-read
after the merge and compared with the fetched target (the OMN-17307 rule:
judge a step by reading its effect back). Every clone gets one JSON line in
``$ONEX_STATE_DIR/logs/canonical-clone-sync.jsonl`` with the before, after and
target sha, or the refusal reason.

Quota
-----
Nothing here calls the GitHub API. ``git fetch`` is the git transport, which
the REST and GraphQL rate limits do not count.

Standard library only, so it runs on any Python 3.12+ the hook or launchd
resolves, without a venv.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import os
import re
import shlex
import subprocess
import sys
import time
from collections.abc import Iterable, Iterator, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import IO

TRACKING_BRANCHES = frozenset({"main", "dev", "master"})
MCP_MERGE_TOOL = "mcp__github__merge_pull_request"

LOG_NAME = "canonical-clone-sync.jsonl"
CLONE_LOCK_NAME = "onex-canonical-clone-sync.lock"
REGISTRY_ROOTS_FILE = Path("scripts") / "git-hooks" / "registry-roots"
SHARED_TREE_COMMIT_LOCK = Path(".onex_state") / "commit.lock"

FETCH_TIMEOUT_SECONDS = 120
GIT_TIMEOUT_SECONDS = 60
CLONE_LOCK_WAIT_SECONDS = 120
COMMIT_LOCK_WAIT_SECONDS = 60
ARMED_DELAY_SECONDS = 30
MAX_WORKERS = 8

# Result vocabulary. Every clone gets exactly one of these per run.
ADVANCED = "ADVANCED"
UP_TO_DATE = "UP_TO_DATE"
REFUSED = "REFUSED"
FAILED = "FAILED"
NO_CLONE = "NO_CLONE"

_GIT_LOCATION_ENV = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_COMMON_DIR",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
)
_IN_PROGRESS_MARKERS = (
    "MERGE_HEAD",
    "CHERRY_PICK_HEAD",
    "REVERT_HEAD",
    "rebase-merge",
    "rebase-apply",
    "BISECT_LOG",
)

_GITHUB_REMOTE = re.compile(r"github\.com[:/]+([^/\s:]+)/([^/\s]+?)(?:\.git)?/*$", re.I)
_PR_URL = re.compile(r"^https?://github\.com/([^/\s]+)/([^/\s]+)/pull/\d+", re.I)
_MERGE_ENDPOINT = re.compile(r"^/?repos/([^/\s]+)/([^/\s]+)/pulls/\d+/merge/?$")
_OWNER_REPO = re.compile(r"^([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)$")
_ENV_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

# gh flags that consume the next argument. Anything not listed is treated as
# boolean, which at worst mistakes a flag's value for the positional argument --
# and the positional argument only ever supplies a repo when it is a PR URL.
_GH_PR_MERGE_VALUE_FLAGS = frozenset(
    {
        "-R",
        "--repo",
        "-b",
        "--body",
        "-F",
        "--body-file",
        "-t",
        "--subject",
        "-A",
        "--author-email",
        "--match-head-commit",
    }
)
_GH_API_VALUE_FLAGS = frozenset(
    {
        "-X",
        "--method",
        "-H",
        "--header",
        "-f",
        "--raw-field",
        "-F",
        "--field",
        "--input",
        "-q",
        "--jq",
        "-t",
        "--template",
        "--hostname",
        "--cache",
        "-p",
        "--preview",
    }
)
_WRAPPERS = frozenset({"env", "command", "builtin", "exec", "nohup", "time"})


# --------------------------------------------------------------------------- #
# Matcher: which tool calls were merges, and of which repository
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class MergeTrigger:
    """A merge seen in a tool call.

    ``repo`` is ``owner/name`` when the call names it, else ``None`` (the caller
    resolves it from the session's working directory). ``armed`` is true for an
    auto-merge arm: GitHub merges at once when the PR is already mergeable,
    otherwise later, so the sync waits briefly and the timer catches the rest.
    """

    verb: str
    repo: str | None
    armed: bool = False


def _split_segments(command: str) -> list[list[str]]:
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    segments: list[list[str]] = [[]]
    for token in lexer:
        if token and set(token) <= set("();<>|&`\n"):
            segments.append([])
            continue
        segments[-1].append(token)
    return [seg for seg in segments if seg]


def _strip_prefix(segment: list[str]) -> tuple[list[str], dict[str, str]]:
    """Drop leading ``VAR=value`` assignments and command wrappers."""
    env: dict[str, str] = {}
    words = list(segment)
    while words:
        head = words[0]
        if head.startswith("$"):
            head = head.lstrip("$")
            if not head:
                words.pop(0)
                continue
            words[0] = head
        if _ENV_ASSIGNMENT.match(head):
            key, _, value = head.partition("=")
            env[key] = value
            words.pop(0)
            continue
        if head in _WRAPPERS:
            words.pop(0)
            continue
        if head == "timeout":
            words.pop(0)
            while words and words[0].startswith("-"):
                words.pop(0)
            if words:
                words.pop(0)
            continue
        break
    return words, env


def _flag_value(args: Sequence[str], names: Iterable[str]) -> str | None:
    """Value of the LAST occurrence of any flag in ``names`` (gh's own rule)."""
    names = tuple(names)
    value: str | None = None
    i = 0
    while i < len(args):
        arg = args[i]
        for name in names:
            if arg == name and i + 1 < len(args):
                value = args[i + 1]
            elif name.startswith("--") and arg.startswith(name + "="):
                value = arg[len(name) + 1 :]
            elif (
                not name.startswith("--")
                and arg.startswith(name)
                and len(arg) > len(name)
            ):
                value = arg[len(name) :]
        i += 1
    return value


def _positionals(args: Sequence[str], value_flags: frozenset[str]) -> list[str]:
    out: list[str] = []
    skip = False
    for arg in args:
        if skip:
            skip = False
            continue
        if arg.startswith("-"):
            if arg in value_flags:
                skip = True
            continue
        out.append(arg)
    return out


def _normalise_repo(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    url = _PR_URL.match(value)
    if url:
        return f"{url.group(1)}/{url.group(2)}"
    if value.lower().startswith(("https://github.com/", "http://github.com/")):
        parts = value.split("/")
        if len(parts) >= 5:
            return f"{parts[3]}/{parts[4].removesuffix('.git')}"
    if value.lower().startswith("github.com/"):
        value = value[len("github.com/") :]
    match = _OWNER_REPO.match(value)
    if match and "{" not in value:
        return f"{match.group(1)}/{match.group(2)}"
    return None


def _match_gh_pr_merge(args: list[str], env: Mapping[str, str]) -> MergeTrigger | None:
    if "--disable-auto" in args:
        return None
    repo = _normalise_repo(_flag_value(args, ("-R", "--repo")))
    if repo is None:
        for positional in _positionals(args, _GH_PR_MERGE_VALUE_FLAGS):
            repo = _normalise_repo(positional) if _PR_URL.match(positional) else None
            break
    if repo is None:
        repo = _normalise_repo(env.get("GH_REPO"))
    return MergeTrigger(verb="gh-pr-merge", repo=repo, armed="--auto" in args)


def _match_gh_api(args: list[str]) -> MergeTrigger | None:
    method = (_flag_value(args, ("-X", "--method")) or "").upper()
    if method != "PUT":
        return None
    for positional in _positionals(args, _GH_API_VALUE_FLAGS):
        match = _MERGE_ENDPOINT.match(positional)
        if not match:
            continue
        owner, name = match.group(1), match.group(2)
        repo = None if "{" in owner or "{" in name else f"{owner}/{name}"
        return MergeTrigger(verb="gh-api-merge", repo=repo)
    return None


def _match_bulk_throttle(args: list[str]) -> MergeTrigger | None:
    if (_flag_value(args, ("--operation",)) or "") != "arm-automerge":
        return None
    if "--dry-run" in args:
        return None
    owner = _flag_value(args, ("--owner",))
    name = _flag_value(args, ("--repo",))
    repo = _normalise_repo(f"{owner}/{name}") if owner and name else None
    return MergeTrigger(verb="bulk-throttle-arm", repo=repo, armed=True)


def match_bash_command(command: str) -> list[MergeTrigger]:
    """Every merge a shell command line performs, in order."""
    try:
        segments = _split_segments(command)
    except ValueError:
        return []
    triggers: list[MergeTrigger] = []
    for segment in segments:
        words, env = _strip_prefix(segment)
        if not words:
            continue
        program = os.path.basename(words[0])
        trigger: MergeTrigger | None = None
        if program == "gh" and words[1:3] == ["pr", "merge"]:
            trigger = _match_gh_pr_merge(words[3:], env)
        elif program == "gh" and words[1:2] == ["api"]:
            trigger = _match_gh_api(words[2:])
        else:
            for index, word in enumerate(words):
                if os.path.basename(word) == "bulk_pr_throttle.py":
                    trigger = _match_bulk_throttle(words[index + 1 :])
                    break
        if trigger is not None:
            triggers.append(trigger)
    return triggers


def tool_call_failed(tool_response: object) -> bool:
    """True when the payload says the call failed. Absent evidence is success."""
    if not isinstance(tool_response, Mapping):
        return False
    for key in ("exit_code", "exitCode", "returncode", "returnCode"):
        code = tool_response.get(key)
        if isinstance(code, int) and not isinstance(code, bool) and code != 0:
            return True
        if isinstance(code, str) and code.strip() not in ("", "0"):
            return True
    for key in ("interrupted", "is_error", "isError"):
        if tool_response.get(key) is True:
            return True
    return False


def triggers_from_payload(payload: Mapping[str, object]) -> list[MergeTrigger]:
    """The merges a PostToolUse payload reports, or an empty list."""
    tool_name = payload.get("tool_name")
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, Mapping):
        return []
    if tool_call_failed(payload.get("tool_response")):
        return []
    if tool_name == "Bash":
        command = tool_input.get("command")
        return match_bash_command(command) if isinstance(command, str) else []
    if tool_name == MCP_MERGE_TOOL:
        owner, name = tool_input.get("owner"), tool_input.get("repo")
        if isinstance(owner, str) and isinstance(name, str):
            return [
                MergeTrigger(verb="mcp-merge", repo=_normalise_repo(f"{owner}/{name}"))
            ]
        return [MergeTrigger(verb="mcp-merge", repo=None)]
    return []


# --------------------------------------------------------------------------- #
# git plumbing
# --------------------------------------------------------------------------- #
def git_env(base: Mapping[str, str] | None = None) -> dict[str, str]:
    """The environment every git call here runs in.

    Git exports the location variables into hook processes, and they override
    both ``-C`` and the cwd (OMN-14891): a sync started from inside a git hook
    would otherwise fetch into whatever repository leaked them.
    """
    env = dict(os.environ if base is None else base)
    for key in _GIT_LOCATION_ENV:
        env.pop(key, None)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env.setdefault("GIT_SSH_COMMAND", "ssh -o BatchMode=yes -o ConnectTimeout=20")
    env["LC_ALL"] = "C"
    return env


@dataclass(frozen=True)
class GitResult:
    code: int
    out: str
    err: str


def run_git(
    clone: Path, *args: str, timeout: float = GIT_TIMEOUT_SECONDS, strip: bool = True
) -> GitResult:
    try:
        proc = subprocess.run(
            ["git", "-C", str(clone), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=git_env(),
            check=False,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        return GitResult(124, "", f"timed out after {timeout:g}s")
    except OSError as exc:
        return GitResult(127, "", str(exc))
    # Porcelain status output starts with a meaningful space (" M path" is an
    # unstaged change), so a caller that parses it asks for the raw stdout.
    out = proc.stdout.strip() if strip else proc.stdout
    return GitResult(proc.returncode, out, proc.stderr.strip())


def _tail(text: str, limit: int = 300) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else "..." + text[-limit:]


def repo_slug_of_url(url: str) -> str | None:
    match = _GITHUB_REMOTE.search(url.strip())
    return f"{match.group(1)}/{match.group(2)}" if match else None


# --------------------------------------------------------------------------- #
# Discovery
# --------------------------------------------------------------------------- #
def registry_roots(env: Mapping[str, str]) -> list[Path]:
    """``$OMNI_HOME``, each ``ONEX_REGISTRY_ROOTS`` entry, and the roots file.

    The roots file (``$OMNI_HOME/scripts/git-hooks/registry-roots``, written by
    omnibase_infra ``install-canonical-clone-git-hooks.sh``, OMN-19388) is read
    so a launchd run, whose environment carries only ``OMNI_HOME``, covers the
    same roots an interactive shell does.
    """
    candidates: list[str] = []
    registry_home = env.get("OMNI_HOME", "")
    if registry_home:
        candidates.append(registry_home)
    candidates.extend(env.get("ONEX_REGISTRY_ROOTS", "").split(":"))
    if registry_home:
        roots_file = Path(registry_home) / REGISTRY_ROOTS_FILE
        with contextlib.suppress(OSError):
            for line in roots_file.read_text().splitlines():
                key, _, value = line.strip().partition("=")
                if key == "root" and value:
                    candidates.append(value)
    roots: list[Path] = []
    seen: set[Path] = set()
    for raw in candidates:
        raw = raw.strip()
        if not raw or not Path(raw).is_absolute():
            continue
        path = Path(raw)
        if not path.is_dir():
            continue
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        roots.append(path)
    return roots


def discover_clones(roots: Iterable[Path]) -> list[Path]:
    """Each root that is itself a clone, and each direct child that is one.

    A child whose ``.git`` is a FILE is a linked worktree, not a canonical
    clone, and is skipped.
    """
    clones: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        candidates = [root]
        with contextlib.suppress(OSError):
            candidates.extend(sorted(p for p in root.iterdir() if p.is_dir()))
        for candidate in candidates:
            if not (candidate / ".git").is_dir():
                continue
            resolved = candidate.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            clones.append(candidate)
    return clones


def clone_slug(clone: Path) -> str | None:
    """``owner/name`` of the remote the checked-out branch tracks (else origin)."""
    branch = run_git(clone, "symbolic-ref", "--quiet", "--short", "HEAD").out
    remote = ""
    if branch:
        remote = run_git(clone, "config", "--get", f"branch.{branch}.remote").out
    url = run_git(clone, "remote", "get-url", remote or "origin").out
    return repo_slug_of_url(url) if url else None


# --------------------------------------------------------------------------- #
# Locks
# --------------------------------------------------------------------------- #
@contextlib.contextmanager
def file_lock(path: Path, wait_seconds: float) -> Iterator[bool]:
    """Exclusive ``fcntl.flock`` (macOS has no flock(1)); yields False on timeout."""
    handle: IO[str] | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(path, "a")  # noqa: SIM115 -- held across the yield
    except OSError:
        yield False
        return
    deadline = time.monotonic() + wait_seconds
    acquired = False
    try:
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except OSError:
                if time.monotonic() >= deadline:
                    break
                time.sleep(0.25)
        yield acquired
    finally:
        if acquired:
            with contextlib.suppress(OSError):
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


# --------------------------------------------------------------------------- #
# Engine
# --------------------------------------------------------------------------- #
@dataclass
class CloneResult:
    clone: str
    result: str
    repo: str | None = None
    branch: str | None = None
    upstream: str | None = None
    before: str | None = None
    after: str | None = None
    target: str | None = None
    reason: str | None = None
    carried_dirty_paths: int = 0


def _dirty_entries(clone: Path) -> tuple[list[str], list[str]] | None:
    """(staged paths, unstaged paths) of tracked files, or None on error."""
    status = run_git(
        clone, "status", "--porcelain=v1", "-z", "--untracked-files=no", strip=False
    )
    if status.code != 0:
        return None
    staged: list[str] = []
    unstaged: list[str] = []
    entries = status.out.split("\0") if status.out.strip("\0") else []
    i = 0
    while i < len(entries):
        entry = entries[i]
        i += 1
        if len(entry) < 4:
            continue
        x, y, path = entry[0], entry[1], entry[3:]
        if x in "RC":
            i += 1  # the rename source follows as its own NUL-separated field
        if x not in " ?":
            staged.append(path)
        if y not in " ?":
            unstaged.append(path)
    return staged, unstaged


def sync_clone(clone: Path) -> CloneResult:
    """Fetch the checked-out tracking branch and fast-forward it, or refuse."""
    result = CloneResult(clone=str(clone), result=FAILED)

    def refuse(reason: str) -> CloneResult:
        result.result = REFUSED
        result.reason = reason
        return result

    def fail(reason: str) -> CloneResult:
        result.result = FAILED
        result.reason = reason
        return result

    if run_git(clone, "rev-parse", "--is-bare-repository").out == "true":
        return refuse(
            "core.bare=true: a fetch lands and no checkout ever does (OMN-17291)"
        )

    branch = run_git(clone, "symbolic-ref", "--quiet", "--short", "HEAD").out
    if not branch:
        return refuse("detached HEAD: the clone tracks no branch")
    result.branch = branch
    if branch not in TRACKING_BRANCHES:
        return refuse(
            f"checked out on {branch!r}, not a tracking branch; pull-all.sh is the "
            "sanctioned door that returns a clone to its branch"
        )

    remote = run_git(clone, "config", "--get", f"branch.{branch}.remote").out
    merge_ref = run_git(clone, "config", "--get", f"branch.{branch}.merge").out
    if not remote or remote == "." or not merge_ref.startswith("refs/heads/"):
        return refuse(f"branch {branch!r} has no remote upstream configured")
    upstream_branch = merge_ref[len("refs/heads/") :]
    tracking_ref = f"refs/remotes/{remote}/{upstream_branch}"
    result.upstream = f"{remote}/{upstream_branch}"
    url = run_git(clone, "remote", "get-url", remote).out
    result.repo = repo_slug_of_url(url) if url else None

    git_dir_out = run_git(clone, "rev-parse", "--absolute-git-dir")
    if git_dir_out.code != 0 or not git_dir_out.out:
        return fail(f"cannot resolve the git dir: {_tail(git_dir_out.err)}")
    git_dir = Path(git_dir_out.out)

    with file_lock(git_dir / CLONE_LOCK_NAME, CLONE_LOCK_WAIT_SECONDS) as locked:
        if not locked:
            return refuse(
                f"another canonical-clone sync held {git_dir / CLONE_LOCK_NAME} "
                f"for {CLONE_LOCK_WAIT_SECONDS}s"
            )

        before = run_git(clone, "rev-parse", "--verify", "--quiet", "HEAD").out
        result.before = before or None

        fetch = run_git(
            clone,
            "fetch",
            "--quiet",
            remote,
            f"+refs/heads/{upstream_branch}:{tracking_ref}",
            timeout=FETCH_TIMEOUT_SECONDS,
        )
        if fetch.code != 0:
            return fail(f"fetch {remote} {upstream_branch} failed: {_tail(fetch.err)}")

        target = run_git(clone, "rev-parse", "--verify", "--quiet", tracking_ref).out
        if not target:
            return fail(f"{tracking_ref} does not resolve after the fetch")
        result.target = target

        if before == target:
            result.after = before
            result.result = UP_TO_DATE
            return result

        for marker in _IN_PROGRESS_MARKERS:
            if (git_dir / marker).exists():
                return refuse(
                    f"{marker} present: an operation is in progress in the clone"
                )
        if (git_dir / "index.lock").exists():
            return refuse(
                "index.lock present: another git process is writing the clone"
            )

        if run_git(clone, "merge-base", "--is-ancestor", before, target).code != 0:
            if run_git(clone, "merge-base", "--is-ancestor", target, before).code == 0:
                return refuse(
                    f"{branch} is ahead of {result.upstream}: it carries commits "
                    "the upstream does not"
                )
            return refuse(f"{branch} and {result.upstream} have diverged")

        dirty = _dirty_entries(clone)
        if dirty is None:
            return fail("git status failed; the clone's cleanliness is unknown")
        staged, unstaged = dirty
        shared_tree = (clone / SHARED_TREE_COMMIT_LOCK).exists()

        if staged:
            return refuse(f"{len(staged)} staged path(s), e.g. {', '.join(staged[:3])}")
        if unstaged and not shared_tree:
            return refuse(
                f"{len(unstaged)} path(s) with uncommitted tracked changes, "
                f"e.g. {', '.join(unstaged[:3])}"
            )
        if unstaged:
            incoming = run_git(clone, "diff", "--name-only", "-z", before, target)
            if incoming.code != 0:
                return fail("cannot list the incoming change set")
            touched = set(filter(None, incoming.out.split("\0")))
            overlap = sorted(touched.intersection(unstaged))
            if overlap:
                return refuse(
                    f"{len(overlap)} uncommitted path(s) are also changed upstream, "
                    f"e.g. {', '.join(overlap[:3])}"
                )
            result.carried_dirty_paths = len(unstaged)

        commit_lock = (
            file_lock(clone / SHARED_TREE_COMMIT_LOCK, COMMIT_LOCK_WAIT_SECONDS)
            if shared_tree
            else contextlib.nullcontext(True)
        )
        with commit_lock as commit_locked:
            if not commit_locked:
                return refuse(
                    f"the shared-tree commit lock {clone / SHARED_TREE_COMMIT_LOCK} "
                    f"was held for {COMMIT_LOCK_WAIT_SECONDS}s"
                )
            merge = run_git(clone, "merge", "--ff-only", "--quiet", target)
        after = run_git(clone, "rev-parse", "--verify", "--quiet", "HEAD").out
        result.after = after or None
        if merge.code != 0:
            return refuse(
                f"git refused the fast-forward: {_tail(merge.err or merge.out)}"
            )
        if after != target:
            return fail("HEAD did not reach the fetched target after the fast-forward")
        result.result = ADVANCED
        return result


# --------------------------------------------------------------------------- #
# Logging
# --------------------------------------------------------------------------- #
def state_dir(env: Mapping[str, str]) -> Path:
    """Same resolution as hooks/scripts/onex-paths.sh."""
    raw = env.get("ONEX_STATE_DIR") or str(
        Path(env.get("HOME", str(Path.home()))) / ".onex_state"
    )
    return Path(raw)


def log_path(env: Mapping[str, str]) -> Path:
    return state_dir(env) / "logs" / LOG_NAME


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def append_log(path: Path, record: Mapping[str, object]) -> None:
    line = json.dumps(record, sort_keys=True) + "\n"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, line.encode())
        finally:
            os.close(fd)
    except OSError:
        pass


# --------------------------------------------------------------------------- #
# Runs
# --------------------------------------------------------------------------- #
def run_sync(
    env: Mapping[str, str],
    repos: Sequence[str] | None,
    trigger: str,
    verb: str | None = None,
) -> list[CloneResult]:
    """Sync every canonical clone of ``repos`` (all clones when None)."""
    started = time.monotonic()
    clones = discover_clones(registry_roots(env))
    wanted = {r.casefold() for r in repos} if repos else None
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        if wanted is not None:
            slugs = list(pool.map(clone_slug, clones))
            clones = [
                c
                for c, slug in zip(clones, slugs, strict=True)
                if (slug or "").casefold() in wanted
            ]
        results = list(pool.map(sync_clone, clones))

    path = log_path(env)
    ts = utc_now()
    for res in results:
        record: dict[str, object] = {"ts": ts, "trigger": trigger, **asdict(res)}
        if verb:
            record["verb"] = verb
        append_log(path, record)
    if wanted is not None:
        found = {(r.repo or "").casefold() for r in results}
        for repo in sorted(wanted - found):
            append_log(
                path,
                {
                    "ts": ts,
                    "trigger": trigger,
                    "verb": verb,
                    "repo": repo,
                    "result": NO_CLONE,
                    "reason": "no canonical clone of this repository under any registry root",
                },
            )
    append_log(
        path,
        {
            "ts": utc_now(),
            "trigger": trigger,
            "verb": verb,
            "result": "RUN_COMPLETE",
            "clones": len(results),
            "counts": {
                name: sum(1 for r in results if r.result == name)
                for name in (ADVANCED, UP_TO_DATE, REFUSED, FAILED)
            },
            "duration_ms": int((time.monotonic() - started) * 1000),
        },
    )
    return results


def resolve_repo_from_cwd(cwd: str | None) -> str | None:
    """The repository a ``gh`` call with no repo flag acts on: the cwd's origin."""
    if not cwd or not Path(cwd).is_dir():
        return None
    url = run_git(Path(cwd), "remote", "get-url", "origin", timeout=5).out
    return repo_slug_of_url(url) if url else None


def hook_main(stdin: IO[str], env: Mapping[str, str]) -> int:
    """Read a PostToolUse payload; spawn a detached sync on a merge. Always 0."""
    try:
        payload = json.loads(stdin.read() or "{}")
    except (ValueError, OSError):
        return 0
    if not isinstance(payload, dict):
        return 0
    triggers = triggers_from_payload(payload)
    if not triggers:
        return 0

    cwd = payload.get("cwd")
    repos: list[str] = []
    armed = False
    for trig in triggers:
        repo = trig.repo or resolve_repo_from_cwd(cwd if isinstance(cwd, str) else None)
        armed = armed or trig.armed
        if repo is None:
            repos = []
            break
        repos.append(repo)
    verbs = ",".join(sorted({t.verb for t in triggers}))

    command = [
        sys.executable,
        os.path.abspath(__file__),
        "sync",
        "--trigger",
        "hook",
        "--verb",
        verbs,
    ]
    if armed:
        command += ["--delay", str(ARMED_DELAY_SECONDS)]
    for repo in dict.fromkeys(repos):
        command += ["--repo", repo]

    append_log(
        log_path(env),
        {
            "ts": utc_now(),
            "trigger": "hook",
            "verb": verbs,
            "result": "TRIGGERED",
            "repos": list(dict.fromkeys(repos)) or "ALL",
            "armed": armed,
        },
    )
    if env.get("ONEX_CLONE_SYNC_HOOK_DRY_RUN") == "1":
        return 0
    try:
        subprocess.Popen(  # noqa: S603 -- argv is built above, no shell
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
            env=dict(env),
        )
    except OSError:
        pass
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0] if __doc__ else None
    )
    sub = parser.add_subparsers(dest="mode", required=True)
    sub.add_parser("hook", help="read a PostToolUse payload on stdin")
    sync = sub.add_parser("sync", help="fetch and fast-forward canonical clones")
    sync.add_argument(
        "--repo",
        action="append",
        default=None,
        help="owner/name; repeatable; default all",
    )
    sync.add_argument(
        "--trigger", default="manual", choices=("hook", "timer", "manual")
    )
    sync.add_argument("--verb", default=None)
    sync.add_argument("--delay", type=float, default=0.0)
    args = parser.parse_args(argv)

    if args.mode == "hook":
        return hook_main(sys.stdin, os.environ)

    if not os.environ.get("OMNI_HOME"):
        print(
            "canonical_clone_sync: OMNI_HOME is not set; there is no default registry",
            file=sys.stderr,
        )
        return 2
    if args.delay > 0:
        time.sleep(args.delay)
    results = run_sync(os.environ, args.repo, args.trigger, args.verb)
    for res in results:
        sha = f"{(res.before or '')[:12]}->{(res.after or '')[:12]}"
        print(
            f"{res.result:10} {res.clone} {res.branch or '-'} {sha} {res.reason or ''}".rstrip()
        )
    return 1 if any(r.result == FAILED for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
