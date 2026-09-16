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

    # additionally classify the RESCUE-ONLY class into its own report section.
    # Report-only: this script never removes a rescue-only worktree, whatever
    # --execute says. The numbers are the CALLER's, from the declared
    # morning-worktree-prune policy — this script carries no default for
    # either, deliberately [OMN-18442 AC6].
    uv run python scripts/worktree_auto_prune.py \
        --rescue-only \
        --rescue-only-age-days <the declared bar> \
        --rescue-only-claim-fence-days <the declared fence> \
        --rescue-only-hand-held <the declared hand_held_worktrees.yaml>

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
from typing import Any, NamedTuple

import yaml
from pydantic import BaseModel, ConfigDict, Field

from omniclaude.hooks.lib.worktree_health import extract_ticket_id
from omniclaude.hooks.lib.worktree_prune_policy import (
    EnumBranchPrState,
    EnumDebrisRemediation,
    EnumPruneBlockReason,
    EnumPruneDisposition,
    EnumRescueOnlyDisposition,
    EnumTicketLifecycle,
    ModelPartialMutationDebrisDecision,
    ModelPartialMutationDebrisFacts,
    ModelRescueOnlyDecision,
    ModelRescueOnlyFacts,
    ModelWorktreePruneDecision,
    ModelWorktreePruneFacts,
    classify_partial_mutation_debris,
    classify_rescue_only,
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


_LANE_RE = re.compile(r"\blane=([^\s|]+)")
# Both spellings are live in the real ledger: `closes-CLAIM=<path>:<line>` and
# the equally-real `closes=CLAIM <path>:<line>` (no dash before CLAIM). Either
# way, only the trailing `:<line>` numeral is load-bearing here.
_CLOSES_CLAIM_RE = re.compile(r"closes[-=]CLAIM[=\s]+\S*?:(\d+)")


class LedgerClaimRow(NamedTuple):
    """One still-open ``CLAIM`` row: not yet closed by a matching ``TERMINAL``.

    ``lineno`` is 1-based, matching the numbering ``closes-CLAIM=<path>:<line>``
    citations use (and what ``sed -n '<n>p'`` / ``grep -n`` report), so a
    citation can be compared directly against it.
    """

    lineno: int
    lane: str | None
    tickets: frozenset[str]
    text: str


def parse_ledger_claims(
    ledger_path: Path,
) -> dict[str, tuple[bool, tuple[LedgerClaimRow, ...]]]:
    """Map each ticket to ``(has_terminal_ever, open_claims)``.

    A ``CLAIM`` is keyed by ``(lane, line)`` [OMN-18380 AC1], not by ticket. It
    is closed ONLY by a ``TERMINAL`` whose ``closes-CLAIM`` field cites that
    exact line, or, when the ``TERMINAL`` carries no ``closes-CLAIM`` field, by
    a ``TERMINAL`` whose ``lane=`` matches (and whose ticket set, if either
    row has one, intersects the claim's). A ``TERMINAL`` naming the ticket
    alone — no ``closes-CLAIM``, no matching lane — closes NOTHING.

    The previous revision compared the newest CLAIM line against the newest
    TERMINAL line **for the ticket**, so any lane's TERMINAL on a shared
    ticket read as closing every other lane's open CLAIM on it. On
    2026-09-14 a peer lane's TERMINAL on OMN-16901 (no ``closes-CLAIM``, a
    different ``lane=``) cleared lane ``worktree-cleanup-phase2``'s own
    still-open CLAIM this way, and the pruner removed its worktree out from
    under it (docs/tracking/ROLLING_WORK_LEDGER.md:7963).

    ``has_terminal_ever`` is reported context only (evidence text), never a
    condition of eligibility — unchanged from the previous contract of
    :func:`omniclaude.hooks.lib.worktree_prune_policy.is_prune_eligible`.

    Section bodies (``- **Status:** IN PROGRESS.``) carry no ticket id of
    their own, so they inherit the ticket from the nearest preceding ``#``
    heading; such legacy rows also carry no ``lane=``, so a bare
    ``**Status:** TERMINAL`` closes nothing under the lane-keyed rule above —
    the fail-safe direction (OMN-15551): an unprovable close leaves the claim
    open rather than assumed closed.
    """
    if not ledger_path.is_file():
        return {}

    open_claims: dict[int, LedgerClaimRow] = {}
    has_terminal_ever: dict[str, bool] = {}
    section_ticket: str | None = None

    for index, raw in enumerate(
        ledger_path.read_text(encoding="utf-8", errors="replace").splitlines()
    ):
        lineno = index + 1  # 1-based, matching closes-CLAIM=<path>:<line> citations
        line = raw.strip()
        if line.startswith("#"):
            heading_ticket = _TICKET_RE.search(line.upper())
            section_ticket = heading_ticket.group(0) if heading_ticket else None

        is_claim = any(m in line for m in _CLAIM_MARKERS)
        is_terminal = any(m in line for m in _TERMINAL_MARKERS)
        if not (is_claim or is_terminal):
            continue

        tickets = frozenset(_TICKET_RE.findall(line.upper()))
        if not tickets and section_ticket:
            tickets = frozenset({section_ticket})
        if not tickets:
            continue

        lane_match = _LANE_RE.search(line)
        lane = lane_match.group(1).lower() if lane_match else None

        for ticket in tickets:
            if is_terminal:
                has_terminal_ever[ticket] = True

        if is_terminal:
            closes_match = _CLOSES_CLAIM_RE.search(line)
            if closes_match:
                cited_line = int(closes_match.group(1))
                open_claims.pop(cited_line, None)
            elif lane is not None:
                # No explicit citation: close the most recent OPEN claim from
                # the SAME lane whose tickets intersect this TERMINAL's (or
                # either side carries no tickets at all — a bare lane close).
                candidates = [
                    row
                    for row in open_claims.values()
                    if row.lane == lane
                    and (not row.tickets or not tickets or row.tickets & tickets)
                ]
                if candidates:
                    newest = max(candidates, key=lambda row: row.lineno)
                    open_claims.pop(newest.lineno, None)
            # Neither field present: this TERMINAL closes nothing (rule 8).
            continue

        # is_claim (CLAIM+TERMINAL combined rows never reach here: they match
        # only _TERMINAL_MARKERS, never _CLAIM_MARKERS, and resolve above).
        open_claims[lineno] = LedgerClaimRow(
            lineno=lineno, lane=lane, tickets=tickets, text=line
        )

    result: dict[str, tuple[bool, tuple[LedgerClaimRow, ...]]] = {}
    for ticket in set(has_terminal_ever) | {
        t for row in open_claims.values() for t in row.tickets
    }:
        ticket_claims = tuple(
            sorted(
                (row for row in open_claims.values() if ticket in row.tickets),
                key=lambda row: row.lineno,
            )
        )
        result[ticket] = (has_terminal_ever.get(ticket, False), ticket_claims)
    return result


def select_blocking_claim(
    open_claims: tuple[LedgerClaimRow, ...],
    worktree_path: str,
    branch: str | None,
) -> str | None:
    """Pick the open claim, if any, that blocks this worktree from pruning.

    A claim naming this worktree's path or branch always blocks, regardless
    of other open or closed claims on the same ticket [OMN-18380 AC2]. Absent
    a named match, any remaining open claim on the ticket still blocks — an
    un-named claim is not proof the worktree is uninvolved, and the safe
    default (OMN-15551) is to hold rather than guess.
    """
    if not open_claims:
        return None
    for claim in open_claims:
        if worktree_path in claim.text or (branch and branch in claim.text):
            return claim.text[:240]
    return open_claims[0].text[:240]


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
    ledger: dict[str, tuple[bool, tuple[LedgerClaimRow, ...]]],
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

    has_terminal, ticket_open_claims = ledger.get(ticket or "", (False, ()))
    open_claim = select_blocking_claim(ticket_open_claims, str(worktree), branch)

    # Limb (c): the branch is on origin at this exact HEAD. The expensive live
    # confirmation runs ONLY when the cheap local remote-tracking ref already
    # agrees, because a local ref can name a branch origin no longer has and the
    # whole point of the limb is that origin is really holding the commits.
    origin_head_oid: str | None = None
    if branch is not None and head_oid is not None:
        tracking = _git_run(
            worktree,
            "rev-parse",
            "--verify",
            "--quiet",
            f"refs/remotes/origin/{branch}",
        )
        if tracking.ok and tracking.stdout == head_oid:
            remote = _git_run(worktree, "ls-remote", "--heads", "origin", branch)
            if remote.ok and remote.stdout:
                first = remote.stdout.split("\n", 1)[0].split("\t", 1)[0].strip()
                if first == head_oid:
                    origin_head_oid = first
            elif remote.timed_out:
                timed_out_probes.append(f"git ls-remote --heads origin {branch}")
                if load_at_timeout is None:
                    load_at_timeout = remote.load_average

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
        origin_head_oid=origin_head_oid,
        head_oid=head_oid,
        attributed_stash_count=count_attributed_stashes(stashes, branch),
        unreadable_probes=tuple(unreadable_probes),
        timed_out_probes=tuple(timed_out_probes),
        load_average=load_at_timeout,
    )


# ---------------------------------------------------------------------------
# rescue-only fact collection [OMN-18442 AC6]
# ---------------------------------------------------------------------------
#
# The class the content-keyed predicate structurally cannot reach: a branch that
# never opened a pull request and has none open, holding work a rescue pass
# swept up and nobody came back for. See the rescue-only section of
# ``worktree_prune_policy`` for what it is and why it is separate.
#
# NOTHING BELOW DECLARES A POLICY VALUE. The age bar and the claim fence arrive
# on the command line, from the workflow config that declares them once. The
# hand-held exclusion list arrives as a path to the declared file. This half
# only OBSERVES; ``classify_rescue_only`` decides.
#
# The classifier REPORTS this class and never acts on it, on ``--execute`` as
# much as on a dry run. Removal is the morning-prune Prune phase's, under a
# re-read of the operator consent row — a pass that destroys unpreserved work
# must not ride in on a flag that means something else.


class ModelHandHeldEntry(BaseModel):
    """One row of the declared hand-held exclusion file.

    Exact on ``branch``, substring on ``path_contains``, and never a regular
    expression — a regex in an exclusion list is how an exclusion quietly grows
    to cover more than it was written for.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    branch: str | None = None
    path_contains: str | None = None
    reason: str
    added: str

    def matches(self, *, branch: str | None, path: str) -> bool:
        if self.branch is not None:
            return branch is not None and branch == self.branch
        return self.path_contains is not None and self.path_contains in path


def load_hand_held_entries(path: Path) -> tuple[ModelHandHeldEntry, ...] | None:
    """Read the declared exclusion list, or return ``None`` if it cannot be read.

    ``None`` is NOT an empty list and the caller must not treat it as one: every
    row is held on ``hand_held_list_unavailable`` instead. A missing file, an
    unparseable one, a row naming neither key or both, or a row missing its
    reason or date all return ``None`` — an exclusion list that silently covers
    nothing reads exactly like one that covers everything it should.
    """
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        print(f"  hand-held list unreadable ({path}): {exc}", file=sys.stderr)
        return None
    if not isinstance(raw, dict) or "hand_held" not in raw:
        print(
            f"  hand-held list has no top-level 'hand_held' key: {path}",
            file=sys.stderr,
        )
        return None
    rows = raw["hand_held"]
    if rows is None:
        return ()
    if not isinstance(rows, list):
        print(f"  hand-held list 'hand_held' is not a list: {path}", file=sys.stderr)
        return None
    entries: list[ModelHandHeldEntry] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            print(
                f"  hand-held entry {index} is not a mapping: {path}", file=sys.stderr
            )
            return None
        branch = row.get("branch")
        path_contains = row.get("path_contains")
        if (branch is None) == (path_contains is None):
            print(
                f"  hand-held entry {index} must name exactly one of 'branch' or "
                f"'path_contains', not neither and not both: {path}",
                file=sys.stderr,
            )
            return None
        if not row.get("reason") or not row.get("added"):
            print(
                f"  hand-held entry {index} carries no reason or no added date: {path}",
                file=sys.stderr,
            )
            return None
        entries.append(
            ModelHandHeldEntry(
                branch=None if branch is None else str(branch),
                path_contains=None if path_contains is None else str(path_contains),
                reason=str(row["reason"]).strip(),
                added=str(row["added"]),
            )
        )
    return tuple(entries)


def commit_age_days(worktree: Path, now: float) -> float | None:
    """Age of the branch tip's COMMITTER date, in days, or None if unreadable."""
    result = _git_run(worktree, "log", "-1", "--format=%ct", "HEAD")
    if not result.ok or not result.stdout.strip().isdigit():
        return None
    return max(0.0, (now - float(result.stdout.strip())) / 86400.0)


def newest_git_visible_mtime_age_days(worktree: Path, now: float) -> float | None:
    """Age of the newest GIT-VISIBLE file, in days, or None if unreadable.

    Git-visible means ``git ls-files`` plus ``git ls-files --others
    --exclude-standard`` — tracked files plus untracked-not-ignored ones. A raw
    filesystem walk is a DEFECT here, not a shortcut: measured 2026-09-16, a
    walk called 663 of 671 worktrees recently touched because ``.grimp_cache/``
    and ``.import_linter_cache/`` entries written by a pre-commit run were the
    newest files, while all 22 uncommitted SOURCE files in one of those trees
    were 33 days old. Excluding cache directories by name requires guessing the
    next tool's cache name; asking git drops them out by construction.

    A tree with no visible files at all reports the age of its own HEAD commit's
    absence rather than a fabricated zero: it returns ``None``, which the
    predicate refuses.
    """
    newest: float | None = None
    for args in (
        ("ls-files", "-z"),
        ("ls-files", "--others", "--exclude-standard", "-z"),
    ):
        result = _git_run(worktree, *args)
        if not result.ok:
            return None
        for name in result.stdout.split("\0"):
            if not name:
                continue
            try:
                stamp = (worktree / name).lstat().st_mtime
            except OSError:
                # A listed path that cannot be stat'ed (a broken symlink, a race
                # with a peer lane) is skipped rather than read as age zero.
                continue
            if newest is None or stamp > newest:
                newest = stamp
    if newest is None:
        return None
    return max(0.0, (now - newest) / 86400.0)


_LEADING_TIMESTAMP_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)")


def newest_claim_timestamp_by_ticket(ledger_path: Path) -> dict[str, float]:
    """Map each ticket to the epoch seconds of the NEWEST ``CLAIM`` naming it.

    Deliberately different from :func:`parse_ledger_claims`, which answers "is a
    claim still OPEN" and discards the row's date. The rescue-only fence asks a
    different question — *how recently did any lane say it owns this* — and a
    closed claim from yesterday answers it just as well as an open one. Reusing
    the open-claims map would silently shorten the fence to zero for every
    ticket whose lane remembered to write its TERMINAL row.

    A ``CLAIM`` row with no leading ISO timestamp contributes nothing: it cannot
    be aged, and a row of unknown age must not be read as old.
    """
    newest: dict[str, float] = {}
    if not ledger_path.is_file():
        return newest
    for raw in ledger_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not any(marker in line for marker in _CLAIM_MARKERS):
            continue
        stamp_match = _LEADING_TIMESTAMP_RE.match(line)
        if not stamp_match:
            continue
        try:
            stamp = (
                datetime.strptime(stamp_match.group(1), "%Y-%m-%dT%H:%M:%SZ")
                .replace(tzinfo=UTC)
                .timestamp()
            )
        except ValueError:
            continue
        for ticket in _TICKET_RE.findall(line.upper()):
            if ticket not in newest or stamp > newest[ticket]:
                newest[ticket] = stamp
    return newest


def claim_age_days(
    ticket: str | None, newest_claim: dict[str, float], now: float
) -> float | None:
    """Age in days of the newest ``CLAIM`` naming ``ticket``, or ``None``.

    ``None`` means no dated CLAIM row named it — a real zero only because the
    ledger itself was read successfully; ``main`` refuses to run at all when it
    is not (OMN-15551).
    """
    if ticket is None:
        return None
    stamp = newest_claim.get(ticket)
    if stamp is None:
        return None
    return max(0.0, (now - stamp) / 86400.0)


def collect_rescue_only_facts(
    worktree: Path,
    root: Path,
    *,
    prune_facts: ModelWorktreePruneFacts,
    newest_claim: dict[str, float],
    hand_held: tuple[ModelHandHeldEntry, ...] | None,
    now: float,
) -> ModelRescueOnlyFacts:
    """Observe the rescue-only facts for one worktree. No judgement, no mutation.

    Reuses the content-keyed pass's already-collected facts for everything the
    two classes ask the same question about — branch, pull-request state,
    attributed stashes, probe failures — so the scan does not pay twice for the
    same git calls, and the two classes cannot disagree about what they saw.

    The two ages are measured HERE and only when they can matter: a row whose
    pull-request state already disqualifies it from the class never pays for a
    whole-tree ``ls-files`` walk.
    """
    del root  # the path is already resolved on ``prune_facts``
    disqualified = (
        prune_facts.pr_state
        in (
            EnumBranchPrState.MERGED,
            EnumBranchPrState.NOT_MERGED,
            EnumBranchPrState.UNKNOWN,
        )
        or prune_facts.branch is None
    )

    commit_age = None if disqualified else commit_age_days(worktree, now)
    mtime_age = (
        None if disqualified else newest_git_visible_mtime_age_days(worktree, now)
    )

    return ModelRescueOnlyFacts(
        path=prune_facts.path,
        repo=prune_facts.repo,
        ticket=prune_facts.ticket,
        branch=prune_facts.branch,
        exists=worktree.is_dir(),
        commit_age_days=commit_age,
        mtime_age_days=mtime_age,
        pr_state=prune_facts.pr_state,
        last_claim_age_days=claim_age_days(prune_facts.ticket, newest_claim, now),
        # The classifier runs detached, outside any agent session, so it cannot
        # observe which lanes are live. It reports False and never removes a
        # rescue-only row on that basis; the Prune phase re-derives the set
        # against live state before anything is deleted.
        live_lane=False,
        attributed_stash_count=prune_facts.attributed_stash_count,
        hand_held_available=hand_held is not None,
        hand_held_match=any(
            entry.matches(branch=prune_facts.branch, path=prune_facts.path)
            for entry in (hand_held or ())
        ),
        unreadable_probes=prune_facts.unreadable_probes + prune_facts.timed_out_probes,
    )


def rescue_only_decision_to_json(decision: ModelRescueOnlyDecision) -> dict[str, Any]:
    payload = decision.model_dump(mode="json")
    payload["hold_reasons"] = [r.value for r in decision.hold_reasons]
    payload["pr_state"] = decision.pr_state.value
    payload["disposition"] = decision.disposition.value
    return payload


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


def _portable(text: str, root: Path) -> str:
    """Strip the operator-machine prefix from every path in ``text``.

    The report is published to a shared repository whose readers cannot resolve
    a path on this machine, and the shared scrub refuses a document carrying
    one. Every path this report emits is under the worktrees root or its parent
    registry, so the prefix is pure noise — but it appears in the Removals
    section inside a full git command line, not only in a path column, which is
    why a column-only fix left the report unpublishable.
    """
    registry = str(root.parent).rstrip("/") + "/"
    return text.replace(registry, "")


def _age_cell(value: float | None) -> str:
    """One age column of the rescue-only table, in days.

    An unmeasured age renders as an em dash, never as ``0.0``: a zero there
    would read as "touched just now", which is the opposite of what an
    unreadable probe means.
    """
    return "—" if value is None else f"{value:.1f}"


def render_report(
    decisions: Sequence[ModelWorktreePruneDecision],
    *,
    root: Path,
    executed: bool,
    generated_at: str,
    removals: Sequence[ModelRemovalAttempt],
    tracker_resolved: int,
    debris_decisions: Sequence[ModelPartialMutationDebrisDecision] = (),
    rescue_only_decisions: Sequence[ModelRescueOnlyDecision] = (),
    rescue_only_enabled: bool = False,
    rescue_only_max_age_days: float | None = None,
    rescue_only_claim_fence_days: float | None = None,
    rescue_only_hand_held_available: bool = False,
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

    # --- the rescue-only class [OMN-18442 AC6] ----------------------------
    # Its own section, after everything above and never merged into it: it is a
    # SECOND predicate answering a different question, and it is the only one
    # whose verdict authorises destroying work that exists nowhere else.
    if rescue_only_enabled:
        candidates = [
            d
            for d in rescue_only_decisions
            if d.disposition is EnumRescueOnlyDisposition.REMOVE
        ]
        held = [
            d
            for d in rescue_only_decisions
            if d.disposition is EnumRescueOnlyDisposition.HOLD
        ]
        bar = (
            "unset"
            if rescue_only_max_age_days is None
            else f"{rescue_only_max_age_days:g}"
        )
        fence = (
            "unset"
            if rescue_only_claim_fence_days is None
            else f"{rescue_only_claim_fence_days:g}"
        )
        lines += [
            "",
            "## Rescue-only candidates",
            "",
            f"- **Age bar (caller-supplied):** {bar} day(s), applied to BOTH the "
            "branch tip's committer date and the newest git-visible file",
            f"- **CLAIM fence (caller-supplied):** {fence} day(s)",
            f"- **Hand-held exclusion list:** "
            f"{'read' if rescue_only_hand_held_available else 'UNAVAILABLE — every row held'}",
            f"- **Candidates:** {len(candidates)}",
            f"- **Held:** {len(held)}",
            "- **Removed by this script:** 0 — it reports this class and never "
            "acts on it, whatever the mode. Removal is the morning-prune Prune "
            "phase's, under a re-read of the operator consent row.",
            "",
            "A rescue-only worktree's branch never opened a pull request and has",
            "none open. The content-keyed predicate above can never reach one:",
            "being dirty or ahead-unmerged is exactly why it was rescued. `mtime`",
            "is the newest of `git ls-files` plus `git ls-files --others",
            "--exclude-standard` — never a filesystem walk, which gitignored tool",
            "caches make read recent.",
            "",
            "| Path | Repo | Branch | Commit age (d) | Git-visible mtime age (d) | PR state | Last CLAIM age (d) | Verdict | Hold reasons |",
            "| --- | --- | --- | ---: | ---: | --- | ---: | --- | --- |",
        ]
        if not rescue_only_decisions:
            lines.append("| _none scanned_ | | | | | | | | |")
        for rescue_row in sorted(
            rescue_only_decisions,
            key=lambda d: (d.disposition.value, d.path),
        ):
            rescue_reasons = ", ".join(r.value for r in rescue_row.hold_reasons) or "—"
            lines.append(
                f"| `{rescue_row.path}` | {rescue_row.repo} | "
                f"`{rescue_row.branch or '(detached)'}` | "
                f"{_age_cell(rescue_row.commit_age_days)} | "
                f"{_age_cell(rescue_row.mtime_age_days)} | "
                f"{rescue_row.pr_state.value} | "
                f"{_age_cell(rescue_row.last_claim_age_days)} | "
                f"{rescue_row.disposition.value} | {rescue_reasons} |"
            )

        by_hold_reason: dict[str, int] = defaultdict(int)
        for rescue_row in held:
            for hold_reason in rescue_row.hold_reasons:
                by_hold_reason[hold_reason.value] += 1
        lines += [
            "",
            "### Rescue-only hold reasons",
            "",
            "Every reason on every held row, never only the first.",
            "",
            "| Reason | Count |",
            "| --- | ---: |",
        ]
        if not by_hold_reason:
            lines.append("| _none_ | 0 |")
        for hold_reason_name, hold_count in sorted(
            by_hold_reason.items(), key=lambda kv: (-kv[1], kv[0])
        ):
            lines.append(f"| `{hold_reason_name}` | {hold_count} |")

    lines.append("")
    return _portable("\n".join(lines), root)


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
        "--no-debris",
        action="store_true",
        help=(
            "Skip the partial-mutation-debris pass. That pass proves every "
            "remaining file's content is already a blob in the owning clone, at "
            "two git subprocesses PER FILE, so a candidate that is a whole repo "
            "tree costs tens of thousands of spawns and it runs BEFORE any "
            "removal. Measured 2026-09-14: it held a --execute run for over 25 "
            "minutes on one candidate while every approved removal waited behind "
            "it. Skipping reports no debris and removes no debris; it never "
            "widens what is removed."
        ),
    )
    parser.add_argument(
        "--no-fetch",
        action="store_true",
        help="Skip refreshing origin/dev in each canonical clone before classifying",
    )
    # --- the rescue-only pass [OMN-18442 AC6] -----------------------------
    # Report-only here, on --execute as much as on a dry run. The numbers are
    # REQUIRED and carry no defaults: they are declared once in the
    # morning-worktree-prune workflow config and its format contract, and this
    # script is one of their callers. A default would be a copy nothing
    # compares, in the one pass whose mistakes destroy work rather than
    # misreport it.
    parser.add_argument(
        "--rescue-only",
        action="store_true",
        help=(
            "Also classify the RESCUE-ONLY class (branch never opened a pull "
            "request and has none open) into its own report section. Reports "
            "only: this script never removes a rescue-only worktree, whatever "
            "--execute says. Requires --rescue-only-age-days and "
            "--rescue-only-claim-fence-days."
        ),
    )
    parser.add_argument(
        "--rescue-only-age-days",
        type=float,
        default=None,
        help=(
            "Age bar in days for the rescue-only class, supplied by the caller "
            "from the declared policy (no default here, deliberately). Both "
            "limbs must exceed it: the branch tip's committer date AND the "
            "newest git-visible file."
        ),
    )
    parser.add_argument(
        "--rescue-only-claim-fence-days",
        type=float,
        default=None,
        help=(
            "Window in days within which a ledger CLAIM naming the ticket "
            "fences a rescue-only row. Supplied by the caller from the declared "
            "policy; no default here."
        ),
    )
    parser.add_argument(
        "--rescue-only-hand-held",
        default=None,
        help=(
            "Path to the declared hand-held exclusion file. When it is absent "
            "or unreadable every rescue-only row is held on "
            "'hand_held_list_unavailable' rather than silently classified a "
            "candidate — an exclusion list that cannot be read has not "
            "established that anything is unexcluded."
        ),
    )
    parser.add_argument("--report-md", help="Write the markdown report to this path")
    parser.add_argument("--report-json", help="Write the JSON report to this path")
    parser.add_argument(
        "--limit", type=int, default=0, help="Scan at most N worktrees (0 = all)"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # The rescue-only policy values are the caller's to supply. Refusing here
    # rather than defaulting is the whole point: this repository declares no age
    # bar, so a run that forgot to pass one must fail loudly instead of quietly
    # adopting a number nobody ruled on [OMN-18442 AC6].
    if args.rescue_only:
        missing = [
            flag
            for flag, value in (
                ("--rescue-only-age-days", args.rescue_only_age_days),
                ("--rescue-only-claim-fence-days", args.rescue_only_claim_fence_days),
            )
            if value is None
        ]
        if missing:
            parser.error(
                f"--rescue-only requires {' and '.join(missing)}: the values are "
                "declared in the morning-worktree-prune workflow config and this "
                "script deliberately carries no default for them."
            )
        for flag, value in (
            ("--rescue-only-age-days", args.rescue_only_age_days),
            ("--rescue-only-claim-fence-days", args.rescue_only_claim_fence_days),
        ):
            if value < 0:
                parser.error(f"{flag} must not be negative (got {value})")

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
    # The rescue-only pass rides along on the SAME fact collection [OMN-18442
    # AC6]: it asks a different question of the same observations, and paying
    # twice for `git branch`/`gh pr list`/`git stash list` at registry scale
    # would also let the two classes disagree about what they saw.
    rescue_hand_held: tuple[ModelHandHeldEntry, ...] | None = None
    if args.rescue_only:
        if args.rescue_only_hand_held:
            rescue_hand_held = load_hand_held_entries(
                Path(args.rescue_only_hand_held).expanduser()
            )
        else:
            print(
                "  no --rescue-only-hand-held supplied: every rescue-only row "
                "will be held on hand_held_list_unavailable",
                file=sys.stderr,
            )
        print(
            f"Rescue-only pass ON (report only): bar "
            f"{args.rescue_only_age_days:g}d, claim fence "
            f"{args.rescue_only_claim_fence_days:g}d, hand-held entries "
            f"{'unavailable' if rescue_hand_held is None else len(rescue_hand_held)}",
            flush=True,
        )
    newest_claim_by_ticket = (
        newest_claim_timestamp_by_ticket(ledger_path) if args.rescue_only else {}
    )
    rescue_now = time.time()

    decisions: list[ModelWorktreePruneDecision] = []
    rescue_decisions: list[ModelRescueOnlyDecision] = []
    for index, worktree in enumerate(worktrees, start=1):
        worktree_facts = collect_facts(
            worktree,
            root,
            ticket_states,
            ledger,
            base_ref_cache,
            stash_cache,
            pr_state_cache,
        )
        decisions.append(classify_worktree_prune(worktree_facts))
        if args.rescue_only:
            rescue_decisions.append(
                classify_rescue_only(
                    collect_rescue_only_facts(
                        worktree,
                        root,
                        prune_facts=worktree_facts,
                        newest_claim=newest_claim_by_ticket,
                        hand_held=rescue_hand_held,
                        now=rescue_now,
                    ),
                    max_age_days=args.rescue_only_age_days,
                    claim_fence_days=args.rescue_only_claim_fence_days,
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
    debris_decisions: list[ModelPartialMutationDebrisDecision] = []
    debris_owner_by_path: dict[str, Path] = {}
    canonicals_for_debris: list[Path] = []
    debris_candidates: list[Path] = []
    owner_lookup: dict[str, tuple[Path, str]] = {}
    if args.no_debris:
        print("Skipping the partial-mutation-debris pass (--no-debris)", flush=True)
    else:
        canonicals_for_debris = discover_canonical_clones(root.parent)
        for canonical in canonicals_for_debris:
            for path_str, state in collect_worktree_list_entries(canonical).items():
                owner_lookup[path_str] = (canonical, state)

        debris_candidates = discover_debris_directories(root, set(worktrees))
        print(
            f"Found {len(debris_candidates)} partial-mutation-debris candidate(s) "
            f"across {len(canonicals_for_debris)} canonical clone(s)",
            flush=True,
        )
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

    rescue_candidates = [
        d for d in rescue_decisions if d.disposition is EnumRescueOnlyDisposition.REMOVE
    ]
    rescue_held = [
        d for d in rescue_decisions if d.disposition is EnumRescueOnlyDisposition.HOLD
    ]

    generated_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    report = render_report(
        decisions,
        root=root,
        executed=args.execute,
        generated_at=generated_at,
        removals=removals,
        tracker_resolved=len(ticket_states),
        debris_decisions=debris_decisions,
        rescue_only_decisions=rescue_decisions,
        rescue_only_enabled=bool(args.rescue_only),
        rescue_only_max_age_days=args.rescue_only_age_days,
        rescue_only_claim_fence_days=args.rescue_only_claim_fence_days,
        rescue_only_hand_held_available=rescue_hand_held is not None,
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
                    # The rescue-only class, in its own section so it can never
                    # be mistaken for a content-keyed verdict [OMN-18442 AC6].
                    # `removed` is structurally 0: this script reports the class
                    # and the Prune phase acts on it under the operator consent
                    # row, so a non-zero here would be a defect, not a mode.
                    "rescue_only": {
                        "enabled": bool(args.rescue_only),
                        "max_age_days": args.rescue_only_age_days,
                        "claim_fence_days": args.rescue_only_claim_fence_days,
                        "hand_held_file": args.rescue_only_hand_held,
                        "hand_held_available": rescue_hand_held is not None,
                        "hand_held_entries": (
                            None if rescue_hand_held is None else len(rescue_hand_held)
                        ),
                        "candidate_count": len(rescue_candidates),
                        "held_count": len(rescue_held),
                        "removed": 0,
                        "decisions": [
                            rescue_only_decision_to_json(d) for d in rescue_decisions
                        ],
                    },
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"Wrote JSON report: {json_path}")

    rescue_summary = (
        f" rescue_only_candidates={len(rescue_candidates)} "
        f"rescue_only_held={len(rescue_held)}"
        if args.rescue_only
        else ""
    )
    print(
        f"\nscanned={len(decisions)} safe={len(prunable)} triage={len(triage)} "
        f"timed_out={len(timed_out)} debris={len(debris_decisions)} "
        f"revalidation_refused={len(revalidation_refusals)} "
        f"removed={sum(1 for r in removals if r.ok)}{rescue_summary}"
    )
    if args.rescue_only and rescue_candidates:
        print(
            f"Rescue-only: {len(rescue_candidates)} candidate(s) REPORTED, none "
            "removed — this script never acts on that class. Removal is the "
            "morning-prune Prune phase's, under a re-read of the operator "
            "consent row."
        )
    if not args.execute and prunable:
        print("Dry run — re-run with --execute to remove the prune candidates.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
