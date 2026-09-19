# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Lane identity: register a lane, resolve it from a worktree, stamp it into
commits (OMN-18260, phase 5 item 3 of the 2026-09-12 process-friction plan).

THE PROBLEM, MEASURED 2026-09-13. Zero commits carry a lane trailer across the
last 200 commits of each of three worked repositories. The same window carries
`Co-authored-by:`, `Ticket:` and `Evidence-Ticket:` trailers, so the mechanism
works and is simply unused. Every lane pushes under one account, so neither
authorship nor branch name says which lane produced a commit. That is why the
cross-lane push on 2026-09-12 at 14:17Z -- three commits to one repository's
branch and four to another's, both under a ticket held by a different lane --
was invisible until a person noticed it by hand.

WHY THAT MATTERS MORE THAN IT SOUNDS. A pre-push refusal compares the claim
holder against the pushing lane. Without this file, the second operand does not
exist, and no hook or check can reproduce the comparison. This is the missing
operand, and nothing downstream in phase 5 works without it.

DESIGN OF RECORD: `beta/plans/2026-09-13-lane-identity-and-claim-index-design.md`
in knowledge-base-internal (OMN-18259), sections 3 and 9. Four alternative
homes for the identity are rejected there on the record; the one adopted here is
a registry keyed by the worktree's resolved path, held outside every repository,
so no product repository needs an ignore entry and the resolution survives the
session that wrote it.

PRIOR ART: OMN-17005 measured what happens without this. Its claimant identity
was an environment variable that is unset, falling back to one shared constant,
so every concurrent lane claimed as the same string and two anonymous lanes
could never be told apart. That is the failure this module exists to not repeat,
which is why the environment-variable option is rejected rather than reused.

THE HONEST LIMIT. A lane stamps its own identity. Nothing here proves a lane is
who it says it is; a lane registering under another lane's slug produces a
correct-looking trailer. This enforces ATTRIBUTION AND BLAST RADIUS, not
authority -- the same limit the production-promotion, staging-namespace and
credential-rotation gates each record about themselves. What it removes is the
silent case: commits on a branch with nothing anywhere saying which lane made
them.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

__all__ = [
    "LANE_TRAILER",
    "SESSION_TRAILER",
    "LaneRecord",
    "BadRange",
    "UnregisteredLane",
    "apply_trailers",
    "SharedHooksDirectory",
    "commit_identity",
    "commit_trailers",
    "commits_in_range",
    "own_hooks_dir",
    "record_path",
    "register",
    "registry_root_from_env",
    "resolve",
    "trailer_lines",
    "unstamped_commits",
    "valid_lane",
]

LANE_TRAILER = "Onex-Lane"
SESSION_TRAILER = "Onex-Session"

# The environment variable naming the workspace root. Named once so the
# literal does not have to be repeated at every use site.
WORKSPACE_ENV = "OMNI_HOME"

# The slug the ledger already uses: lowercase, digits, single hyphens, no
# leading or trailing hyphen. Adopted rather than invented so a trailer and a
# claim row name the same thing in the same vocabulary -- a trailer in a
# different alphabet could not be compared against a claim row at all.
_LANE_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_LANE_MAX = 64
_TICKET_RE = re.compile(r"^OMN-\d+$")

# A trailer is read as a trailer -- a `Key: value` line in the message's final
# trailer block -- never searched for in the body. CLAUDE.md rule 15: prose that
# merely spells a trigger must not satisfy a gate.
_TRAILER_LINE_RE = re.compile(r"^([A-Za-z][A-Za-z0-9-]*):[ \t]*(.*)$")


class BadRange(RuntimeError):
    """The revision range does not resolve. Raised rather than returning an
    empty finding list: no commits and no defects look identical to a caller,
    and this check's whole value is that its zero means something."""


class UnregisteredLane(RuntimeError):
    """The worktree has no lane identity. Raised rather than defaulted: a
    trailer that can be wrong is worse than one that is absent, because the
    check downstream cannot tell the two apart."""


@dataclass(frozen=True)
class LaneRecord:
    lane: str
    session_id: str
    ticket: str
    worktree: str
    registered_at: str

    def as_dict(self) -> dict[str, str]:
        return {
            "lane": self.lane,
            "session_id": self.session_id,
            "ticket": self.ticket,
            "worktree": self.worktree,
            "registered_at": self.registered_at,
        }


def valid_lane(lane: str) -> bool:
    return bool(lane) and len(lane) <= _LANE_MAX and _LANE_RE.match(lane) is not None


def registry_root_from_env() -> Path:
    """Where the registry lives, resolved fail-fast.

    `ONEX_LANE_REGISTRY_ROOT` wins when set, so tests and alternate workspaces
    do not have to fake a workspace root. Otherwise the workspace root, read as
    a required key so a missing one raises rather than silently picking a wrong
    default (CLAUDE.md rule 8). A silent default here would scatter lane records
    into an unrelated directory and make every resolution miss -- which reads
    exactly like "no lane is registered" and refuses every commit on the box.
    """
    explicit = os.environ.get("ONEX_LANE_REGISTRY_ROOT")
    if explicit:
        return Path(explicit)
    return Path(os.environ[WORKSPACE_ENV]) / ".onex_state"


def _registry_dir(base: Path) -> Path:
    return base / "lane_identity"


def _key(worktree: Path) -> str:
    return hashlib.sha256(str(worktree.resolve()).encode("utf-8")).hexdigest()[:32]


def record_path(base: Path, worktree: Path) -> Path:
    return _registry_dir(base) / f"{_key(worktree)}.json"


def register(
    base: Path,
    worktree: Path,
    *,
    lane: str,
    ticket: str,
    session_id: str | None = None,
) -> LaneRecord:
    """Register `worktree` as belonging to `lane`. Re-registering replaces the
    record: a worktree has exactly one lane at a time, and a second lane taking
    over a directory is a fact to record, not an error."""
    if not valid_lane(lane):
        raise ValueError(
            f"lane {lane!r} is not a valid slug: lowercase letters, digits and single "
            f"hyphens, at most {_LANE_MAX} characters"
        )
    if not _TICKET_RE.match(ticket):
        raise ValueError(f"ticket {ticket!r} is not of the form OMN-<digits>")
    resolved = worktree.resolve()
    record = LaneRecord(
        lane=lane,
        session_id=session_id or uuid.uuid4().hex,
        ticket=ticket,
        worktree=str(resolved),
        registered_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    path = record_path(base, resolved)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(record.as_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    tmp.replace(path)
    return record


def resolve(base: Path, path: Path) -> LaneRecord | None:
    """The lane owning `path`, or None.

    Walks upward, so a lane working in a subdirectory of its worktree still
    resolves. Returns None -- not a partial record -- for anything unreadable or
    incomplete: an unresolvable identity must read as unregistered so the commit
    is refused and the lane re-registers, never as a successful resolution of a
    record that is missing half its fields.
    """
    try:
        current = path.resolve()
    except OSError:
        return None
    for candidate in [current, *current.parents]:
        record_file = record_path(base, candidate)
        if not record_file.is_file():
            continue
        try:
            data = json.loads(record_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        lane = data.get("lane")
        session_id = data.get("session_id")
        if not isinstance(lane, str) or not isinstance(session_id, str):
            return None
        if not valid_lane(lane) or not session_id:
            return None
        return LaneRecord(
            lane=lane,
            session_id=session_id,
            ticket=str(data.get("ticket", "")),
            worktree=str(data.get("worktree", candidate)),
            registered_at=str(data.get("registered_at", "")),
        )
    return None


def trailer_lines(base: Path, worktree: Path) -> list[str]:
    record = resolve(base, worktree)
    if record is None:
        raise UnregisteredLane(str(worktree))
    return [f"{LANE_TRAILER}: {record.lane}", f"{SESSION_TRAILER}: {record.session_id}"]


def _split_comments(message: str) -> tuple[str, str]:
    """Separate the authored message from git's own comment block, which is
    everything from the first line starting with `#` that begins the trailing
    run of comment lines. A trailer appended after the comments is not a trailer
    -- git strips that region before the commit is written."""
    lines = message.splitlines(keepends=True)
    first_comment = len(lines)
    for index in range(len(lines) - 1, -1, -1):
        stripped = lines[index].strip()
        if stripped.startswith("#") or not stripped:
            first_comment = index
        else:
            break
    return "".join(lines[:first_comment]), "".join(lines[first_comment:])


def apply_trailers(message: str, lines: list[str]) -> str:
    """Append the trailers to `message`, idempotently.

    Idempotent because a commit gets amended and reworded, and a message
    accumulating a second copy of its own lane trailer would make the reader
    downstream see two lanes for one commit.
    """
    body, comments = _split_comments(message)
    present = {
        line.split(":", 1)[0]
        for line in body.splitlines()
        if _TRAILER_LINE_RE.match(line)
    }
    missing = [line for line in lines if line.split(":", 1)[0] not in present]
    if not missing:
        return message
    if not body.endswith("\n"):
        body += "\n"
    last = [line for line in body.splitlines() if line.strip()]
    needs_blank = bool(last) and _TRAILER_LINE_RE.match(last[-1]) is None
    if needs_blank:
        body += "\n"
    body += "\n".join(missing) + "\n"
    return body + comments


def commit_trailers(message: str) -> dict[str, str]:
    """Every trailer in the message's FINAL trailer block, as a mapping.

    Extracted from `commit_identity` (OMN-18263) so a reader that needs another
    trailer -- the fencing token, say -- does not parse the block a second way.
    Two parsers of one format is two places for it to disagree about what counts
    as a trailer, and "counts as a trailer" is the whole of CLAUDE.md rule 15.

    The final block only. A `Key: value` line in the body is prose that happens
    to look like a trailer, and git would not treat it as one either.
    """
    body, _ = _split_comments(message)
    lines = [line for line in body.splitlines() if line.strip()]
    trailers: dict[str, str] = {}
    for line in reversed(lines):
        match = _TRAILER_LINE_RE.match(line)
        if match is None:
            break
        trailers.setdefault(match.group(1), match.group(2).strip())
    return trailers


def commit_identity(message: str) -> tuple[str, str] | None:
    """The (lane, session) a commit message declares, or None.

    Read from the message's final trailer block only. A mention in the body is
    not a declaration, and a trailer whose lane value is not a valid slug is not
    one either: an identifier that cannot be compared against a claim row fails
    the check exactly as an absent one does.
    """
    trailers = commit_trailers(message)
    lane = trailers.get(LANE_TRAILER)
    session = trailers.get(SESSION_TRAILER)
    if not lane or not session or not valid_lane(lane):
        return None
    return lane, session


class SharedHooksDirectory(RuntimeError):
    """The resolved hooks directory is shared with other repositories."""


def git_common_dir(repo: Path) -> Path:
    return Path(
        subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
            env=_git_env(),
        ).stdout.strip()
    )


def configured_hooks_path(repo: Path) -> Path | None:
    """`core.hooksPath` for this clone, absolute, or None when unset."""
    result = subprocess.run(
        ["git", "config", "--get", "core.hooksPath"],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
        env=_git_env(),
    )
    value = result.stdout.strip()
    if result.returncode != 0 or not value:
        return None
    path = Path(value).expanduser()
    return path if path.is_absolute() else (repo / path)


def own_hooks_dir(repo: Path) -> Path:
    """This repository OWN hooks directory -- `<git-common-dir>/hooks` -- or raise.

    RESOLVED FROM THE COMMON DIRECTORY, NOT FROM `git rev-parse --git-path hooks`
    (OMN-18273). That form honours `core.hooksPath`, and this workspace points
    EVERY canonical clone at one shared guard directory
    (`scripts/git-hooks/canonical-clone`). So the refusal below fired on every
    clone in the registry and the installer could not install anywhere at all:
    `install-hook --repo <any canonical clone>` exited 2 with "refusing to
    install into .../canonical-clone". That is why OMN-18260 through OMN-18263
    shipped complete and stayed inert -- not because nobody ran the installer,
    but because running it could not succeed.

    The refusal it was protecting is kept, and is now structural: the target is
    computed as `<git-common-dir>/hooks`, which cannot be a shared directory,
    and the assertion below still refuses anything that escapes it. The original
    incident -- an inherited GIT_DIR pointing the installer at the shared
    directory -- is separately closed by `_git_env()` stripping every GIT_*
    variable before any git call here.

    Installing HERE is also what makes the hook run: the shared guard
    (`canonical_clone_guard.sh`) chains with `exec "$git_common_dir/hooks/$hook_name"`,
    so a hook in this directory is exactly what the guard hands control to. See
    `hooks_reachable` for the other half -- the guard only chains hook types it
    has a symlink for.
    """
    common = git_common_dir(repo)
    hooks = common / "hooks"
    if not hooks.resolve().parent == common.resolve():
        raise SharedHooksDirectory(
            f"refusing to install into {hooks} -- that directory is outside this "
            f"repository git directory ({common}), so it is shared with other "
            "repositories and a refusing hook there would arm all of them. Install "
            "per clone, into its own hooks directory."
        )
    return hooks


def hooks_reachable(repo: Path, hook_name: str) -> tuple[bool, str]:
    """Will git actually run `<git-common-dir>/hooks/<hook_name>` for this clone?

    THE QUESTION AN INSTALLER MUST ASK AND DID NOT (OMN-18273). `core.hooksPath`
    REPLACES git's hook lookup outright -- git never falls back to the clone's
    own hooks directory. So a hook file written into `<git-common-dir>/hooks` on
    a clone whose `core.hooksPath` is overridden is dead bytes unless the
    override directory carries an entry of the SAME NAME that chains back.

    This workspace's override is `scripts/git-hooks/canonical-clone`, whose
    per-hook-type symlinks resolve to `canonical_clone_guard.sh`, and that guard
    ends by exec-ing `<git-common-dir>/hooks/<hook_name>`. Its symlink set was
    `pre-commit commit-msg pre-push pre-merge-commit` -- `prepare-commit-msg` was
    never in it, so the stamping hook had no dispatch entry even had it been
    installable. Both halves had to be wrong for the mechanism to be inert, and
    both were.

    Returns (reachable, human-readable reason). A caller that cannot prove
    reachability must say so rather than report a successful install: an install
    that reports success and never runs is the failure this whole ticket is.
    """
    override = configured_hooks_path(repo)
    if override is None:
        return True, "core.hooksPath is unset, so git uses the clone's own hooks"
    entry = override / hook_name
    if not entry.exists():
        return False, (
            f"core.hooksPath is {override} and it has no '{hook_name}' entry, so git "
            f"will never dispatch this hook type. Add the chaining entry with:\n"
            f"    python3 {Path(__file__).resolve()} reconcile --execute"
        )
    if not os.access(entry, os.X_OK):
        return False, f"{entry} exists but is not executable, so git cannot run it"
    return True, f"{entry} dispatches this hook type and chains to the clone's own"


def _git_env() -> dict[str, str]:
    """The ambient environment with every GIT_* variable removed.

    This matters in production, not only in tests. Git exports GIT_DIR and
    GIT_INDEX_FILE to the hooks it runs, and GIT_DIR is frequently the relative
    string ".git". A `git log` launched from inside a hook therefore reads the
    HOOK OWNER repository no matter which directory it is pointed at -- so a
    window check invoked from a hook silently answered about the wrong
    repository, reporting its commits as the findings. Caught by running the
    check inside a real `git commit` rather than beside one.
    """
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def unstamped_commits(repo: Path, rev_range: str) -> list[tuple[str, str]]:
    """Commits in `rev_range` carrying no resolvable lane identity, as
    (sha, subject).

    Merge commits are exempt: git writes them, not a lane, and refusing them
    would make the check fire on the correct behaviour.

    This is the phase 5 AC3 window check. Note what it does NOT do: it cannot
    confirm the identifier resolves to exactly one claim row, because the claim
    index that answers that lands in OMN-18261. Presence and shape are what this
    half proves, and saying so is better than implying the whole criterion is
    closed here.
    """
    return [
        (sha, subject)
        for sha, subject, message in commits_in_range(repo, rev_range)
        if commit_identity(message) is None
    ]


def commits_in_range(
    repo: Path, rev_range: str | Sequence[str]
) -> list[tuple[str, str, str]]:
    """Every non-merge commit in `rev_range` as (sha, subject, full message).

    Extracted from `unstamped_commits` (OMN-18263) so the branch-claim
    resolution reads commits through the SAME invocation. That matters for one
    measured reason: the environment scrub below. A `git log` launched from
    inside a hook inherits GIT_DIR and answers about the HOOK OWNER repository
    whatever directory it is pointed at, and a second copy of this call is a
    second chance to omit the scrub.
    """
    separator = "\x1e"
    revs = [rev_range] if isinstance(rev_range, str) else list(rev_range)
    completed = subprocess.run(
        ["git", "log", "--no-merges", f"--format=%H%x1f%s%x1f%B{separator}", *revs],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
        env=_git_env(),
    )
    if completed.returncode != 0:
        # A range git cannot resolve must be an ERROR, never an empty result.
        # An unresolvable range returns no commits, which reads exactly like
        # "every commit is stamped" -- a zero that is not evidence of absence
        # (CLAUDE.md rule 16). Found by running the check with a bad range
        # against a one-commit repository, where it raised an unhandled
        # traceback instead of saying so.
        raise BadRange(f"git could not resolve {revs!r}: {completed.stderr.strip()}")
    out = completed.stdout
    commits: list[tuple[str, str, str]] = []
    for chunk in out.split(separator):
        if not chunk.strip():
            continue
        sha, _, rest = chunk.lstrip("\n").partition("\x1f")
        subject, _, message = rest.partition("\x1f")
        commits.append((sha, subject, message))
    return commits


# ---------------------------------------------------------------------------
# Arming: installation, reachability, policy, reconcile  (OMN-18273)
# ---------------------------------------------------------------------------

# The hook types this workspace's shared guard must dispatch for the lane
# mechanism to run at all. `prepare-commit-msg` is the one that was missing.
CHAINED_HOOK_TYPES = (
    "prepare-commit-msg",
    "pre-commit",
    "commit-msg",
    "pre-push",
    "pre-merge-commit",
)

PRIOR_SUFFIX = ".onex-prior"

# Marks a hook file as one of ours, so a re-install is idempotent and a
# pre-existing third-party hook is never mistaken for a previous install of
# this one and discarded.
OURS_MARKER = "# onex-lane-hook: managed by lane_identity.py"

_UNREGISTERED_MODES = ("silent", "refuse")


def policy_path(base: Path) -> Path:
    return _registry_dir(base) / "policy.json"


def unregistered_mode(base: Path) -> str:
    """What the stamping hook does in a worktree with no lane identity.

    DEFAULT `silent`, and that is a deliberate departure from the design of
    record (OMN-18259 §3), recorded here rather than buried in a commit message.

    The design says the stamping hook REFUSES an unregistered worktree, on the
    argument that a trailer which can be wrong is worse than one that is absent.
    That argument is about STAMPING and it still holds -- nothing here ever
    stamps a guessed lane. It is not an argument for refusing the commit, and
    arming a refusal is a different act with a different blast radius: this
    workspace carries 454 worktrees that predate the mechanism, so installing a
    refusing stamping hook today freezes every one of them. That is precisely
    the ten-minute fleet-wide freeze the OMN-18260 development incident already
    produced once, at a larger scale.

    Absence also costs the downstream gate nothing it can use: the pre-push
    refusal already reports-and-allows a commit carrying no lane trailer, by its
    own documented design, because on install day that is every commit.

    So the refusal is kept and made an explicit, reversible decision --
    `lane_identity policy --unregistered refuse` -- which is the sequencing
    question the design left open for the operator (§7), answered by a verb
    rather than by an install side effect.
    """
    try:
        data = json.loads(policy_path(base).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "silent"
    mode = data.get("unregistered")
    return mode if mode in _UNREGISTERED_MODES else "silent"


def set_unregistered_mode(base: Path, mode: str) -> None:
    if mode not in _UNREGISTERED_MODES:
        raise ValueError(
            f"unregistered mode {mode!r} is not one of {_UNREGISTERED_MODES}"
        )
    path = policy_path(base)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"unregistered": mode}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def install_hook(
    repo: Path,
    *,
    source: Path,
    hook_name: str,
    placeholder: str,
    module: Path,
) -> tuple[Path, str]:
    """Install `source` as `<git-common-dir>/hooks/<hook_name>`, chain-safely.

    CHAIN, NEVER CLOBBER. Every canonical clone in this registry already carries
    a `pre-push` written by the pre-commit framework -- the governed
    impacted-test selector runs from it. The shipped installer wrote its own
    file over that path unconditionally, which would have silently removed the
    repository's real pre-push gate on the first successful install. A prior
    hook that is not ours is moved aside to `<hook_name>.onex-prior` and the
    installed hook execs it as its last act, so the existing gate keeps running
    and keeps its exit status.

    Returns (target, reachability reason). The caller decides what an
    unreachable install means; this function does not report success for one.
    """
    hooks = own_hooks_dir(repo)
    hooks.mkdir(parents=True, exist_ok=True)
    target = hooks / hook_name
    prior = hooks / f"{hook_name}{PRIOR_SUFFIX}"

    if target.exists():
        existing = ""
        try:
            existing = target.read_text(encoding="utf-8", errors="replace")
        except OSError:
            existing = ""
        if OURS_MARKER not in existing:
            # Somebody else's hook. Preserve it, once: a second install must not
            # overwrite the preserved original with our own previous copy.
            if not prior.exists():
                target.replace(prior)
                prior.chmod(0o755)
            else:
                target.unlink()

    body = source.read_text(encoding="utf-8").replace(
        placeholder, str(module.resolve())
    )
    target.write_text(body, encoding="utf-8")
    target.chmod(0o755)
    _, reason = hooks_reachable(repo, hook_name)
    return target, reason


def shared_guard_dir(repo: Path) -> Path | None:
    """The shared `core.hooksPath` directory for this clone, when it has one."""
    return configured_hooks_path(repo)


def ensure_chained_entries(repo: Path, *, execute: bool) -> list[str]:
    """Give the shared guard directory a dispatch entry for every hook type we
    need, copying whatever mechanism its existing entries already use.

    A new entry is a symlink to the SAME target the directory's existing entries
    resolve to, read from the directory itself rather than named here. Naming
    the guard script in this file would make an omniclaude module depend on the
    exact layout of an untracked local script, and the two would drift the first
    time either moved.
    """
    override = shared_guard_dir(repo)
    if override is None or not override.is_dir():
        return []
    existing = [p for p in override.iterdir() if p.is_symlink()]
    if not existing:
        return []
    link_target = existing[0].readlink()
    added: list[str] = []
    for hook_name in CHAINED_HOOK_TYPES:
        entry = override / hook_name
        if entry.exists() or entry.is_symlink():
            continue
        added.append(str(entry))
        if execute:
            entry.symlink_to(link_target)
    return added


def worktree_dirs(worktrees_root: Path) -> list[tuple[Path, str]]:
    """Every `<worktrees-root>/<TICKET>/<repo>` directory that is a git worktree,
    paired with its ticket, read from the path convention of CLAUDE.md rule 9."""
    found: list[tuple[Path, str]] = []
    if not worktrees_root.is_dir():
        return found
    for ticket_dir in sorted(worktrees_root.iterdir()):
        if not ticket_dir.is_dir():
            continue
        ticket = ticket_dir.name.upper()
        if not _TICKET_RE.match(ticket):
            continue
        for repo_dir in sorted(ticket_dir.iterdir()):
            if (repo_dir / ".git").exists():
                found.append((repo_dir, ticket))
    return found


def claim_holders(
    ledger_text: str, ledger_name: str, claim_index: Any
) -> dict[str, str]:
    """Ticket -> LIVE holder lane, resolved by the authoritative claim index.

    ONE RESOLUTION, NOT A SECOND PARSER. The claim store is the ledger and the
    index that replays it is the only thing allowed to say who holds a ticket
    (OMN-18259 section 4). A backfill that scanned CLAIM rows with its own
    regular expression would be a second reader of the same store, and the two
    would disagree the first time either moved -- which is the whole argument
    the design makes against a second store.

    Using the index also makes the backfill honest about STALENESS. A ticket
    whose holder has written nothing for the staleness window has no live
    holder, so its worktree stays unregistered rather than being stamped with
    the name of a lane that stopped days ago. A trailer naming a dead lane is
    a wrong trailer, and a wrong trailer is the one outcome ruled out.
    """
    index = claim_index.build_index(ledger_text, ledger_name, now=datetime.now(UTC))
    holders: dict[str, str] = {}
    for ticket in index.get("tickets", {}):
        held = claim_index.holder(index, ticket)
        if held is not None and valid_lane(getattr(held, "lane", "")):
            holders[ticket] = held.lane
    return holders


# ---------------------------------------------------------------------------
# Arming READBACK: does an armed clone actually let a commit through? (OMN-18288)
# ---------------------------------------------------------------------------

# The outcomes a probe of one clone/worktree pair can have. Named rather than
# spelled at each use site so the JSON report, the human report and the tests
# cannot drift into three vocabularies for the same fact.
PROBE_ALLOWED = "ALLOWED"
PROBE_REFUSED = "REFUSED"
PROBE_UNPROBED = "UNPROBED"


@dataclass(frozen=True)
class ProbeResult:
    """One clone/worktree pair, run through the INSTALLED hook.

    `stamped` is meaningful only for a registered worktree: it says the hook
    did its work, not merely that it declined to block. An `ALLOWED` that
    stamped nothing where a lane IS registered is a silently inert hook, which
    is the exact failure OMN-18273 found three days of, and it is reported as a
    refusal-class defect rather than a pass.
    """

    clone: str
    worktree: str
    case: str
    outcome: str
    stamped: bool
    detail: str

    def as_dict(self) -> dict[str, object]:
        return {
            "clone": self.clone,
            "worktree": self.worktree,
            "case": self.case,
            "outcome": self.outcome,
            "stamped": self.stamped,
            "detail": self.detail,
        }


def clone_worktrees(clone: Path) -> list[Path]:
    """Every working tree attached to `clone`, the main one included.

    Read from `git worktree list`, never from the path convention: a worktree
    parked outside `omni_worktrees/` is still a directory whose commits this
    hook governs, and a probe that could not see it would report a pass over a
    surface it never looked at.
    """
    completed = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=clone,
        check=False,
        capture_output=True,
        text=True,
        env=_git_env(),
    )
    if completed.returncode != 0:
        return []
    return [
        Path(line[len("worktree ") :].strip())
        for line in completed.stdout.splitlines()
        if line.startswith("worktree ")
    ]


def run_installed_hook(
    worktree: Path,
    hook: Path,
    *,
    message: str = "probe: lane identity arming readback",
    env_overrides: dict[str, str] | None = None,
) -> tuple[int, str, str]:
    """Invoke `hook` exactly as git invokes `prepare-commit-msg`, and return
    (exit status, the message file's contents afterwards, stderr).

    A REAL INVOCATION OF THE INSTALLED BYTES, not an import of the module they
    call. The defect this probe exists to catch is a hook that refuses or does
    nothing in a clone, and both of those live in the shell file, the baked-in
    module path and the interpreter search -- none of which an import exercises.
    OMN-18273 is the precedent: every test that only read the script passed
    while the installed copy skipped the path it had just baked in.

    No commit is created, and NOTHING IS WRITTEN INTO THE WORKING TREE. The
    scratch message file lives in a temporary directory, because the probe
    sweeps clones whose worktrees belong to OTHER live lanes and a file
    appearing in a peer's `git status` -- even for the length of one
    subprocess -- is the probe creating the interference it is auditing for.
    Only the working DIRECTORY is the worktree, which is what the hook reads
    its lane from. git's contract for this hook is exactly
    (message file, source, [sha]), so this is the whole behaviour.
    """
    env = _git_env()
    if env_overrides:
        env.update(env_overrides)
    with tempfile.TemporaryDirectory(prefix="onex-lane-probe-") as tmp:
        scratch = Path(tmp) / "COMMIT_EDITMSG"
        scratch.write_text(message + "\n", encoding="utf-8")
        completed = subprocess.run(
            [str(hook), str(scratch), "message"],
            cwd=worktree,
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        try:
            written = scratch.read_text(encoding="utf-8")
        except OSError:
            written = ""
        return completed.returncode, written, completed.stderr


def probe_clone(base: Path, clone: Path) -> list[ProbeResult]:
    """Run the installed hook in `clone`, once per probeable working tree.

    TWO CASES, because the 2026-09-13 incident produced both at once. A
    registered worktree must be ALLOWED and must come back STAMPED. An
    unregistered directory -- the canonical clone itself is always one -- must
    behave as the declared policy says: allowed under `silent`, refused under
    `refuse`. Probing only the registered case would report a pass over the
    exact surface that froze, since it was the unregistered worktrees that
    every clone briefly refused.
    """
    try:
        hook = own_hooks_dir(clone) / "prepare-commit-msg"
    except (SharedHooksDirectory, subprocess.CalledProcessError, OSError) as exc:
        return [
            ProbeResult(
                clone=clone.name,
                worktree=str(clone),
                case="registered",
                outcome=PROBE_UNPROBED,
                stamped=False,
                detail=f"hooks directory did not resolve: {exc}",
            )
        ]

    installed = hook.is_file() and OURS_MARKER in hook.read_text(
        encoding="utf-8", errors="replace"
    )
    reachable, reason = hooks_reachable(clone, "prepare-commit-msg")
    if not (installed and reachable):
        return [
            ProbeResult(
                clone=clone.name,
                worktree=str(clone),
                case="registered",
                outcome=PROBE_UNPROBED,
                stamped=False,
                detail=f"not armed ({'installed' if installed else 'not installed'}; {reason})",
            )
        ]

    policy = unregistered_mode(base)
    results: list[ProbeResult] = []

    # THE HOOK MUST RESOLVE THE REGISTRY THIS PROBE IS ASKING ABOUT. The hook
    # runs as a subprocess and reads its registry from the environment, so
    # without this a probe pointed at one registry would grade a hook that
    # answered from another -- and the mismatch presents as "installed but
    # stamps nothing", i.e. as a defect in the clone rather than in the probe.
    probed_registry = {"ONEX_LANE_REGISTRY_ROOT": str(base)}

    registered = [wt for wt in clone_worktrees(clone) if resolve(base, wt) is not None]
    if registered:
        target, case = registered[0], "registered"
        record = resolve(base, target)
        assert record is not None  # noqa: S101 - filtered above
        lane = record.lane
        overrides = probed_registry
        synthetic_dir = None
    else:
        # NO LIVE LANE HOLDS A WORKING TREE OF THIS CLONE, and reporting that as
        # UNPROBED would leave the acceptance criterion answered for some clones
        # and unanswered for the rest -- exactly the per-clone gap the criterion
        # names ("not a single spot check"). So the registered path is exercised
        # against a registration this probe makes for itself, in a throwaway
        # registry the environment points the hook at, and the row says
        # `registered-synthetic` so nobody reads it as a live lane's evidence.
        #
        # The identity is synthetic; the CODE PATH is not. The hook resolves its
        # registry from the same environment key in both cases and runs the same
        # resolution, stamping and chaining. What this cannot show is that some
        # particular lane is registered -- which is a fact about the registry,
        # reported by `status`, not about whether the clone refuses.
        synthetic_dir = tempfile.mkdtemp(prefix="onex-lane-probe-registry-")
        lane = "probe-arming-readback"
        register(Path(synthetic_dir), clone, lane=lane, ticket="OMN-18288")
        target = clone
        case = "registered-synthetic"
        overrides = {"ONEX_LANE_REGISTRY_ROOT": synthetic_dir}

    try:
        status, written, stderr = run_installed_hook(
            target, hook, env_overrides=overrides
        )
        stamped = f"{LANE_TRAILER}: {lane}" in written
        if status != 0:
            last = stderr.strip().splitlines()[-1] if stderr.strip() else "no stderr"
            detail = f"hook exited {status}: {last}"
            outcome = PROBE_REFUSED
        elif not stamped:
            detail = (
                "hook allowed the commit but stamped no lane trailer, so it is inert -- "
                "an allowed commit with no identity is what the downstream refusal "
                "cannot tell from a wrong one"
            )
            outcome = PROBE_REFUSED
        else:
            detail = f"allowed and stamped {LANE_TRAILER}: {lane}"
            outcome = PROBE_ALLOWED
        results.append(
            ProbeResult(
                clone=clone.name,
                worktree=str(target),
                case=case,
                outcome=outcome,
                stamped=stamped,
                detail=detail,
            )
        )
    finally:
        if synthetic_dir is not None:
            shutil.rmtree(synthetic_dir, ignore_errors=True)

    # The clone root is unregistered by construction: no lane registers the
    # canonical clone, because no lane commits there.
    if resolve(base, clone) is None:
        status, _, stderr = run_installed_hook(
            clone, hook, env_overrides=probed_registry
        )
        allowed = status == 0
        expected_allowed = policy == "silent"
        if allowed == expected_allowed:
            outcome = PROBE_ALLOWED if allowed else PROBE_REFUSED
            detail = f"unregistered directory behaved as the `{policy}` policy declares"
        else:
            outcome = PROBE_REFUSED if not allowed else PROBE_ALLOWED
            detail = (
                f"unregistered directory exited {status} under the `{policy}` policy, "
                f"which is not what that policy declares"
            )
        results.append(
            ProbeResult(
                clone=clone.name,
                worktree=str(clone),
                case=f"unregistered/{policy}",
                outcome=outcome,
                stamped=False,
                detail=detail
                + (
                    f": {stderr.strip().splitlines()[-1]}"
                    if not allowed and stderr.strip()
                    else ""
                ),
            )
        )
    return results


def probe_refusals(results: Sequence[ProbeResult], base: Path) -> list[ProbeResult]:
    """The results that are DEFECTS, given the declared policy.

    A refusal is only a defect when the policy says the commit should have been
    allowed. Under `refuse`, an unregistered directory refusing is the
    mechanism working, and counting it as a failure would make the probe red
    exactly when the workspace is most strictly armed.
    """
    policy = unregistered_mode(base)
    defects = []
    for r in results:
        if r.case.startswith("registered") and r.outcome == PROBE_REFUSED:
            defects.append(r)
        elif r.case.startswith("unregistered/"):
            expected = PROBE_ALLOWED if policy == "silent" else PROBE_REFUSED
            if r.outcome != expected:
                defects.append(r)
    return defects


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _base(args: argparse.Namespace) -> Path:
    if getattr(args, "registry_root", None):
        return Path(args.registry_root)
    try:
        return registry_root_from_env()
    except KeyError:
        print(
            "lane_identity: neither ONEX_LANE_REGISTRY_ROOT nor OMNI_HOME is set, so the "
            "lane registry has no home. Set one; there is deliberately no default "
            "(CLAUDE.md rule 8).",
            file=sys.stderr,
        )
        raise SystemExit(2) from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--registry-root", help="override the registry location")
    sub = parser.add_subparsers(dest="command", required=True)

    p_reg = sub.add_parser("register", help="register this worktree as a lane")
    p_reg.add_argument("--lane", required=True)
    p_reg.add_argument("--ticket", required=True)
    p_reg.add_argument("--worktree", default=".")
    p_reg.add_argument("--session")

    p_res = sub.add_parser(
        "resolve", help="print this worktree's lane identity as JSON"
    )
    p_res.add_argument("--worktree", default=".")

    p_tr = sub.add_parser(
        "trailers", help="print the commit trailers for this worktree"
    )
    p_tr.add_argument("--worktree", default=".")

    p_ver = sub.add_parser(
        "verify", help="fail if any commit in a range carries no lane identity"
    )
    p_ver.add_argument("--repo", default=".")
    p_ver.add_argument("--range", dest="rev_range", required=True)

    p_inst = sub.add_parser(
        "install-hook", help="install the prepare-commit-msg hook in a clone"
    )
    p_inst.add_argument("--repo", default=".")

    p_pol = sub.add_parser(
        "policy",
        help="read or set what the stamping hook does in an unregistered worktree",
    )
    p_pol.add_argument("--unregistered", choices=list(_UNREGISTERED_MODES))

    p_stat = sub.add_parser(
        "status",
        help="report whether the mechanism is armed on this host; nonzero when it is not",
    )
    p_stat.add_argument(
        "--repo",
        action="append",
        default=None,
        help="a clone to check; repeatable. Defaults to every clone in the workspace",
    )
    p_stat.add_argument("--json", action="store_true")

    p_probe = sub.add_parser(
        "probe",
        help=(
            "run the INSTALLED hook in every canonical clone and report, per clone, "
            "whether a commit from a registered worktree is allowed and stamped"
        ),
    )
    p_probe.add_argument(
        "--repo",
        action="append",
        default=None,
        help="a clone to probe; repeatable. Defaults to every clone in the workspace",
    )
    p_probe.add_argument("--json", action="store_true")

    p_rec = sub.add_parser(
        "reconcile",
        help="arm every canonical clone and register the worktrees whose lane the ledger resolves",
    )
    p_rec.add_argument(
        "--execute", action="store_true", help="apply; default is a dry run"
    )
    p_rec.add_argument("--workspace-root", default=None)
    p_rec.add_argument(
        "--ledger",
        default=None,
        help="claim store to backfill registrations from; defaults to the workspace ledger",
    )

    args = parser.parse_args(argv)

    if args.command == "register":
        try:
            record = register(
                _base(args),
                Path(args.worktree),
                lane=args.lane,
                ticket=args.ticket,
                session_id=args.session,
            )
        except ValueError as exc:
            print(f"lane_identity: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(record.as_dict(), indent=2, sort_keys=True))
        return 0

    if args.command == "resolve":
        resolved = resolve(_base(args), Path(args.worktree))
        if resolved is None:
            print(
                f"lane_identity: {Path(args.worktree).resolve()} has no lane",
                file=sys.stderr,
            )
            return 3
        print(json.dumps(resolved.as_dict(), indent=2, sort_keys=True))
        return 0

    if args.command == "trailers":
        base = _base(args)
        try:
            for line in trailer_lines(base, Path(args.worktree)):
                print(line)
        except UnregisteredLane as exc:
            # Exit 3 is the hook's REFUSE contract. Under the default `silent`
            # policy an unregistered worktree exits 0 printing nothing, and the
            # hook stamps nothing and allows the commit -- see
            # `unregistered_mode` for why that is the default and how a refusing
            # workspace is armed deliberately.
            if unregistered_mode(base) == "refuse":
                print(f"lane_identity: {exc} has no lane", file=sys.stderr)
                return 3
            return 0
        return 0

    if args.command == "verify":
        try:
            findings = unstamped_commits(Path(args.repo), args.rev_range)
        except BadRange as exc:
            print(f"lane_identity: {exc}", file=sys.stderr)
            return 2
        if not findings:
            print(
                f"lane_identity: every commit in {args.rev_range} carries a lane identity"
            )
            return 0
        print(
            f"lane_identity: {len(findings)} commit(s) in {args.rev_range} carry no resolvable "
            f"lane identity:",
            file=sys.stderr,
        )
        for sha, subject in findings:
            print(f"  {sha[:12]} {subject}", file=sys.stderr)
        print(
            "Each lane registers once per worktree:\n"
            "  python3 scripts/lane_identity.py register --lane <slug> --ticket OMN-XXXX",
            file=sys.stderr,
        )
        return 1

    if args.command == "install-hook":
        repo = Path(args.repo)
        try:
            # Bake the module's absolute path into the copy. The hook then needs
            # no environment variable at commit time, which removes the failure
            # mode where a correctly installed hook cannot find its own module on
            # a box that does not export the workspace variable.
            target, reason = install_hook(
                repo,
                source=Path(__file__).resolve().parent
                / "hooks"
                / "prepare-commit-msg-lane",
                hook_name="prepare-commit-msg",
                placeholder="@LANE_IDENTITY_PATH@",
                module=Path(__file__),
            )
        except SharedHooksDirectory as exc:
            print(f"lane_identity: {exc}", file=sys.stderr)
            return 2
        print(f"lane_identity: installed {target}")
        reachable, _ = hooks_reachable(repo, "prepare-commit-msg")
        if not reachable:
            # An install that git will never dispatch is the defect this ticket
            # exists to remove. Say so with a nonzero exit rather than printing
            # a success line over an inert file.
            print(f"lane_identity: NOT REACHABLE -- {reason}", file=sys.stderr)
            return 4
        print(f"lane_identity: reachable -- {reason}")
        return 0

    if args.command == "policy":
        base = _base(args)
        if args.unregistered:
            set_unregistered_mode(base, args.unregistered)
        print(json.dumps({"unregistered": unregistered_mode(base)}, indent=2))
        return 0

    if args.command == "status":
        return _status(args)

    if args.command == "probe":
        return _probe(args)

    if args.command == "reconcile":
        return _reconcile(args)

    return 2


def _registry_clones(root: Path) -> list[Path]:
    """Every git CLONE in the workspace: the ROOT itself when it is one, plus
    each of its children that is one. Read from the filesystem, never from a
    hardcoded list: a list in this file goes stale the first time a repository
    is added, and a clone missing from it reads as armed because it was never
    checked.

    THE ROOT IS ONE OF THEM (OMN-18792). This walked `root.iterdir()` alone, and
    a directory is not its own child, so the registry repository at the
    workspace root was never enumerated -- not unarmed and reported, ABSENT.
    Measured on this host 2026-09-19T01:45Z: `status` printed `26/26 clones
    armed` and the root was in neither number. That is the shape CLAUDE.md rule
    16 refuses, because a surface nobody enumerates is indistinguishable from
    one that passed, and it left the single repository where many concurrent
    lanes commit into a SHARED working tree (rule 19) as the only one with no
    stamping hook -- the repository where per-commit attribution matters most.

    A worktree is still excluded, at the root as at any child: `.git` is a FILE
    in a linked worktree and a directory in a clone, which is the same
    predicate both places. So a workspace root that is itself a worktree
    enumerates its children and not itself, and `omni_worktrees/`, which
    carries no `.git` at all, is a clone nowhere.

    ARMED IS NOT REGISTERED, and for the shared root that distinction is
    deliberate. Arming installs the hook; it stamps nothing until some registry
    resolves a lane for the directory being committed in. The shared registry
    deliberately holds no record for the workspace root, because `resolve`
    walks upward and one record there would answer for every path beneath it
    that has none -- including the worktrees `_reconcile` leaves unregistered
    on purpose when no live claim holder resolves. A lane that wants its own
    commits in the shared tree stamped points `ONEX_LANE_REGISTRY_ROOT` at a
    registry of its own, which no peer process reads. Pinned by
    `test_a_registration_on_the_root_reaches_every_unregistered_path_beneath_it`.
    """
    clones: list[Path] = []
    seen: set[Path] = set()

    def _add(candidate: Path) -> None:
        if not (candidate / ".git").is_dir():
            return
        try:
            key = candidate.resolve()
        except OSError:
            return
        if key in seen:
            return
        seen.add(key)
        clones.append(candidate)

    # The root first, so the row that used to be missing is the row that leads
    # the report rather than one sorted into the middle of the children.
    _add(root)
    for child in sorted(root.iterdir()):
        if child.name.startswith("."):
            continue
        # `seen` rather than a name comparison: a child that is a symlink back
        # to the workspace root resolves to a path already added, and counting
        # it twice would double every install and make the armed/total ratio
        # `status` prints unreadable.
        _add(child)
    return clones


def _status(args: argparse.Namespace) -> int:
    base = _base(args)
    if args.repo:
        repos = [Path(r) for r in args.repo]
    else:
        try:
            repos = _registry_clones(Path(os.environ[WORKSPACE_ENV]))
        except KeyError:
            print(f"lane_identity: {WORKSPACE_ENV} is not set", file=sys.stderr)
            return 2

    registry = _registry_dir(base)
    registrations = len(list(registry.glob("*.json"))) if registry.is_dir() else 0

    rows = []
    unarmed = 0
    for repo in repos:
        try:
            hooks = own_hooks_dir(repo)
        except (SharedHooksDirectory, subprocess.CalledProcessError, OSError):
            # Not a resolvable clone. Skipped, and the empty-sweep refusal below
            # is what stops a run that skipped everything from reading as a pass.
            continue
        hook = hooks / "prepare-commit-msg"
        installed = hook.is_file() and OURS_MARKER in hook.read_text(
            encoding="utf-8", errors="replace"
        )
        reachable, reason = hooks_reachable(repo, "prepare-commit-msg")
        armed = installed and reachable
        if not armed:
            unarmed += 1
        rows.append(
            {
                "repo": repo.name,
                "installed": installed,
                "reachable": reachable,
                "armed": armed,
                "reason": reason,
            }
        )

    report = {
        "armed_clones": sum(1 for r in rows if r["armed"]),
        "clones": len(rows),
        "registrations": registrations,
        "unregistered_policy": unregistered_mode(base),
        "repos": rows,
    }
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        for row in rows:
            mark = "ARMED   " if row["armed"] else "UNARMED "
            print(f"{mark} {row['repo']}: {row['reason']}")
        print(
            f"lane_identity: {report['armed_clones']}/{report['clones']} clones armed, "
            f"{registrations} worktree registration(s), "
            f"unregistered policy = {report['unregistered_policy']}"
        )
    if not rows:
        print(
            "lane_identity: no clones were checked, which is not the same as none "
            "being unarmed -- refusing to report a pass on an empty sweep "
            "(CLAUDE.md rule 16).",
            file=sys.stderr,
        )
        return 2
    if unarmed:
        print(
            f"lane_identity: {unarmed} clone(s) are NOT armed, so commits there carry no "
            f"lane identity and the pre-push refusal has nothing to compare. Arm with:\n"
            f"    python3 {Path(__file__).resolve()} reconcile --execute",
            file=sys.stderr,
        )
        return 1
    return 0


def _probe(args: argparse.Namespace) -> int:
    """The AC(c) readback: a real hook invocation per clone, reported per clone.

    NOT A SPOT CHECK, and the acceptance criterion says so in those words. One
    clone answering correctly says nothing about the other twenty-five: the
    install is per clone, the shared guard dispatch is per hook type, and the
    registration is per worktree, so every one of the three can be right in one
    clone and wrong in the next.
    """
    base = _base(args)
    if args.repo:
        clones = [Path(r) for r in args.repo]
    else:
        try:
            clones = _registry_clones(Path(os.environ[WORKSPACE_ENV]))
        except KeyError:
            print(f"lane_identity: {WORKSPACE_ENV} is not set", file=sys.stderr)
            return 2

    results: list[ProbeResult] = []
    for clone in clones:
        results.extend(probe_clone(base, clone))

    defects = probe_refusals(results, base)
    unprobed = [r for r in results if r.outcome == PROBE_UNPROBED]
    report = {
        "clones": len({r.clone for r in results}),
        "probes": len(results),
        "refusals": len(defects),
        "unprobed": len(unprobed),
        "unregistered_policy": unregistered_mode(base),
        "results": [r.as_dict() for r in results],
    }

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        for r in results:
            print(f"{r.outcome:<9} {r.clone} [{r.case}]: {r.detail}")
        print(
            f"lane_identity: {report['probes']} probe(s) across {report['clones']} clone(s); "
            f"{report['refusals']} refusal(s), {report['unprobed']} unprobed; "
            f"unregistered policy = {report['unregistered_policy']}"
        )

    if not results or len(unprobed) == len(results):
        # The empty-sweep refusal, the same one `status` carries, widened to
        # the sweep that ASKED nothing as well as the one that looked at
        # nothing. Every row UNPROBED yields zero refusals, which reads exactly
        # like a clean bill of health while proving nothing at all
        # (CLAUDE.md rule 16).
        print(
            "lane_identity: no clone was actually probed, which is not the same as "
            "none refusing -- refusing to report a pass on an empty sweep.",
            file=sys.stderr,
        )
        return 2
    if defects:
        print(
            f"lane_identity: {len(defects)} clone/worktree pair(s) did not behave as the "
            f"`{unregistered_mode(base)}` policy declares. A clone that refuses a "
            f"registered worktree's commit freezes every lane working in it.",
            file=sys.stderr,
        )
        return 1
    return 0


def _reconcile(args: argparse.Namespace) -> int:
    base = _base(args)
    try:
        root = Path(args.workspace_root or os.environ[WORKSPACE_ENV])
    except KeyError:
        print(f"lane_identity: {WORKSPACE_ENV} is not set", file=sys.stderr)
        return 2
    execute = bool(args.execute)
    verb = "would " if not execute else ""

    clones = _registry_clones(root)
    if not clones:
        print(f"lane_identity: no clones under {root}", file=sys.stderr)
        return 2

    # 1. The shared guard needs a dispatch entry per hook type, or nothing we
    #    install into a clone's own hooks directory is ever invoked.
    announced: set[str] = set()
    for clone in clones:
        for entry in ensure_chained_entries(clone, execute=execute):
            if entry in announced:
                # Every clone shares one override directory, so a dry run would
                # otherwise report the same missing entry once per clone.
                continue
            announced.add(entry)
            print(f"lane_identity: {verb}add shared dispatch entry {entry}")

    # 2. Install into each clone's own hooks directory, chain-safely.
    failures = 0
    for clone in clones:
        if not execute:
            print(f"lane_identity: would install prepare-commit-msg in {clone.name}")
            continue
        try:
            target, reason = install_hook(
                clone,
                source=Path(__file__).resolve().parent
                / "hooks"
                / "prepare-commit-msg-lane",
                hook_name="prepare-commit-msg",
                placeholder="@LANE_IDENTITY_PATH@",
                module=Path(__file__),
            )
        except (SharedHooksDirectory, OSError) as exc:
            print(f"lane_identity: {clone.name}: {exc}", file=sys.stderr)
            failures += 1
            continue
        reachable, _ = hooks_reachable(clone, "prepare-commit-msg")
        state = "armed" if reachable else "INERT"
        if not reachable:
            failures += 1
        print(f"lane_identity: {clone.name}: {state} -- {target} ({reason})")

    # 3. Backfill registrations for worktrees whose holder the ledger resolves.
    # The same claim store the pre-push hook resolves, resolved the same way, so
    # a backfill and a refusal can never be reading two different stores.
    ledger = Path(
        args.ledger
        or os.environ.get("ONEX_BRANCH_CLAIM_LEDGER")
        or root / "docs/tracking/ROLLING_WORK_LEDGER.md"
    )
    try:
        ledger_text = ledger.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(
            f"lane_identity: cannot read the claim store {ledger}: {exc}",
            file=sys.stderr,
        )
        return 2

    # The claim index module lives in the private workspace repository. Loaded
    # by path, with importlib, exactly as the pre-push hook's resolution loads
    # it -- not through `scripts.branch_claim`, which is only importable when
    # this file is imported as part of a package and is not when it is run as a
    # script, which is how every hook and every lane invokes it.
    index_path = Path(
        os.environ.get("ONEX_BRANCH_CLAIM_INDEX_MODULE")
        or root / "docs/workflows/_shared/claim_index.py"
    )
    try:
        spec = importlib.util.spec_from_file_location("onex_claim_index", index_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"no loader for {index_path}")
        claim_index = importlib.util.module_from_spec(spec)
        # Registered BEFORE execution. `claim_index` declares frozen
        # dataclasses, and `dataclasses` resolves each class's own module out of
        # `sys.modules` while processing it; a module absent from that table
        # raises an AttributeError from inside the standard library that reads
        # like a defect in the claim index rather than in how it was loaded.
        sys.modules[spec.name] = claim_index
        spec.loader.exec_module(claim_index)
    except (OSError, ImportError, SyntaxError) as exc:
        # FAIL CLOSED ON THE BACKFILL, not on the install. The hooks above are
        # already armed and stamping is safe without any registration; what
        # cannot proceed is deciding who holds a ticket without the module that
        # decides who a holder is. Reported, never substituted with a second,
        # weaker parser -- two readers of one claim store is the drift the
        # design of record rules out.
        print(
            f"lane_identity: the claim index module at {index_path} did not load "
            f"({exc}), so NO worktree was backfilled. The hooks above are installed; "
            f"register a worktree with `register --lane <slug> --ticket OMN-XXXX`.",
            file=sys.stderr,
        )
        return 1 if failures else 0

    holders = claim_holders(ledger_text, ledger.name, claim_index)

    registered = skipped = 0
    for worktree, ticket in worktree_dirs(root / "omni_worktrees"):
        if resolve(base, worktree) is not None:
            continue
        lane = holders.get(ticket)
        if lane is None:
            # No LIVE holder. Left unregistered on purpose: a lane derived from
            # a directory name is an invented identity, and a lane whose claim
            # went stale days ago is a dead one. Either produces a wrong
            # trailer, which is the one outcome the design rules out.
            skipped += 1
            continue
        registered += 1
        if execute:
            register(base, worktree, lane=lane, ticket=ticket)

    print(
        f"lane_identity: {verb}register {registered} worktree(s) from {ledger.name}; "
        f"{skipped} left unregistered (no single claim holder resolves)"
    )
    if failures:
        print(f"lane_identity: {failures} clone(s) did not arm", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
