# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The Done-flip hook's evidence readers: no ``gh`` (OMN-20368).

Before this the MCP hook (``done_flip_guard.main``) ran ``decide`` with its
default readers, and every one of them read GitHub through ``gh api``: the
product contract, the ``repo-evidence / dod-verify`` check run and, for a
merged PR the PR watcher no longer tracks, the PR head. A lane's gh shim
refuses every GitHub read (RULING 2026-10-10T18:17:36Z), so on 2026-10-22
merged and verified tickets were refused. These readers are the lane write
path's (:class:`LaneRepoEvidence`), with the local PR read first so an open
or closed PR the watcher holds costs no bus call.

:meth:`HookEvidenceReaders.repo_evidence` is the guard's one sufficient bar,
for a tick and for Done alike. It returns the contract verdict unchanged.
Documentation-only changes may skip runtime lab proof, but still need bound
acceptance evidence. A merged docs PR is never a substitute for that receipt.
"""

from __future__ import annotations

import functools
import re
from collections.abc import Callable, Sequence
from typing import Protocol, cast

from omniclaude.nodes.node_linear_effect.handlers.handler_lane_repo_evidence import (
    LaneRepoEvidence,
    PRRefLike,
    hook_module,
)

#: File suffixes a documentation-only merge may touch, and nothing else.
DOC_SUFFIXES = frozenset({".md", ".mdx", ".markdown", ".rst", ".adoc", ".txt"})

#: ``(repo, sha)`` -> ``(commit subject, changed paths)``, or ``None`` when unreadable.
MergeCommitReader = Callable[[str, str], "tuple[str, list[str]] | None"]


class _PRStatusLike(Protocol):
    """The fields of ``linear_done_verify.PRStatus`` these readers use."""

    ref: PRRefLike
    state: str
    error: str | None
    head_sha: str
    merge_commit_sha: str


class _VerdictLike(Protocol):
    """The fields of ``no_pr_bound_evidence.RepoEvidenceVerdict`` these readers use."""

    outcome: object
    detail: str


class _ContractReadLike(Protocol):
    status: object
    error: str


def is_doc_path(path: str) -> bool:
    """True for a documentation file: one of :data:`DOC_SUFFIXES`, by name."""
    name = path.rsplit("/", 1)[-1].casefold()
    return "." in name and name[name.rindex(".") :] in DOC_SUFFIXES


def _cites_ticket(subject: str, ticket_id: str) -> bool:
    pattern = rf"(?<![A-Za-z0-9-]){re.escape(ticket_id)}(?!\d)"
    return re.search(pattern, subject, re.IGNORECASE) is not None


class HookEvidenceReaders:
    """PR state and the repo-evidence bar for the Done-flip hook (see module docstring)."""

    def __init__(
        self,
        evidence: LaneRepoEvidence | None = None,
        *,
        local_pr_status: Callable[[PRRefLike], _PRStatusLike] | None = None,
        read_merge_commit: MergeCommitReader | None = None,
    ) -> None:
        self._evidence = evidence or LaneRepoEvidence()
        self._ldv = hook_module("linear_done_verify")
        self._lib = hook_module("no_pr_bound_evidence")
        self._local: Callable[[PRRefLike], _PRStatusLike] = (
            local_pr_status or self._ldv.fetch_pr_status
        )
        self._read_merge_commit = read_merge_commit or self.read_merge_commit

    def pr_status(self, ref: PRRefLike) -> _PRStatusLike:
        """Local first; the read node for a merged PR (its head) or an unread one."""
        local = self._local(ref)
        if not ref.repo or (local.state in ("OPEN", "CLOSED") and not local.error):
            return local
        remote = cast("_PRStatusLike", self._evidence.fetch_pr_status(ref))
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
        evidence = self._evidence
        for clone in evidence._canonical_clones(repo):
            if not evidence._has_commit(clone, sha):
                continue
            subject = evidence._git(clone, ["log", "-1", "--format=%s", sha])
            changed = evidence._git(clone, ["diff", "--name-only", f"{sha}^1", sha])
            if subject.returncode != 0 or changed.returncode != 0:
                return None
            paths = [line for line in changed.stdout.splitlines() if line.strip()]
            return subject.stdout.strip(), paths
        return None

    def _verdict(self, outcome: object, detail: str) -> _VerdictLike:
        made: _VerdictLike = self._lib.RepoEvidenceVerdict(outcome, detail)
        return made

    def repo_evidence(
        self,
        ticket_id: str,
        descriptions: list[str],
        merged: Sequence[_PRStatusLike],
    ) -> _VerdictLike:
        """The bound contract verdict, including for documentation tickets."""
        verdict: _VerdictLike = self._lib.evaluate_repo_evidence(
            ticket_id,
            descriptions,
            merged,
            read_contract=self._evidence.read_contract,
            read_check_runs=self._evidence.read_check_runs,
        )
        if verdict.outcome is self._lib.RepoEvidenceOutcome.NOT_ENGAGED:
            docs = self.docs_evidence(ticket_id, merged)
            return self._verdict(verdict.outcome, f"{verdict.detail}; {docs.detail}")
        return verdict

    def docs_evidence(
        self, ticket_id: str, merged: Sequence[_PRStatusLike]
    ) -> _VerdictLike:
        """Docs diagnostics only: documentation does not discharge a criterion."""
        outcome = self._lib.RepoEvidenceOutcome
        found = self._lib.ContractReadStatus

        def refuse(kind: object, detail: str) -> _VerdictLike:
            return self._verdict(kind, f"docs-only path: {detail}")

        prs = {
            (pr.ref.repo, pr.ref.number): pr
            for pr in merged
            if pr.state == "MERGED" and pr.ref.repo
        }
        if not prs:
            return refuse(outcome.NOT_ENGAGED, "no merged PR to read")
        citing: list[str] = []
        for (repo, number), pr in sorted(prs.items(), key=lambda kv: str(kv[0])):
            assert repo is not None
            source = f"{repo}#{number}"
            if not pr.merge_commit_sha:
                return refuse(outcome.REFUSED, f"{source} has no known merge commit")
            read = cast(
                "_ContractReadLike",
                self._evidence.read_contract(repo, pr.merge_commit_sha, ticket_id),
            )
            if read.status is found.FOUND:
                return refuse(
                    outcome.NOT_ENGAGED,
                    f"{source} carries contracts/{ticket_id}.yaml, so its "
                    "contract decides",
                )
            if read.status is found.ERROR:
                return refuse(
                    outcome.REFUSED, f"{source} contract unreadable ({read.error})"
                )
            commit = self._read_merge_commit(repo, pr.merge_commit_sha)
            if commit is None:
                return refuse(
                    outcome.REFUSED,
                    f"merge {pr.merge_commit_sha[:12]} of {source} is not "
                    "readable in a canonical clone",
                )
            subject, paths = commit
            code = sorted(p for p in paths if not is_doc_path(p))
            if not paths or code:
                return refuse(
                    outcome.NOT_ENGAGED,
                    f"{source} changed non-documentation files "
                    f"({', '.join(code[:5]) or 'none at all'})",
                )
            if _cites_ticket(subject, ticket_id):
                citing.append(f"{source} at merge {pr.merge_commit_sha[:12]}")
        if not citing:
            return refuse(
                outcome.NOT_ENGAGED,
                f"no merged documentation PR names {ticket_id} in its merge subject",
            )
        return self._verdict(
            outcome.NOT_ENGAGED,
            "docs-only: " + ", ".join(citing) + "; no bound PASS receipt",
        )


@functools.cache
def shared_readers() -> HookEvidenceReaders:
    """One :class:`HookEvidenceReaders` per hook process, built on first use."""
    return HookEvidenceReaders()


__all__ = [
    "DOC_SUFFIXES",
    "HookEvidenceReaders",
    "MergeCommitReader",
    "is_doc_path",
    "shared_readers",
]
