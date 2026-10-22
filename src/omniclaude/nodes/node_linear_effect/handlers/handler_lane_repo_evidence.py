# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Repo-evidence readers a lab lane can run (OMN-17427).

The Done-flip guard's repo-evidence bar reads PR state, the product contract and
the ``repo-evidence / dod-verify`` check run through ``gh api``. A lane cannot:
the gh shim refuses every GitHub read from a lane (OMN-19856), so on a lab host
the bar answers "PR state read failed" for every ticket whatever its evidence.

These readers answer the same three questions from the sanctioned lane surfaces
instead: ``onex scm`` (the bus gateway and the canonical clones) for PR state,
the merge commit and the named check run, and ``git show`` on the canonical
clone for the contract. They are handed to the guard's own ``decide`` as its
injected readers, so the bar is the guard's bar, not a copy of it.

One read has no lane equivalent: the contract at the PR *head*. A squash-merged
head is not in the canonical clone and its branch is deleted. The bar needs it
only to show the check run covered the contract that merged. The reader proves
that from what the clone does hold: the check checked out the merge of the head
with the base at its ``started_at``, so the contract at the merge commit is the
checked one when no other commit touched the contract file between that start
and the merge. Any commit in that window, or a missing run, fails the read.
"""

from __future__ import annotations

import functools
import importlib
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any, Protocol

from omnibase_core.validators.no_unguarded_git_subprocess import (
    scrub_git_location_env,
)

SCM_TIMEOUT_S = 90
GIT_TIMEOUT_S = 30
DEFAULT_BUS_LANE = "dev"
_BUS_LANE_ENV = "ONEX_SCM_BUS_LANE"
_ONEX_BIN_ENV = "ONEX_BIN"
_HOOK_LIB_ENV = "ONEX_PLUGIN_HOOK_LIB"

#: ``(verb, args)`` -> the ``result`` object of the verb's JSON terminal, or ``None``.
ScmRunner = Callable[[str, list[str]], "dict[str, object] | None"]


def hook_lib_dir() -> Path:
    """The plugin hook library holding the guard modules this package reuses."""
    named = os.environ.get(_HOOK_LIB_ENV)
    if named:
        return Path(named)
    return Path(__file__).resolve().parents[5] / "plugins" / "onex" / "hooks" / "lib"


def hook_module(name: str) -> ModuleType:
    """A guard module from the plugin hook library, imported by its bare name."""
    lib = hook_lib_dir()
    if not lib.is_dir():
        raise RuntimeError(
            f"plugin hook library not found at {lib}; set {_HOOK_LIB_ENV} to "
            "<onex plugin dir>/hooks/lib"
        )
    if str(lib) not in sys.path:
        sys.path.insert(0, str(lib))
    return importlib.import_module(name)


def _onex_bin() -> str:
    named = os.environ.get(_ONEX_BIN_ENV)
    if named:
        return named
    home = os.environ.get("OMNI_HOME", "")
    return str(Path(home) / "omnibase_infra" / "scripts" / "onex")


def run_scm(verb: str, args: list[str]) -> dict[str, object] | None:
    """Run ``onex scm <verb>`` and return its terminal ``result`` object."""
    lane = os.environ.get(_BUS_LANE_ENV, DEFAULT_BUS_LANE)
    command = [_onex_bin(), "scm", verb, *args, "--bus-lane", lane]
    try:
        done = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=SCM_TIMEOUT_S,
            check=False,
            env=scrub_git_location_env(os.environ),
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if done.returncode != 0:
        return None
    for line in reversed(done.stdout.splitlines()):
        if not line.startswith("{"):
            continue
        try:
            payload = json.loads(line)
        except ValueError:
            return None
        result = payload.get("result") if isinstance(payload, dict) else None
        if isinstance(result, dict) and payload.get("outcome") == "completed":
            return result
        return None
    return None


class PRRefLike(Protocol):
    """The two fields of ``linear_done_verify.PRRef`` this module reads."""

    number: int
    repo: str | None


class LaneRepoEvidence:
    """PR status, contract and check-run readers for the guard, lane-safe."""

    def __init__(
        self,
        *,
        scm: ScmRunner = run_scm,
        clone_root: Path | None = None,
    ) -> None:
        self._scm = scm
        # An explicit root is authoritative (including in isolated tests).
        # Otherwise use the same registry discovery as canonical-clone-sync:
        # not every canonical clone is a child named after the repository.
        self._clone_root = clone_root
        self._clones: dict[str, list[Path]] = {}
        self._ldv = hook_module("linear_done_verify")
        self._evidence = hook_module("no_pr_bound_evidence")
        #: (repo, head sha) -> merge commit, from the PR reads.
        self._merge_of_head: dict[tuple[str, str], str] = {}
        #: (repo, head sha) -> the check run's started_at, from the check reads.
        self._check_started: dict[tuple[str, str], str] = {}

    # -- PR state ---------------------------------------------------------

    def fetch_pr_status(self, ref: PRRefLike) -> object:
        """The guard's ``PRStatus`` for a PR, read through ``onex scm``."""
        ldv = self._ldv
        repo = ref.repo
        if not repo:
            return ldv.fetch_pr_status(ref)
        target = f"{repo}#{ref.number}"
        merged = self._scm("pr-merged", [target])
        if merged is None:
            return ldv.PRStatus(
                ref=ref,
                state="UNKNOWN",
                merge_state="UNKNOWN",
                error=f"PR state read failed for {target}: onex scm pr-merged gave no result",
            )
        raw_state = str(merged.get("state") or "").upper()
        if merged.get("merged") is True:
            state = "MERGED"
        elif raw_state in ("OPEN", "CLOSED"):
            state = raw_state
        else:
            state = "UNKNOWN"
        head_sha = str(merged.get("head_sha") or "")
        merge_commit = ""
        if state == "MERGED":
            found = self._scm("pr-merge-commit", [target])
            merge_commit = str((found or {}).get("merge_commit_sha") or "")
            if head_sha and merge_commit:
                self._merge_of_head[(repo, head_sha)] = merge_commit
        closing_notes: tuple[str, ...] = ()
        if state == "CLOSED":
            closing_notes = self._closing_notes(target)
        return ldv.PRStatus(
            ref=ref,
            state=state,
            merge_state="UNKNOWN",
            closing_notes=closing_notes,
            merge_commit_sha=merge_commit,
            head_sha=head_sha,
            merged_at=str(merged.get("merged_at") or "") if state == "MERGED" else "",
        )

    def _closing_notes(self, target: str) -> tuple[str, ...]:
        viewed = self._scm("pr-view", [target]) or {}
        notes = [str(viewed.get("body") or "")]
        comments = viewed.get("comments")
        for comment in comments if isinstance(comments, list) else []:
            if isinstance(comment, dict):
                notes.append(str(comment.get("body") or ""))
        return tuple(n for n in notes if n)

    # -- check runs -------------------------------------------------------

    def read_check_runs(self, repo: str, sha: str) -> list[dict[str, object]] | None:
        """The named ``repo-evidence / dod-verify`` runs on ``sha``, in REST shape."""
        found = self._scm(
            "commit-check-runs",
            [
                repo,
                "--head-sha",
                sha,
                "--check-name",
                self._evidence.REPO_EVIDENCE_CHECK_NAME,
            ],
        )
        runs = (found or {}).get("check_runs")
        if not isinstance(runs, list):
            return None
        out: list[dict[str, object]] = []
        for run in runs:
            if not isinstance(run, dict):
                return None
            shaped = {**run, "app": {"slug": run.get("app_slug")}}
            out.append(shaped)
            started = run.get("started_at")
            if isinstance(started, str) and started:
                key = (repo, sha)
                self._check_started[key] = min(
                    started, self._check_started.get(key, started)
                )
        return out

    # -- contract ---------------------------------------------------------

    def read_contract(self, repo: str, ref: str, ticket_id: str) -> object:
        """``contracts/<ticket>.yaml`` at a commit, from the canonical clone."""
        ev = self._evidence
        path = f"{ev.CONTRACT_DIR}/{ticket_id}.yaml"
        clones = self._canonical_clones(repo)
        name = repo.rsplit("/", maxsplit=1)[-1]
        if self._clone_root is None and name == "omnibase_internal":
            # Reuse the sync's canonical sibling discovery, including its env
            # override and refusal to treat a linked worktree as the clone.
            siblings = hook_module("canonical_clone_sync").sibling_clones(os.environ)
            # The sibling is canonical by its location, so it counts even when
            # no remote or onex.repo names the repository.
            clones = clones + [s for s in siblings if s not in clones]
            if not clones:
                return ev.ContractRead(
                    ev.ContractReadStatus.ERROR,
                    error=f"no canonical sibling clone found for {repo}",
                )
        if not clones:
            return ev.ContractRead(
                ev.ContractReadStatus.ERROR,
                error=f"no canonical clone of {repo} under the registered roots",
            )
        for clone in clones:
            if self._has_commit(clone, ref):
                return self._show(clone, ref, path)
        # A second registered clone may hold the merge even when the first
        # has not synced it yet. The unchanged head proof needs that merge.
        merge = self._merge_of_head.get((repo, ref))
        for clone in clones:
            if merge and self._has_commit(clone, merge):
                return self._contract_at_unheld_head(clone, repo, ref, path)
        return self._contract_at_unheld_head(clones[0], repo, ref, path)

    def _canonical_clones(self, repo: str) -> list[Path]:
        if self._clone_root is not None:
            return [self._clone_root / repo.rsplit("/", maxsplit=1)[-1]]
        if repo not in self._clones:
            sync = hook_module("canonical_clone_sync")
            self._clones[repo] = sync._clones_for(os.environ, repo)
        return self._clones[repo]

    def _has_commit(self, clone: Path, ref: str) -> bool:
        return self._git(clone, ["cat-file", "-e", f"{ref}^{{commit}}"]).returncode == 0

    def _git(self, clone: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(clone), *args],
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_S,
            check=False,
            env=scrub_git_location_env(os.environ),
        )

    def _show(self, clone: Path, ref: str, path: str) -> object:
        ev = self._evidence
        done = self._git(clone, ["show", f"{ref}:{path}"])
        if done.returncode == 0:
            return ev.ContractRead(ev.ContractReadStatus.FOUND, text=done.stdout)
        message = done.stderr.strip()
        if "does not exist" in message or "exists on disk, but not in" in message:
            return ev.ContractRead(ev.ContractReadStatus.ABSENT)
        return ev.ContractRead(ev.ContractReadStatus.ERROR, error=message[-400:])

    def _contract_at_unheld_head(
        self, clone: Path, repo: str, head: str, path: str
    ) -> object:
        ev = self._evidence
        merge = self._merge_of_head.get((repo, head))
        started = self._check_started.get((repo, head))
        if not merge or not started:
            return ev.ContractRead(
                ev.ContractReadStatus.ERROR,
                error=(
                    f"head {head[:12]} is not in the canonical clone and no merge "
                    "commit and check start are known for it"
                ),
            )
        between = self._git(
            clone,
            ["log", "--format=%H", f"--since={started}", f"{merge}^", "--", path],
        )
        if between.returncode != 0:
            return ev.ContractRead(
                ev.ContractReadStatus.ERROR, error=between.stderr.strip()[-400:]
            )
        if between.stdout.strip():
            return ev.ContractRead(
                ev.ContractReadStatus.ERROR,
                error=(
                    f"head {head[:12]} is not in the canonical clone and {path} "
                    f"changed after the check started ({started}): the check "
                    "may not cover the merged contract"
                ),
            )
        return self._show(clone, merge, path)


# --------------------------------------------------------------------------- #
# The Done-flip hook's readers (OMN-20368)
# --------------------------------------------------------------------------- #

#: File suffixes a documentation-only merge may touch, and nothing else.
DOC_SUFFIXES = frozenset({".md", ".mdx", ".markdown", ".rst", ".adoc", ".txt"})

#: ``(repo, sha)`` -> ``(commit subject, changed paths)``, or ``None`` when unreadable.
MergeCommitReader = Callable[[str, str], "tuple[str, list[str]] | None"]


def is_doc_path(path: str) -> bool:
    """True for a documentation file: one of :data:`DOC_SUFFIXES`, by name."""
    name = path.rsplit("/", 1)[-1].casefold()
    return "." in name and name[name.rindex(".") :] in DOC_SUFFIXES


def _cites_ticket(subject: str, ticket_id: str) -> bool:
    pattern = rf"(?<![A-Za-z0-9-]){re.escape(ticket_id)}(?!\d)"
    return re.search(pattern, subject, re.IGNORECASE) is not None


class HookEvidenceReaders:
    """The Done-flip hook's readers: no ``gh``, plus the docs-only verdict.

    Before this the MCP hook (``done_flip_guard.main``) ran ``decide`` with its
    default readers, and every one of them read GitHub through ``gh api``: the
    product contract, the ``repo-evidence / dod-verify`` check run and, for a
    merged PR the PR watcher no longer tracks, the PR head. A lane's gh shim
    refuses every GitHub read (RULING 2026-10-10T18:17:36Z), so on 2026-10-22
    merged and verified tickets were refused. These readers are the lane write
    path's (:class:`LaneRepoEvidence`), with the local PR read first so an open
    or closed PR the watcher holds costs no bus call.

    :meth:`repo_evidence` is the guard's one sufficient bar, for a tick and for
    Done alike. It returns the contract verdict unchanged unless no merged PR
    carries a contract (NOT_ENGAGED); only then is the docs-only verdict
    consulted (operator RULING 2026-10-14T03:57:46Z item 4: docs PRs skip the
    lab proof and heavy gates). It passes only when every merged PR the ticket
    cites changed documentation files alone, none carries the ticket's
    contract, and at least one merge commit's subject names the ticket.
    Anything unreadable refuses.
    """

    def __init__(
        self,
        evidence: LaneRepoEvidence | None = None,
        *,
        local_pr_status: Callable[[PRRefLike], object] | None = None,
        read_merge_commit: MergeCommitReader | None = None,
    ) -> None:
        self._evidence = evidence or LaneRepoEvidence()
        self._ldv = hook_module("linear_done_verify")
        self._lib = hook_module("no_pr_bound_evidence")
        self._local = local_pr_status or self._ldv.fetch_pr_status
        self._read_merge_commit = read_merge_commit or self.read_merge_commit

    def pr_status(self, ref: PRRefLike) -> object:
        """Local first; the read node for a merged PR (its head) or an unread one."""
        local: Any = self._local(ref)
        if not ref.repo or (local.state in ("OPEN", "CLOSED") and not local.error):
            return local
        remote: Any = self._evidence.fetch_pr_status(ref)
        if not remote.error and remote.state in ("MERGED", "OPEN", "CLOSED"):
            if remote.state == "MERGED" and not remote.merge_commit_sha:
                remote.merge_commit_sha = local.merge_commit_sha
            return remote
        if local.state == "MERGED":
            return local
        local.error = f"{local.error or 'no local state'}; {remote.error}"
        return local

    def read_merge_commit(self, repo: str, sha: str) -> tuple[str, list[str]] | None:
        """``(subject, changed paths)`` of ``sha`` from a canonical clone, or None."""
        for clone in self._evidence._canonical_clones(repo):
            if not self._evidence._has_commit(clone, sha):
                continue
            subject = self._evidence._git(clone, ["log", "-1", "--format=%s", sha])
            changed = self._evidence._git(
                clone, ["diff", "--name-only", f"{sha}^1", sha]
            )
            if subject.returncode != 0 or changed.returncode != 0:
                return None
            paths = [line for line in changed.stdout.splitlines() if line.strip()]
            return subject.stdout.strip(), paths
        return None

    def repo_evidence(
        self, ticket_id: str, descriptions: list[str], merged: list[Any]
    ) -> object:
        """The contract verdict, or the docs-only verdict when no contract engaged."""
        lib = self._lib
        verdict: Any = lib.evaluate_repo_evidence(
            ticket_id,
            descriptions,
            merged,
            read_contract=self._evidence.read_contract,
            read_check_runs=self._evidence.read_check_runs,
        )
        if verdict.outcome is not lib.RepoEvidenceOutcome.NOT_ENGAGED:
            return verdict
        docs: Any = self.docs_evidence(ticket_id, merged)
        if docs.outcome is lib.RepoEvidenceOutcome.PASSED:
            return docs
        return lib.RepoEvidenceVerdict(
            verdict.outcome, f"{verdict.detail}; {docs.detail}"
        )

    def docs_evidence(self, ticket_id: str, merged: list[Any]) -> object:
        """PASSED only for a ticket whose whole merged work is documentation."""
        lib = self._lib
        outcome = lib.RepoEvidenceOutcome

        def verdict(kind: object, detail: str) -> object:
            return lib.RepoEvidenceVerdict(kind, f"docs-only path: {detail}")

        prs = {(p.ref.repo, p.ref.number): p for p in merged if p.state == "MERGED"}
        prs = {key: pr for key, pr in prs.items() if key[0]}
        if not prs:
            return verdict(outcome.NOT_ENGAGED, "no merged PR to read")
        citing: list[str] = []
        for (repo, number), pr in sorted(prs.items(), key=lambda kv: str(kv[0])):
            source = f"{repo}#{number}"
            if not pr.merge_commit_sha:
                return verdict(outcome.REFUSED, f"{source} has no known merge commit")
            read: Any = self._evidence.read_contract(
                repo, pr.merge_commit_sha, ticket_id
            )
            if read.status is lib.ContractReadStatus.FOUND:
                return verdict(
                    outcome.NOT_ENGAGED,
                    f"{source} carries contracts/{ticket_id}.yaml, so its "
                    "contract decides",
                )
            if read.status is lib.ContractReadStatus.ERROR:
                return verdict(
                    outcome.REFUSED, f"{source} contract unreadable ({read.error})"
                )
            commit = self._read_merge_commit(repo, pr.merge_commit_sha)
            if commit is None:
                return verdict(
                    outcome.REFUSED,
                    f"merge {pr.merge_commit_sha[:12]} of {source} is not "
                    "readable in a canonical clone",
                )
            subject, paths = commit
            code = sorted(p for p in paths if not is_doc_path(p))
            if not paths or code:
                return verdict(
                    outcome.NOT_ENGAGED,
                    f"{source} changed non-documentation files "
                    f"({', '.join(code[:5]) or 'none at all'})",
                )
            if _cites_ticket(subject, ticket_id):
                citing.append(f"{source} at merge {pr.merge_commit_sha[:12]}")
        if not citing:
            return verdict(
                outcome.NOT_ENGAGED,
                f"no merged documentation PR names {ticket_id} in its merge subject",
            )
        return lib.RepoEvidenceVerdict(
            outcome.PASSED, "docs-only: " + ", ".join(citing)
        )


@functools.cache
def hook_evidence_readers() -> HookEvidenceReaders:
    """One :class:`HookEvidenceReaders` per hook process, built on first use."""
    return HookEvidenceReaders()


__all__ = [
    "DEFAULT_BUS_LANE",
    "DOC_SUFFIXES",
    "HookEvidenceReaders",
    "LaneRepoEvidence",
    "MergeCommitReader",
    "ScmRunner",
    "hook_evidence_readers",
    "hook_lib_dir",
    "hook_module",
    "is_doc_path",
    "run_scm",
]
