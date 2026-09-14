#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""worktree_auto_prune.py — content-keyed worktree pruner [OMN-16901, OMN-18370].

The fact-collecting half of the automated pruner. It walks every worktree under
the worktrees root, gathers observations from git / GitHub / the tracker / the
rolling work ledger, hands them to the **pure** predicate in
``omniclaude.hooks.lib.worktree_prune_policy``, and then either reports or acts.

Why this exists
---------------
Pruning is keyed to **what the worktree HOLDS** — operator ruling 2026-09-14,
``docs/tracking/ROLLING_WORK_LEDGER.md`` line 7870. A worktree is removable when
it is clean and zero commits ahead with no open ledger ``CLAIM``, or clean with a
MERGED pull request and no open ``CLAIM``. The ticket's own state decides
nothing: an empty or fully-merged worktree carries no work whatever the ticket
says.

That supersedes this script's original ticket-close-keyed rule, which on
2026-09-14 refused 186 provably-empty or provably-merged worktrees (82 under an
In Progress ticket) out of 751 on the host. Claim-awareness — the OMN-15551
hazard, a live lane sitting on a clean pushed tree between push and post-merge
verification — is preserved in full: an open ``CLAIM`` still blocks, and it is
now the *only* trigger-half block reason.

This script does NOT reimplement ``prune-worktrees.sh``. That script stays the
merge-keyed GC used after a batch merge sweep; this one is the claim-aware,
content-keyed sweep.

Safety posture
--------------
Dry-run is the default; ``--execute`` is required to remove anything. Removal
uses plain ``git worktree remove`` (no ``--force``) so git itself re-checks
cleanliness as a second, independent gate after the policy's. Everything that is
not prunable becomes a triage row — never a silent drop, never a deletion.

Usage
-----
    # dry run over the default root (report only, removes nothing)
    uv run python scripts/worktree_auto_prune.py

    # write the report where the daily runner expects it
    uv run python scripts/worktree_auto_prune.py \
        --report-md "$OMNI_HOME/docs/tracking/2026-08-29-worktree-prune.md" \
        --report-json "$OMNI_HOME/docs/tracking/2026-08-29-worktree-prune.json"

    # act
    uv run python scripts/worktree_auto_prune.py --execute

Pull-request state is resolved once per canonical clone with ``gh pr list``;
an unresolvable PR state simply makes limb (b) unavailable for that row, which
falls back to limb (a).

Ticket-state resolution reads ``LINEAR_API_KEY`` from the environment, falling
back to ``~/.omnibase/.env``. It is **reported context only** since the
2026-09-14 ruling — ``--no-tracker`` costs the report a column and changes no
verdict.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess  # noqa: S404 — fixed git argv lists, never shell-interpolated
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from omniclaude.hooks.lib.worktree_health import extract_ticket_id
from omniclaude.hooks.lib.worktree_prune_policy import (
    EnumBranchPrState,
    EnumDebrisRemediation,
    EnumPruneBlockReason,
    EnumPruneDisposition,
    EnumTicketLifecycle,
    ModelPartialMutationDebrisDecision,
    ModelPartialMutationDebrisFacts,
    ModelWorktreePruneDecision,
    ModelWorktreePruneFacts,
    classify_partial_mutation_debris,
    classify_worktree_prune,
)

LINEAR_API_URL = "https://api.linear.app/graphql"  # url-authority-ok: the tracker's single documented GraphQL endpoint, read-only ticket-state lookups from a local maintenance script that is not a runtime node and has no routing authority or integration catalog to resolve from
LINEAR_BATCH_SIZE = 50
BASE_REF_CANDIDATES: tuple[str, ...] = ("origin/dev", "origin/main")
GIT_TIMEOUT_SECONDS = 60

# --- timeout / load policy [OMN-18370 AC-4] --------------------------------
# On 2026-09-14 twenty `git worktree remove` calls hit the 60 s budget at host
# load 127 and were reported as removal failures indistinguishable from a real
# refusal. A timeout is a statement about the HOST, not about the worktree, so
# it is retried once when the host has actually calmed down and otherwise
# reported with the load reading that explains it.
LOAD_RETRY_THRESHOLD = 24.0
"""1-minute load average at or below which a timed-out git call is retried."""
LOAD_RETRY_MAX_WAIT_SECONDS = 120
"""How long to wait for the load to fall before giving up on the retry."""
LOAD_RETRY_POLL_SECONDS = 10
"""Interval between load readings while waiting."""

GH_TIMEOUT_SECONDS = 300
GH_MERGED_PR_LIMIT = 5000
GH_OPEN_PR_LIMIT = 500

_TICKET_RE = re.compile(r"OMN-\d+")
_CLAIM_MARKERS: tuple[str, ...] = ("| CLAIM |", "(CLAIM)", "**Status:** IN PROGRESS")
_TERMINAL_MARKERS: tuple[str, ...] = (
    "| TERMINAL |",
    "(TERMINAL)",
    "CLAIM+TERMINAL",
    "**Status:** TERMINAL",
)


# ---------------------------------------------------------------------------
# git helpers
# ---------------------------------------------------------------------------


def host_load_average() -> float | None:
    """1-minute host load average, or None where the platform cannot report it."""
    try:
        return os.getloadavg()[0]
    except (OSError, AttributeError):
        return None


class ModelGitResult(BaseModel):
    """The full outcome of one git invocation, timeouts held apart.

    A timed-out call and a refused call are not the same event and must not
    collapse into the same ``(1, "")`` [OMN-18370 AC-4]: the first says the host
    was too busy to answer, the second says git answered and said no.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    exit_code: int = Field(..., description="git's exit code; -1 when it never ran")
    stdout: str = Field(...)
    stderr: str = Field(...)
    timed_out: bool = Field(...)
    load_average: float | None = Field(
        ..., description="1-minute load read at the timeout; None otherwise"
    )

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


def _git_run(
    cwd: Path, *args: str, timeout: int = GIT_TIMEOUT_SECONDS
) -> ModelGitResult:
    """Run one git command and report exactly what happened."""
    try:
        proc = subprocess.run(  # noqa: S603 — fixed argv, no shell
            ["git", "-C", str(cwd), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return ModelGitResult(
            exit_code=-1,
            stdout="",
            stderr=f"TimeoutExpired after {timeout}s",
            timed_out=True,
            load_average=host_load_average(),
        )
    except OSError as exc:
        return ModelGitResult(
            exit_code=-1,
            stdout="",
            stderr=f"{type(exc).__name__}: {exc}",
            timed_out=False,
            load_average=None,
        )
    return ModelGitResult(
        exit_code=proc.returncode,
        stdout=proc.stdout.strip(),
        stderr=proc.stderr.strip(),
        timed_out=False,
        load_average=None,
    )


def _git_run_with_load_retry(
    cwd: Path, *args: str, timeout: int = GIT_TIMEOUT_SECONDS
) -> ModelGitResult:
    """Run a git command; on a timeout, wait for the host to calm down and retry once.

    The retry fires only when the 1-minute load average actually falls to
    :data:`LOAD_RETRY_THRESHOLD` within :data:`LOAD_RETRY_MAX_WAIT_SECONDS` —
    retrying immediately at load 127 reproduces the timeout and doubles the
    cost. When the load never falls, the original timed-out result is returned
    with its load reading intact so the report can say *why* [OMN-18370 AC-4].
    """
    result = _git_run(cwd, *args, timeout=timeout)
    if not result.timed_out:
        return result

    waited = 0
    while waited < LOAD_RETRY_MAX_WAIT_SECONDS:
        load = host_load_average()
        if load is not None and load <= LOAD_RETRY_THRESHOLD:
            retry = _git_run(cwd, *args, timeout=timeout)
            if not retry.timed_out:
                return retry
            return retry
        time.sleep(LOAD_RETRY_POLL_SECONDS)
        waited += LOAD_RETRY_POLL_SECONDS
    return result


def _git(cwd: Path, *args: str) -> tuple[int, str]:
    """Run a git command, returning ``(returncode, stripped stdout)``.

    A timeout is reported as a non-zero exit code here; call sites that must
    tell a timeout apart from a refusal use :func:`_git_run` directly.
    """
    result = _git_run(cwd, *args)
    return (1 if result.timed_out else result.exit_code), result.stdout


def _git_capture(cwd: Path, *args: str) -> tuple[int, str, str]:
    """Run a git command, returning ``(returncode, stripped stdout, stripped stderr)``.

    ``_git`` above discards stderr, which is exactly where git puts a
    refusal reason (``git worktree remove`` in particular) — that discard is
    OMN-16951 defect 1. This variant is for every call site that needs to
    report *why* git refused, not just whether it did.
    """
    result = _git_run(cwd, *args)
    return (
        (1 if result.timed_out else result.exit_code),
        result.stdout,
        result.stderr,
    )


def discover_worktrees(root: Path) -> list[Path]:
    """Return every git worktree directory under ``root``.

    A linked worktree's ``.git`` is a *file* pointing back at the canonical
    clone, which is what distinguishes it from a full clone.
    """
    found = [p.parent for p in root.glob("*/.git") if p.is_file()]
    found += [p.parent for p in root.glob("*/*/.git") if p.is_file()]
    found += [p.parent for p in root.glob("*/*/*/.git") if p.is_file()]
    return sorted(set(found))


def _inside_a_known_worktree(
    candidate: Path, root: Path, known_worktrees: set[Path]
) -> bool:
    """True when a strict ancestor of ``candidate``, between it and ``root``
    (exclusive of ``root`` itself), is a known worktree or carries its own
    ``.git`` [OMN-16951 debris-discovery fix]. A subdirectory of a healthy
    linked worktree is not debris — its parent already answered the
    `.git`/known-worktree checks, and a plain subdirectory match must not
    re-litigate that on the child.
    """
    rel_parts = candidate.relative_to(root).parts[:-1]  # exclude candidate itself
    ancestor = root
    for part in rel_parts:
        ancestor = ancestor / part
        if ancestor in known_worktrees or (ancestor / ".git").exists():
            return True
    return False


def discover_debris_directories(root: Path, known_worktrees: set[Path]) -> list[Path]:
    """Return ticket-dir children under ``root`` that carry no discoverable
    ``.git`` but still hold file content on disk [OMN-16951 defect 2].

    ``discover_worktrees`` above only finds directories via a ``*/.git`` glob,
    so a directory whose ``.git`` link is already gone is invisible to it —
    not merely unprunable, but never even reported. This walks the same three
    depths, keeps whatever is NOT a known valid worktree and NOT already
    carrying a ``.git`` of its own, and drops directories with no file content
    (``cleanup_empty_ticket_dirs`` already reclaims those; an empty leftover is
    not debris, it is nothing).

    The ``.git``/``known_worktrees`` checks below apply to ``child`` itself —
    a subdirectory of a healthy linked worktree (e.g. ``<ticket>/<repo>/src``)
    matches a deeper glob, is itself neither a known worktree nor `.git`-
    bearing, and would otherwise pass every filter. Each candidate's ancestry
    up to ``root`` is walked so a directory living inside a real worktree is
    never reported as debris [CodeRabbit, OMN-16951 PR review].
    """
    candidates: list[Path] = []
    for depth_glob in ("*/*", "*/*/*", "*/*/*/*"):
        for child in root.glob(depth_glob):
            if not child.is_dir():
                continue
            if child in known_worktrees:
                continue
            if (child / ".git").exists():
                continue
            if _inside_a_known_worktree(child, root, known_worktrees):
                continue
            if not any(p.is_file() for p in child.rglob("*")):
                continue
            candidates.append(child)

    # The three glob depths can re-match a subdirectory of an already-flagged
    # candidate (e.g. the depth-3 glob matching a folder one level inside a
    # depth-2 debris directory) — keep only the shallowest match per lineage.
    ordered = sorted(set(candidates), key=lambda p: len(p.parts))
    kept: list[Path] = []
    for candidate in ordered:
        if not any(ancestor in candidate.parents for ancestor in kept):
            kept.append(candidate)
    return sorted(kept)


def discover_canonical_clones(registry_root: Path) -> list[Path]:
    """Return every full git clone directly under ``registry_root``.

    A canonical clone's ``.git`` is a *directory*; a linked worktree's is a
    file. ``registry_root`` is conventionally ``$OMNI_HOME`` — the parent of
    the worktrees root — where every repo in the registry is cloned.
    """
    if not registry_root.is_dir():
        return []
    return [
        child
        for child in sorted(registry_root.iterdir())
        if child.is_dir() and (child / ".git").is_dir()
    ]


def collect_worktree_list_entries(canonical: Path) -> dict[str, str]:
    """Map each worktree path a canonical clone still knows about to its raw
    ``git worktree list --porcelain`` annotation state.

    The map key is the resolved absolute path as git reports it; the value is
    the ``prunable``/``locked`` annotation line(s) joined, or ``""`` for a
    clean (non-stale) record. A clone that has lost the ``.git`` link inside a
    worktree still carries this administrative record until ``git worktree
    prune`` runs — that is exactly the signal that makes a debris directory's
    removal provably safe.
    """
    code, out = _git(canonical, "worktree", "list", "--porcelain")
    if code != 0 or not out:
        return {}

    entries: dict[str, str] = {}
    current_path: str | None = None
    current_state: list[str] = []
    for line in [*out.splitlines(), ""]:
        if line.startswith("worktree "):
            current_path = line[len("worktree ") :].strip()
            current_state = []
        elif line == "":
            if current_path is not None:
                try:
                    resolved = str(Path(current_path).resolve())
                except OSError:
                    resolved = current_path
                entries[resolved] = " ".join(current_state)
            current_path = None
            current_state = []
        elif line.startswith(("prunable", "locked")):
            current_state.append(line.strip())
    return entries


def leftover_content_reachable(
    candidate: Path, canonical: Path
) -> tuple[int, tuple[str, ...]]:
    """Check every regular file under ``candidate`` against ``canonical``'s
    object database. Returns ``(file_count, unreachable_relpaths)``.

    A file's content is "reachable" when ``git hash-object`` on it matches a
    blob that already exists in the clone (``git cat-file -e``) — byte-
    identical to something already in the repo, so removing it loses nothing
    unique. This is a presence check against the object database, not a
    reachability-from-a-ref check; the object database of a canonical clone
    holds everything ever fetched, which is the conservative direction to err
    in (a blob that exists but is unreachable from any ref still proves the
    content is not unique local work).
    """
    files = sorted(p for p in candidate.rglob("*") if p.is_file())
    unreachable: list[str] = []
    for file in files:
        code, sha, _ = _git_capture(canonical, "hash-object", str(file))
        if code != 0 or not sha:
            unreachable.append(str(file.relative_to(candidate)))
            continue
        check_code, _, _ = _git_capture(canonical, "cat-file", "-e", sha)
        if check_code != 0:
            unreachable.append(str(file.relative_to(candidate)))
    return len(files), tuple(unreachable)


def collect_debris_facts(
    candidate: Path,
    root: Path,
    owner_lookup: dict[str, tuple[Path, str]],
) -> ModelPartialMutationDebrisFacts:
    """Observe one ``.git``-gone leftover directory. Pure observation."""
    rel = candidate.relative_to(root)
    ticket = extract_ticket_id(rel.parts[0])
    repo = candidate.name

    try:
        resolved = str(candidate.resolve())
    except OSError:
        resolved = str(candidate)
    owner = owner_lookup.get(resolved)
    if owner is None:
        return ModelPartialMutationDebrisFacts(
            path=str(candidate),
            ticket=ticket,
            repo=repo,
            owning_clone=None,
            worktree_list_state=None,
            file_count=0,
            unreachable_files=(),
        )

    canonical, state = owner
    file_count, unreachable = leftover_content_reachable(candidate, canonical)
    return ModelPartialMutationDebrisFacts(
        path=str(candidate),
        ticket=ticket,
        repo=repo,
        owning_clone=str(canonical),
        worktree_list_state=state,
        file_count=file_count,
        unreachable_files=unreachable,
    )


def canonical_root_of(worktree: Path) -> Path | None:
    """Resolve the canonical clone backing a linked worktree."""
    code, common_dir = _git(worktree, "rev-parse", "--git-common-dir")
    if code != 0 or not common_dir:
        return None
    common = Path(common_dir)
    if not common.is_absolute():
        common = (worktree / common).resolve()
    # <canonical>/.git  ->  <canonical>
    return common.parent if common.name == ".git" else None


def resolve_base_ref(canonical: Path) -> str | None:
    """Return the first of ``origin/dev`` / ``origin/main`` that exists."""
    for ref in BASE_REF_CANDIDATES:
        code, _ = _git(canonical, "rev-parse", "--verify", "--quiet", ref)
        if code == 0:
            return ref
    return None


def fetch_base(canonical: Path) -> None:
    """Refresh the base branches of a canonical clone, tolerating failure.

    Fetches the two candidate branches by name rather than running a bare
    ``git fetch origin``: a bare fetch aborts wholesale when any stale
    remote-tracking ref no longer exists upstream, which is routine here.
    """
    for branch in ("dev", "main"):
        _git(canonical, "fetch", "origin", f"{branch}:refs/remotes/origin/{branch}")


def stash_subjects(canonical: Path) -> list[str]:
    """Return the subject line of every stash entry in a canonical clone.

    Stashes live in the shared ``refs/stash`` of the common dir, so they are
    repo-wide; attribution to a worktree is by the branch named in the subject
    (``WIP on <branch>: ...`` / ``On <branch>: ...``).
    """
    code, out = _git(canonical, "stash", "list", "--format=%gs")
    if code != 0 or not out:
        return []
    return out.splitlines()


def count_attributed_stashes(subjects: Sequence[str], branch: str | None) -> int:
    """Count stash entries whose subject names ``branch``."""
    if branch is None:
        return 0
    needles = (f"WIP on {branch}:", f"On {branch}:")
    return sum(1 for s in subjects if any(s.startswith(n) for n in needles))


# ---------------------------------------------------------------------------
# ledger
# ---------------------------------------------------------------------------


def parse_ledger_claims(ledger_path: Path) -> dict[str, tuple[bool, str | None]]:
    """Map each ticket to ``(has_terminal, open_claim_text_or_None)``.

    The ledger is append-only, so line order is chronological order: a CLAIM
    appearing at a later line than the newest TERMINAL for the same ticket means
    a lane resumed work and the worktree must not be touched. A line carrying
    both markers (``CLAIM+TERMINAL``) resolves to TERMINAL.

    Section bodies (``- **Status:** IN PROGRESS.``) carry no ticket id of their
    own, so they inherit the ticket from the nearest preceding ``#`` heading.
    """
    if not ledger_path.is_file():
        return {}

    last_claim: dict[str, tuple[int, str]] = {}
    last_terminal: dict[str, int] = {}
    section_ticket: str | None = None

    for lineno, raw in enumerate(
        ledger_path.read_text(encoding="utf-8", errors="replace").splitlines()
    ):
        line = raw.strip()
        if line.startswith("#"):
            heading_ticket = _TICKET_RE.search(line.upper())
            section_ticket = heading_ticket.group(0) if heading_ticket else None

        is_claim = any(m in line for m in _CLAIM_MARKERS)
        is_terminal = any(m in line for m in _TERMINAL_MARKERS)
        if not (is_claim or is_terminal):
            continue

        tickets = set(_TICKET_RE.findall(line.upper()))
        if not tickets and section_ticket:
            tickets = {section_ticket}
        if not tickets:
            continue

        for ticket in tickets:
            if is_terminal:
                last_terminal[ticket] = lineno
            if is_claim:
                last_claim[ticket] = (lineno, line[:240])

    result: dict[str, tuple[bool, str | None]] = {}
    for ticket in set(last_claim) | set(last_terminal):
        terminal_line = last_terminal.get(ticket)
        claim = last_claim.get(ticket)
        open_claim: str | None = None
        if claim is not None and (terminal_line is None or claim[0] > terminal_line):
            open_claim = claim[1]
        result[ticket] = (terminal_line is not None, open_claim)
    return result


# ---------------------------------------------------------------------------
# pull-request state (GitHub) — the fact limb (b) of the ruling turns on
# ---------------------------------------------------------------------------


def collect_branch_pr_states(
    canonical: Path,
) -> dict[str, tuple[EnumBranchPrState, str | None]]:
    """Map every branch in one repository to ``(pr_state, merged_head_oid)``.

    One ``gh`` call per repository, not per worktree: a registry-scale root
    holds ~750 worktrees across ~15 clones, and a per-branch ``gh pr view``
    would be 750 API round trips.

    ``gh`` is run with ``cwd`` inside the clone so it resolves the repository
    from that clone's own ``origin`` remote — never from a repo slug this
    script guesses from a directory name.

    A failure of either call leaves the affected branches absent from the map,
    which the caller reads as :data:`EnumBranchPrState.UNKNOWN`: limb (b) is
    then unavailable and the row falls back to limb (a). An empty result is
    never read as "no PR exists".
    """
    states: dict[str, tuple[EnumBranchPrState, str | None]] = {}

    def _gh(*args: str) -> list[dict[str, Any]] | None:
        try:
            proc = subprocess.run(  # noqa: S603 — fixed argv, no shell
                ["gh", *args],
                cwd=str(canonical),
                capture_output=True,
                text=True,
                timeout=GH_TIMEOUT_SECONDS,
                check=False,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            print(
                f"  gh: {canonical.name}: {type(exc).__name__}: {exc}", file=sys.stderr
            )
            return None
        if proc.returncode != 0:
            print(
                f"  gh: {canonical.name}: exit {proc.returncode}: "
                f"{proc.stderr.strip()[:200]}",
                file=sys.stderr,
            )
            return None
        try:
            parsed = json.loads(proc.stdout or "[]")
        except ValueError as exc:
            print(f"  gh: {canonical.name}: unparseable JSON: {exc}", file=sys.stderr)
            return None
        return parsed if isinstance(parsed, list) else None

    # Open first, merged second: a branch that was reused after its PR merged
    # should read MERGED only when the merged head is still its HEAD, and the
    # merged entry carries the oid that decides that.
    open_rows = _gh(
        "pr",
        "list",
        "--state",
        "open",
        "--limit",
        str(GH_OPEN_PR_LIMIT),
        "--json",
        "headRefName",
    )
    for row in open_rows or []:
        name = row.get("headRefName")
        if name:
            states[name] = (EnumBranchPrState.NOT_MERGED, None)

    merged_rows = _gh(
        "pr",
        "list",
        "--state",
        "merged",
        "--limit",
        str(GH_MERGED_PR_LIMIT),
        "--json",
        "headRefName,headRefOid",
    )
    for row in merged_rows or []:
        name = row.get("headRefName")
        if name:
            states[name] = (EnumBranchPrState.MERGED, row.get("headRefOid") or None)

    if open_rows is None and merged_rows is None:
        return {}
    return states


# ---------------------------------------------------------------------------
# tracker (Linear) — reported context only since the 2026-09-14 ruling
# ---------------------------------------------------------------------------


def load_linear_api_key() -> str | None:
    """Read ``LINEAR_API_KEY`` from the environment, else ``~/.omnibase/.env``."""
    key = os.environ.get("LINEAR_API_KEY")
    if key:
        return key
    env_file = Path.home() / ".omnibase" / ".env"
    if not env_file.is_file():
        return None
    for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if stripped.startswith("LINEAR_API_KEY="):
            return stripped.split("=", 1)[1].strip().strip("'\"") or None
    return None


def _state_type_to_lifecycle(state_type: str) -> EnumTicketLifecycle:
    if state_type == "completed":
        return EnumTicketLifecycle.DONE
    if state_type == "canceled":
        return EnumTicketLifecycle.CANCELED
    return EnumTicketLifecycle.OPEN


def resolve_ticket_states(
    tickets: Iterable[str], api_key: str
) -> dict[str, EnumTicketLifecycle]:
    """Batch-resolve ticket lifecycle states from Linear.

    Unresolvable tickets are simply absent from the result; the caller maps them
    to :data:`EnumTicketLifecycle.UNKNOWN`, which fails closed.
    """
    ordered = sorted(set(tickets))
    states: dict[str, EnumTicketLifecycle] = {}

    for start in range(0, len(ordered), LINEAR_BATCH_SIZE):
        batch = ordered[start : start + LINEAR_BATCH_SIZE]
        aliases = {f"t{i}": ident for i, ident in enumerate(batch)}
        selections = " ".join(
            f'{alias}: issue(id: "{ident}") {{ identifier state {{ type }} }}'
            for alias, ident in aliases.items()
        )
        payload = json.dumps({"query": f"query {{ {selections} }}"}).encode()
        request = urllib.request.Request(  # noqa: S310 — constant https endpoint
            LINEAR_API_URL,
            data=payload,
            headers={"Content-Type": "application/json", "Authorization": api_key},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310  # nosec B310 — constant https Linear endpoint, no user-supplied scheme
                body = json.loads(response.read().decode())
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            print(
                f"  tracker: batch {start // LINEAR_BATCH_SIZE} failed ({exc}); "
                "those tickets stay UNKNOWN and fail closed",
                file=sys.stderr,
            )
            continue

        for alias, node in (body.get("data") or {}).items():
            if not node:
                continue
            identifier = node.get("identifier") or aliases.get(alias)
            state_type = ((node.get("state") or {}).get("type")) or ""
            if identifier:
                states[identifier.upper()] = _state_type_to_lifecycle(state_type)

    return states


# ---------------------------------------------------------------------------
# fact collection
# ---------------------------------------------------------------------------


def collect_facts(
    worktree: Path,
    root: Path,
    ticket_states: dict[str, EnumTicketLifecycle],
    ledger: dict[str, tuple[bool, str | None]],
    base_ref_cache: dict[Path, str | None],
    stash_cache: dict[Path, list[str]],
    pr_state_cache: dict[Path, dict[str, tuple[EnumBranchPrState, str | None]]]
    | None = None,
) -> ModelWorktreePruneFacts:
    """Observe one worktree. Pure observation — no judgement, no mutation."""
    rel = worktree.relative_to(root)
    ticket_dir = rel.parts[0]
    ticket = extract_ticket_id(ticket_dir)

    # Every probe's exit code is checked. A git command that fails (timeout,
    # OSError, a broken gitdir pointer) returns empty stdout, and empty stdout
    # read as a fact means "clean tree" / "nothing ahead" — the two facts that
    # authorise a deletion. Each failure is recorded here and fails the safety
    # gate closed rather than being inferred away.
    unreadable_probes: list[str] = []
    # A timeout is held apart from an unreadable probe [OMN-18370 AC-4]: it says
    # the host was too busy to answer, not that the worktree is unsafe.
    timed_out_probes: list[str] = []
    load_at_timeout: float | None = None

    def _probe(name: str, *args: str) -> str:
        """Run one read-only probe, routing its failure to the right bucket."""
        nonlocal load_at_timeout
        result = _git_run(worktree, *args)
        if result.timed_out:
            timed_out_probes.append(name)
            if load_at_timeout is None:
                load_at_timeout = result.load_average
        elif result.exit_code != 0:
            unreadable_probes.append(name)
        return result.stdout

    branch_result = _git_run(worktree, "branch", "--show-current")
    # A non-zero rc here is a real failure; a zero rc with empty output is a
    # detached HEAD, which the policy already refuses on its own terms.
    if branch_result.timed_out:
        timed_out_probes.append("git branch --show-current")
        load_at_timeout = branch_result.load_average
    elif branch_result.exit_code != 0:
        unreadable_probes.append("git branch --show-current")
    branch = branch_result.stdout if branch_result.ok and branch_result.stdout else None

    status_out = _probe("git status --porcelain", "status", "--porcelain")
    dirty_files = tuple(
        line[3:].strip() for line in status_out.splitlines() if line.strip()
    )

    head_out = _probe("git rev-parse HEAD", "rev-parse", "HEAD")
    head_oid = head_out or None

    canonical = canonical_root_of(worktree)
    if canonical is None:
        base_ref = None
        stashes: list[str] = []
    else:
        if canonical not in base_ref_cache:
            base_ref_cache[canonical] = resolve_base_ref(canonical)
        base_ref = base_ref_cache[canonical]
        if canonical not in stash_cache:
            stash_cache[canonical] = stash_subjects(canonical)
        stashes = stash_cache[canonical]

    commits_ahead = 0
    unmerged: tuple[str, ...] = ()
    tree_diff_empty = False
    if base_ref is not None:
        count_result = _git_run(worktree, "rev-list", "--count", f"{base_ref}..HEAD")
        if count_result.ok and count_result.stdout.isdigit():
            commits_ahead = int(count_result.stdout)
        elif count_result.timed_out:
            timed_out_probes.append(f"git rev-list --count {base_ref}..HEAD")
            if load_at_timeout is None:
                load_at_timeout = count_result.load_average
        else:
            unreadable_probes.append(f"git rev-list --count {base_ref}..HEAD")
        if commits_ahead > 0:
            code, cherry_out = _git(worktree, "cherry", base_ref, "HEAD")
            if code == 0:
                unmerged = tuple(
                    line.split(" ", 1)[1].strip()
                    for line in cherry_out.splitlines()
                    if line.startswith("+ ")
                )
            else:
                # Unreadable cherry output must not read as "nothing unmerged".
                unreadable_probes.append(f"git cherry {base_ref} HEAD")
                unmerged = tuple(f"<unreadable:{i}>" for i in range(commits_ahead))
            # `git diff --quiet` signals its answer through the exit code: 0 =
            # no difference, 1 = differences. Anything else is a failure, and
            # must not be read as "no difference".
            code, _ = _git(worktree, "diff", "--quiet", f"{base_ref}...HEAD")
            if code not in (0, 1):
                unreadable_probes.append(f"git diff --quiet {base_ref}...HEAD")
            tree_diff_empty = code == 0

    has_terminal, open_claim = ledger.get(ticket or "", (False, None))

    pr_state = EnumBranchPrState.UNKNOWN
    pr_head_oid: str | None = None
    if branch is not None and canonical is not None and pr_state_cache is not None:
        if canonical not in pr_state_cache:
            pr_state_cache[canonical] = collect_branch_pr_states(canonical)
        repo_map = pr_state_cache[canonical]
        if repo_map:
            # A branch absent from a map that DID resolve has no pull request;
            # a branch absent from an EMPTY map proves nothing, so that case
            # stays UNKNOWN and limb (b) is simply unavailable.
            pr_state, pr_head_oid = repo_map.get(branch, (EnumBranchPrState.NONE, None))

    return ModelWorktreePruneFacts(
        path=str(worktree),
        ticket=ticket,
        repo=worktree.name,
        branch=branch,
        ticket_state=(
            ticket_states.get(ticket, EnumTicketLifecycle.UNKNOWN)
            if ticket
            else EnumTicketLifecycle.UNKNOWN
        ),
        ledger_has_terminal=has_terminal,
        ledger_open_claim=open_claim,
        base_ref=base_ref,
        dirty_files=dirty_files,
        commits_ahead=commits_ahead,
        unmerged_ahead_commits=unmerged,
        tree_diff_vs_base_empty=tree_diff_empty,
        pr_state=pr_state,
        pr_head_oid=pr_head_oid,
        head_oid=head_oid,
        attributed_stash_count=count_attributed_stashes(stashes, branch),
        unreadable_probes=tuple(unreadable_probes),
        timed_out_probes=tuple(timed_out_probes),
        load_average=load_at_timeout,
    )


# ---------------------------------------------------------------------------
# action
# ---------------------------------------------------------------------------


class ModelRemovalAttempt(BaseModel):
    """The full evidence of one removal attempt [OMN-16951 defect 1].

    A prior revision recorded only a free-text ``detail`` string built from
    ``_git``'s stdout — which git never uses for a refusal reason, so every
    failure rendered identically as "no output". This model is the fix: the
    exact command, exit code, and full stderr are captured for every attempt,
    success or failure, so a refusal row can actually be adjudicated.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str = Field(..., min_length=1)
    ok: bool = Field(...)
    command: str = Field(..., min_length=1, description="The exact command run")
    exit_code: int = Field(..., description="-1 when the command was never run")
    stderr: str = Field(..., description="Full stderr text; '' on a clean success")
    detail: str = Field(..., description="Human-readable summary of the outcome")
    timed_out: bool = Field(
        default=False,
        description=(
            "The command exceeded its budget rather than being refused "
            "[OMN-18370 AC-4]. Never a safety finding — a statement about the "
            "host, reported with the load average that explains it."
        ),
    )
    load_average: float | None = Field(
        default=None, description="1-minute host load average read at the timeout"
    )
    branch_outcome: str = Field(
        default="",
        description="What happened to the local branch, in its own field, not folded into detail",
    )


def delete_branch_from_worktree_side(
    worktree: Path, branch: str, base_ref: str | None, pr_merged: bool
) -> tuple[str, str | None]:
    """Delete a worktree's local branch through a path the canonical-clone guard
    permits, returning ``(outcome_text, restorable_tip_oid_or_None)``
    [OMN-18370 AC-1/AC-2].

    Why not in the canonical clone. The clone's ``reference-transaction`` hook
    refuses ``refs/heads/*`` deletion outright — "branch deletion in a mirror
    destroys the only local record of what it pointed at". Measured 2026-09-14:
    23 of 26 removals left an orphan branch because the pruner ran ``git branch
    -D`` there. Both behaviours are correct; the pruner is what has to move.

    A **linked worktree** shares the clone's config, and therefore its
    ``hooksPath``, but the hook's own canonical-clone test resolves false there,
    so a ref write issued from the worktree side is permitted rather than
    bypassed. This is the option the ticket names, not a way around the guard.

    Sequence, and why each step is what it is:

    1. Record the branch tip, so a failed removal can put the branch back.
    2. ``git checkout --detach <base_ref>`` — a branch cannot be deleted while
       it is checked out, and detaching **at the base** rather than at the
       branch tip is what makes step 3 a real check: with HEAD at the tip,
       ``git branch -d`` would find the branch trivially "merged into HEAD" and
       delete anything.
    3. ``git branch -d`` — safe delete. git independently re-checks that the
       branch is merged into HEAD (now the base), a second opinion on the
       policy that approved the removal.
    4. ``git branch -D`` **only** when ``-d`` refused and a MERGED pull request
       exists for the branch. That is the squash-merge shape: the PR's commits
       are in the base as one new commit, so the branch's own commits are not
       ancestors of it and ``-d`` cannot see the merge. The force is recorded in
       the outcome text, never silent, and never reached without the merged PR.
    """
    tip_result = _git_run(worktree, "rev-parse", "--verify", f"refs/heads/{branch}")
    tip = tip_result.stdout if tip_result.ok else None
    if tip is None:
        return ("local branch kept: could not resolve its tip", None)

    if base_ref is None:
        return (
            "local branch kept: base ref unresolved, so a safe delete cannot be checked",
            None,
        )

    detach = _git_run(worktree, "checkout", "--detach", base_ref)
    if not detach.ok:
        return (
            f"local branch kept: could not detach HEAD onto {base_ref} "
            f"({detach.stderr or 'no stderr'})",
            None,
        )

    safe_delete = _git_run(worktree, "branch", "-d", branch)
    if safe_delete.ok:
        return (
            f"local branch deleted from the worktree side (-d, merged into {base_ref})",
            tip,
        )

    if not pr_merged:
        return (
            f"local branch kept: git branch -d refused "
            f"({safe_delete.stderr or 'no stderr'}) and no merged pull request "
            "proves the content is preserved",
            tip,
        )

    forced = _git_run(worktree, "branch", "-D", branch)
    if forced.ok:
        return (
            "local branch force-deleted from the worktree side: -d refused "
            f"(squash-merge shape, its commits are not ancestors of {base_ref}) "
            "and a MERGED pull request carries this exact HEAD",
            tip,
        )
    return (
        f"local branch kept: delete failed ({forced.stderr or 'no stderr'})",
        tip,
    )


def restore_branch(worktree: Path, branch: str, tip: str) -> str:
    """Put a deleted branch back after a removal that did not happen.

    The branch is deleted BEFORE ``git worktree remove`` (it is the only moment
    the guard-permitted worktree-side path exists), so a refused or timed-out
    removal must not leave a live worktree sitting detached with its branch
    gone.
    """
    recreated = _git_run(worktree, "branch", branch, tip)
    if not recreated.ok:
        return f"; branch {branch} NOT restored ({recreated.stderr or 'no stderr'})"
    reattached = _git_run(worktree, "checkout", branch)
    if not reattached.ok:
        return f"; branch {branch} restored at {tip[:12]} but HEAD left detached"
    return f"; branch {branch} restored at {tip[:12]} and re-checked-out"


def prune_worktree(decision: ModelWorktreePruneDecision) -> ModelRemovalAttempt:
    """Remove one proven-safe worktree and its local branch.

    Uses plain ``git worktree remove`` — never ``--force`` — so git re-checks
    cleanliness independently of the policy that just approved the removal. A
    timeout is retried once when the host load falls, and is reported as a
    timeout rather than as a refusal [OMN-18370 AC-4].
    """
    worktree = Path(decision.path)
    canonical = canonical_root_of(worktree)
    if canonical is None:
        return ModelRemovalAttempt(
            path=decision.path,
            ok=False,
            command=f"git -C <unresolved> worktree remove {worktree}",
            exit_code=-1,
            stderr="",
            detail="canonical clone not resolvable",
        )

    branch_outcome = "no local branch to delete (detached HEAD)"
    restorable_tip: str | None = None
    if decision.branch and not decision.branch_content_preserved:
        branch_outcome = (
            "local branch kept: its content is not proven preserved in the base "
            "or in a merged pull request"
        )
    elif decision.branch:
        branch_outcome, restorable_tip = delete_branch_from_worktree_side(
            worktree,
            decision.branch,
            resolve_base_ref(canonical),
            decision.pr_state is EnumBranchPrState.MERGED,
        )

    argv = ["git", "-C", str(canonical), "worktree", "remove", str(worktree)]
    result = _git_run_with_load_retry(canonical, "worktree", "remove", str(worktree))

    if result.timed_out:
        restored = (
            restore_branch(worktree, decision.branch, restorable_tip)
            if decision.branch and restorable_tip
            else ""
        )
        load_text = (
            f"{result.load_average:.2f}"
            if result.load_average is not None
            else "unavailable"
        )
        return ModelRemovalAttempt(
            path=decision.path,
            ok=False,
            command=" ".join(argv),
            exit_code=-1,
            stderr=result.stderr,
            timed_out=True,
            load_average=result.load_average,
            branch_outcome=branch_outcome,
            detail=(
                f"git worktree remove timed out at {GIT_TIMEOUT_SECONDS}s, retried "
                f"once after waiting for the load to fall and timed out again; "
                f"1-minute load {load_text}. Not a safety finding{restored}"
            ),
        )

    if result.exit_code != 0:
        stderr_text = (
            result.stderr or result.stdout or "(git produced no stdout or stderr)"
        )
        restored = (
            restore_branch(worktree, decision.branch, restorable_tip)
            if decision.branch and restorable_tip
            else ""
        )
        return ModelRemovalAttempt(
            path=decision.path,
            ok=False,
            command=" ".join(argv),
            exit_code=result.exit_code,
            stderr=stderr_text,
            branch_outcome=branch_outcome,
            detail=f"git worktree remove refused (exit {result.exit_code}): {stderr_text}{restored}",
        )

    return ModelRemovalAttempt(
        path=decision.path,
        ok=True,
        command=" ".join(argv),
        exit_code=0,
        stderr="",
        branch_outcome=branch_outcome,
        detail=f"worktree removed; {branch_outcome}",
    )


def remediate_debris(
    decision: ModelPartialMutationDebrisDecision, owning_clone: Path
) -> ModelRemovalAttempt:
    """Execute the ONE auto-removable remediation for a partial-mutation
    debris row [OMN-16951 defect 2]: ``git worktree prune`` in the owning
    clone (administrative-record-only — this never touches the worktree
    directory itself), then remove the now-orphaned leftover directory.

    Caller contract: only invoke this when ``decision.remediation`` is
    :data:`EnumDebrisRemediation.AUTO_REMOVABLE` — that is where the predicate
    already proved every remaining file's content is reachable as a blob in
    ``owning_clone``. Never ``--force`` on the git side; the directory removal
    that follows is not a blind ``rm -rf`` — it only runs after that proof.
    """
    prune_argv = ["git", "-C", str(owning_clone), "worktree", "prune"]
    code, out, err = _git_capture(owning_clone, "worktree", "prune")
    if code != 0:
        stderr_text = err or out or "(git produced no stdout or stderr)"
        return ModelRemovalAttempt(
            path=decision.path,
            ok=False,
            command=" ".join(prune_argv),
            exit_code=code,
            stderr=stderr_text,
            detail=f"git worktree prune refused (exit {code}) in {owning_clone}",
        )

    target = Path(decision.path)
    rm_command = f"{' '.join(prune_argv)} ; shutil.rmtree({target})"

    # Re-prove reachability immediately before deleting, not just at
    # classification time [CodeRabbit, OMN-16951 PR review]: the scan that
    # produced this decision can run minutes ahead of the --execute pass over
    # a large root, and a file written into the directory during that gap
    # would otherwise be deleted without ever being checked.
    _recheck_count, recheck_unreachable = leftover_content_reachable(
        target, owning_clone
    )
    if recheck_unreachable:
        return ModelRemovalAttempt(
            path=decision.path,
            ok=False,
            command=rm_command,
            exit_code=-1,
            stderr="",
            detail=(
                f"refused: {len(recheck_unreachable)} file(s) are no longer "
                "reachable as blobs in the owning clone at removal time — "
                "content changed after classification"
            ),
        )

    try:
        shutil.rmtree(target)
    except OSError as exc:
        return ModelRemovalAttempt(
            path=decision.path,
            ok=False,
            command=rm_command,
            exit_code=0,
            stderr=str(exc),
            detail=(
                "git worktree prune succeeded but the leftover directory removal failed"
            ),
        )

    return ModelRemovalAttempt(
        path=decision.path,
        ok=True,
        command=rm_command,
        exit_code=0,
        stderr="",
        detail=(
            "owning-clone administrative record pruned; leftover directory "
            "removed (content proven reachable as blobs already in the repo)"
        ),
    )


def cleanup_empty_ticket_dirs(root: Path) -> list[str]:
    """Remove now-empty ``omni_worktrees/<ticket>/`` directories."""
    removed: list[str] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        if any(child.rglob("*")):
            continue
        child.rmdir()
        removed.append(str(child))
    return removed


# ---------------------------------------------------------------------------
# reporting
# ---------------------------------------------------------------------------


def render_report(
    decisions: Sequence[ModelWorktreePruneDecision],
    *,
    root: Path,
    executed: bool,
    generated_at: str,
    removals: Sequence[ModelRemovalAttempt],
    tracker_resolved: int,
    debris_decisions: Sequence[ModelPartialMutationDebrisDecision] = (),
) -> str:
    """Render the markdown report. Every worktree appears exactly once."""
    prunable = [d for d in decisions if d.disposition is EnumPruneDisposition.PRUNE]
    triage = [d for d in decisions if d.disposition is EnumPruneDisposition.TRIAGE]
    timed_out = [
        d for d in decisions if d.disposition is EnumPruneDisposition.TIMED_OUT
    ]

    # Every reason on every row, from both halves of the predicate — the
    # previous revision counted only the reasons of the half that fired first,
    # which undercounted detached_head 40-against-130 and dirty_tree
    # 26-against-158 on the 2026-09-14 run [OMN-18370 AC-3].
    by_reason: dict[EnumPruneBlockReason, int] = defaultdict(int)
    for decision in (*triage, *timed_out):
        for reason in decision.block_reasons:
            by_reason[reason] += 1
    # Only the TRIAGE subset belongs in the block-reason table — an
    # AUTO_REMOVABLE debris row is (on --execute) actually removed, so
    # counting it as triage would misreport what the morning sweep left
    # behind [CodeRabbit, OMN-16951 PR review].
    triage_debris = sum(
        1 for d in debris_decisions if d.remediation is EnumDebrisRemediation.TRIAGE
    )
    if triage_debris:
        by_reason[EnumPruneBlockReason.PARTIAL_MUTATION_DEBRIS] += triage_debris

    mode = "EXECUTE" if executed else "DRY RUN — nothing was removed"
    lines: list[str] = [
        "# Worktree auto-prune report",
        "",
        f"- **Generated:** {generated_at}",
        f"- **Root:** `{root}`",
        f"- **Mode:** {mode}",
        f"- **Scanned:** {len(decisions)}",
        f"- **Prune-eligible and safe:** {len(prunable)}",
        f"- **Triage (never deleted):** {len(triage)}",
        f"- **Timed out (host load, not a safety finding):** {len(timed_out)}",
        f"- **Partial-mutation debris candidates:** {len(debris_decisions)}",
        f"- **Ticket states resolved from tracker (reported, not decisive):** "
        f"{tracker_resolved}",
        "",
        "Pruning is keyed to **what the worktree holds**, not to its ticket's state",
        "(operator ruling 2026-09-14). Removable when clean and zero commits ahead",
        "with no open ledger `CLAIM`, or clean with a MERGED pull request and no open",
        "`CLAIM`. See `omniclaude/src/omniclaude/hooks/lib/worktree_prune_policy.py`.",
        "",
        "## Triage block reasons",
        "",
        "| Reason | Count |",
        "| --- | ---: |",
    ]
    for reason, count in sorted(by_reason.items(), key=lambda kv: -kv[1]):
        lines.append(f"| `{reason.value}` | {count} |")
    if not by_reason:
        lines.append("| _(none)_ | 0 |")

    lines += [
        "",
        f"## Prune candidates ({len(prunable)})",
        "",
        "| Path | Ticket | Branch | PR | Eligibility | Safety |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for decision in prunable:
        lines.append(
            f"| `{decision.path}` | {decision.ticket} | `{decision.branch}` "
            f"| {decision.pr_state.value} | {decision.eligibility_evidence} "
            f"| {decision.safety_evidence} |"
        )
    if not prunable:
        lines.append("| _(none)_ | | | | | |")

    lines += [
        "",
        f"## Timed out ({len(timed_out)})",
        "",
        "A git probe exceeded its budget, so the facts were never collected. This",
        "says nothing about the worktree — it is a host-load reading, and it is NOT",
        "counted as a safety finding (OMN-18370 AC-4). Each row was retried once",
        f"after waiting for the 1-minute load to fall to {LOAD_RETRY_THRESHOLD:.0f}.",
        "",
        "| Path | Ticket | Branch | Probes | 1-min load |",
        "| --- | --- | --- | --- | ---: |",
    ]
    for decision in timed_out:
        probes = ", ".join(f"`{p}`" for p in decision.timed_out_probes) or "—"
        load = (
            f"{decision.load_average:.2f}"
            if decision.load_average is not None
            else "unavailable"
        )
        branch = f"`{decision.branch}`" if decision.branch else "_(detached)_"
        lines.append(
            f"| `{decision.path}` | {decision.ticket or '—'} | {branch} "
            f"| {probes} | {load} |"
        )
    if not timed_out:
        lines.append("| _(none)_ | | | | |")

    lines += [
        "",
        f"## Triage rows ({len(triage)})",
        "",
        "Never deleted. Each row carries what a human or the morning friction",
        "sweep needs to adjudicate it.",
        "",
        "| Path | Ticket | Branch | PR | Ahead | Dirty files | Block reasons | Ledger claim |",
        "| --- | --- | --- | --- | ---: | ---: | --- | --- |",
    ]
    for decision in triage:
        reasons = ", ".join(f"`{r.value}`" for r in decision.block_reasons)
        claim = (decision.ledger_open_claim or "").replace("|", "\\|")
        branch = f"`{decision.branch}`" if decision.branch else "_(detached)_"
        lines.append(
            f"| `{decision.path}` | {decision.ticket or '—'} | {branch} "
            f"| {decision.pr_state.value} | {decision.commits_ahead} "
            f"| {decision.dirty_file_count} | {reasons} | {claim} |"
        )
    if not triage:
        lines.append("| _(none)_ | | | | | | | |")

    auto_removable_debris = sum(
        1
        for d in debris_decisions
        if d.remediation is EnumDebrisRemediation.AUTO_REMOVABLE
    )
    lines += [
        "",
        f"## Partial-mutation debris ({len(debris_decisions)})",
        "",
        "No `.git` link remains under these directories, so `git worktree remove`",
        "can never succeed — see `partial_mutation_debris` in",
        "`docs/workflows/morning-worktree-prune/README.md`. Never deleted here;",
        f"only the auto-removable subset ({auto_removable_debris}) is a candidate for",
        "the conservative `git worktree prune` + proven-reachable-content removal",
        "path, and only on an `--execute` run.",
        "",
        "| Path | Ticket | Repo | Remediation | Evidence |",
        "| --- | --- | --- | --- | --- |",
    ]
    for debris in debris_decisions:
        lines.append(
            f"| `{debris.path}` | {debris.ticket or '—'} | {debris.repo} "
            f"| {debris.remediation.value} | {debris.evidence} |"
        )
    if not debris_decisions:
        lines.append("| _(none)_ | | | | |")

    if removals:
        succeeded = sum(1 for r in removals if r.ok)
        lines += [
            "",
            f"## Removals ({succeeded} succeeded)",
            "",
            "| Path | Result | Command | Exit code | Stderr | Local branch | Detail |",
            "| --- | --- | --- | ---: | --- | --- | --- |",
        ]
        for attempt in removals:
            stderr_cell = (
                (attempt.stderr or "—").replace("|", "\\|").replace("\n", "<br>")
            )
            command_cell = attempt.command.replace("|", "\\|")
            if attempt.ok:
                verdict = "OK"
            elif attempt.timed_out:
                verdict = "TIMED OUT"
            else:
                verdict = "FAILED"
            lines.append(
                f"| `{attempt.path}` | {verdict} "
                f"| `{command_cell}` | {attempt.exit_code} | {stderr_cell} "
                f"| {attempt.branch_outcome or '—'} | {attempt.detail} |"
            )

    lines.append("")
    return "\n".join(lines)


def decision_to_json(decision: ModelWorktreePruneDecision) -> dict[str, Any]:
    payload = decision.model_dump(mode="json")
    payload["block_reasons"] = [r.value for r in decision.block_reasons]
    return payload


def debris_decision_to_json(
    decision: ModelPartialMutationDebrisDecision,
) -> dict[str, Any]:
    payload = decision.model_dump(mode="json")
    payload["block_reasons"] = [r.value for r in decision.block_reasons]
    payload["remediation"] = decision.remediation.value
    return payload


# ---------------------------------------------------------------------------
# entrypoint
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Content-keyed worktree pruner (operator ruling 2026-09-14). Dry-run "
            "by default; --execute to remove. A worktree is removable when it is "
            "clean and zero commits ahead with no open ledger CLAIM, or clean "
            "with a MERGED pull request and no open CLAIM. The ticket's own "
            "state is reported but decides nothing. Everything else is triaged."
        )
    )
    parser.add_argument(
        "--worktrees-root",
        default=os.environ.get("ONEX_WORKTREES_ROOT")
        or (
            f"{os.environ['OMNI_HOME'].rstrip('/')}/omni_worktrees"
            if os.environ.get("OMNI_HOME")
            else None
        ),
        help="Worktrees root (default: $ONEX_WORKTREES_ROOT, else $OMNI_HOME/omni_worktrees)",
    )
    parser.add_argument(
        "--ledger",
        default=(
            f"{os.environ['OMNI_HOME'].rstrip('/')}/docs/tracking/ROLLING_WORK_LEDGER.md"
            if os.environ.get("OMNI_HOME")
            else None
        ),
        help="Rolling work ledger path (default: $OMNI_HOME/docs/tracking/ROLLING_WORK_LEDGER.md)",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually remove prune-eligible worktrees (default: dry run)",
    )
    parser.add_argument(
        "--no-tracker",
        action="store_true",
        help=(
            "Skip Linear resolution. Ticket state is reported context only, so "
            "this costs the report a column and changes no verdict."
        ),
    )
    parser.add_argument(
        "--no-pr-state",
        action="store_true",
        help=(
            "Skip `gh pr list` resolution. Limb (b) of the ruling (clean plus a "
            "MERGED pull request) becomes unavailable and every row falls back "
            "to limb (a): fewer removals, never more."
        ),
    )
    parser.add_argument(
        "--no-fetch",
        action="store_true",
        help="Skip refreshing origin/dev in each canonical clone before classifying",
    )
    parser.add_argument("--report-md", help="Write the markdown report to this path")
    parser.add_argument("--report-json", help="Write the JSON report to this path")
    parser.add_argument(
        "--limit", type=int, default=0, help="Scan at most N worktrees (0 = all)"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if not args.worktrees_root:
        print(
            "ERROR: worktrees root unresolved. Set ONEX_WORKTREES_ROOT or OMNI_HOME, "
            "or pass --worktrees-root.",
            file=sys.stderr,
        )
        return 2
    root = Path(args.worktrees_root).expanduser().resolve()
    if not root.is_dir():
        print(f"ERROR: worktrees root is not a directory: {root}", file=sys.stderr)
        return 2

    ledger_path = Path(args.ledger).expanduser() if args.ledger else None
    if ledger_path is None or not ledger_path.is_file():
        # Fail closed: with no ledger there is no claim-awareness, and a prune
        # without claim-awareness is exactly the OMN-15551 hazard.
        print(
            f"ERROR: ledger not readable ({ledger_path}); refusing to classify "
            "without claim-awareness (OMN-15551).",
            file=sys.stderr,
        )
        return 2

    worktrees = discover_worktrees(root)
    if args.limit > 0:
        worktrees = worktrees[: args.limit]
    print(f"Scanning {len(worktrees)} worktree(s) under {root}", flush=True)

    ledger = parse_ledger_claims(ledger_path)
    print(f"Ledger: {len(ledger)} ticket(s) carry CLAIM/TERMINAL rows", flush=True)

    base_ref_cache: dict[Path, str | None] = {}
    stash_cache: dict[Path, list[str]] = {}
    pr_state_cache: (
        dict[Path, dict[str, tuple[EnumBranchPrState, str | None]]] | None
    ) = None if args.no_pr_state else {}

    if not args.no_fetch:
        canonicals = {
            c for c in (canonical_root_of(w) for w in worktrees) if c is not None
        }
        print(
            f"Refreshing base branches in {len(canonicals)} canonical clone(s)",
            flush=True,
        )
        for canonical in sorted(canonicals):
            fetch_base(canonical)

    tickets = {
        t
        for t in (extract_ticket_id(w.relative_to(root).parts[0]) for w in worktrees)
        if t
    }
    ticket_states: dict[str, EnumTicketLifecycle] = {}
    if not args.no_tracker:
        api_key = load_linear_api_key()
        if api_key:
            print(f"Resolving {len(tickets)} ticket state(s) from Linear", flush=True)
            ticket_states = resolve_ticket_states(tickets, api_key)
        else:
            print(
                "WARNING: no LINEAR_API_KEY; every ticket state is UNKNOWN and "
                "eligibility falls back to ledger TERMINAL rows",
                file=sys.stderr,
            )

    # A full root is ~1000 worktrees and several git calls each, so the scan runs
    # for minutes. Report progress as it goes: a silent multi-minute run is
    # indistinguishable from a hung one.
    decisions: list[ModelWorktreePruneDecision] = []
    for index, worktree in enumerate(worktrees, start=1):
        decisions.append(
            classify_worktree_prune(
                collect_facts(
                    worktree,
                    root,
                    ticket_states,
                    ledger,
                    base_ref_cache,
                    stash_cache,
                    pr_state_cache,
                )
            )
        )
        if index % 100 == 0 or index == len(worktrees):
            print(f"  classified {index}/{len(worktrees)}", flush=True)

    prunable = [d for d in decisions if d.disposition is EnumPruneDisposition.PRUNE]
    triage = [d for d in decisions if d.disposition is EnumPruneDisposition.TRIAGE]
    timed_out = [
        d for d in decisions if d.disposition is EnumPruneDisposition.TIMED_OUT
    ]

    # Partial-mutation debris [OMN-16951 defect 2]: directories whose `.git`
    # link is already gone are invisible to `discover_worktrees` (it keys off
    # a `.git` glob), so they need their own discovery pass and their own
    # (much narrower) predicate — see worktree_prune_policy.classify_
    # partial_mutation_debris. Cheap even at registry scale: one `git
    # worktree list` per canonical clone, not per worktree.
    canonicals_for_debris = discover_canonical_clones(root.parent)
    owner_lookup: dict[str, tuple[Path, str]] = {}
    for canonical in canonicals_for_debris:
        for path_str, state in collect_worktree_list_entries(canonical).items():
            owner_lookup[path_str] = (canonical, state)

    debris_candidates = discover_debris_directories(root, set(worktrees))
    print(
        f"Found {len(debris_candidates)} partial-mutation-debris candidate(s) "
        f"across {len(canonicals_for_debris)} canonical clone(s)",
        flush=True,
    )
    debris_decisions: list[ModelPartialMutationDebrisDecision] = []
    debris_owner_by_path: dict[str, Path] = {}
    for candidate in debris_candidates:
        facts = collect_debris_facts(candidate, root, owner_lookup)
        debris_decision = classify_partial_mutation_debris(facts)
        debris_decisions.append(debris_decision)
        if facts.owning_clone:
            debris_owner_by_path[debris_decision.path] = Path(facts.owning_clone)

    removals: list[ModelRemovalAttempt] = []
    revalidation_refusals: list[ModelWorktreePruneDecision] = []
    if args.execute:
        for decision in prunable:
            # RE-VERIFY LIVE, immediately before the removal. The classification
            # pass over a registry-scale root runs for tens of minutes while peer
            # lanes keep working, so a row can gain a CLAIM, a commit or an
            # uncommitted edit between being judged and being removed. Re-running
            # the whole predicate is cheap next to deleting live work, and it is
            # the only thing that closes that window: `git worktree remove`
            # re-checks cleanliness but knows nothing about the ledger.
            fresh = classify_worktree_prune(
                collect_facts(
                    Path(decision.path),
                    root,
                    ticket_states,
                    parse_ledger_claims(ledger_path),
                    base_ref_cache,
                    stash_cache,
                    pr_state_cache,
                )
            )
            if fresh.disposition is not EnumPruneDisposition.PRUNE:
                revalidation_refusals.append(fresh)
                reasons = ", ".join(r.value for r in fresh.block_reasons) or "unknown"
                print(
                    f"  SKIPPED {decision.path} — re-verification at removal time "
                    f"no longer approves it ({fresh.disposition.value}: {reasons})"
                )
                continue
            attempt = prune_worktree(fresh)
            removals.append(attempt)
            if attempt.ok:
                status = "REMOVED"
            elif attempt.timed_out:
                status = "TIMEOUT"
            else:
                status = "FAILED "
            print(f"  {status} {attempt.path} — {attempt.detail}")
        for debris_decision in debris_decisions:
            if debris_decision.remediation is not EnumDebrisRemediation.AUTO_REMOVABLE:
                continue
            owner = debris_owner_by_path.get(debris_decision.path)
            if owner is None:
                continue  # classify_partial_mutation_debris never reaches
                # AUTO_REMOVABLE without an owning clone; this is a fail-safe.
            attempt = remediate_debris(debris_decision, owner)
            removals.append(attempt)
            status = "REMOVED" if attempt.ok else "FAILED "
            print(f"  {status} {attempt.path} — {attempt.detail}")
        for empty_dir in cleanup_empty_ticket_dirs(root):
            print(f"  RMDIR   {empty_dir}")

    generated_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    report = render_report(
        decisions,
        root=root,
        executed=args.execute,
        generated_at=generated_at,
        removals=removals,
        tracker_resolved=len(ticket_states),
        debris_decisions=debris_decisions,
    )

    if args.report_md:
        md_path = Path(args.report_md).expanduser()
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(report, encoding="utf-8")
        print(f"Wrote markdown report: {md_path}")
    if args.report_json:
        json_path = Path(args.report_json).expanduser()
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(
            json.dumps(
                {
                    "generated_at": generated_at,
                    "root": str(root),
                    "executed": args.execute,
                    "scanned": len(decisions),
                    "prune_count": len(prunable),
                    "triage_count": len(triage),
                    "timed_out_count": len(timed_out),
                    "revalidation_refusal_count": len(revalidation_refusals),
                    "revalidation_refusals": [
                        decision_to_json(d) for d in revalidation_refusals
                    ],
                    "decisions": [decision_to_json(d) for d in decisions],
                    "debris_count": len(debris_decisions),
                    "debris_decisions": [
                        debris_decision_to_json(d) for d in debris_decisions
                    ],
                    "removals": [r.model_dump(mode="json") for r in removals],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"Wrote JSON report: {json_path}")

    print(
        f"\nscanned={len(decisions)} safe={len(prunable)} triage={len(triage)} "
        f"timed_out={len(timed_out)} debris={len(debris_decisions)} "
        f"revalidation_refused={len(revalidation_refusals)} "
        f"removed={sum(1 for r in removals if r.ok)}"
    )
    if not args.execute and prunable:
        print("Dry run — re-run with --execute to remove the prune candidates.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
