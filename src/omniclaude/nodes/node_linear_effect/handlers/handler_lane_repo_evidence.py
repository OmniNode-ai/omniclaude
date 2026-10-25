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

import importlib
import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Protocol

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
        if ref == ev.CURRENT_CONTRACT_REF:
            return ev.ContractRead(
                ev.ContractReadStatus.ERROR,
                error=f"current contract ref {ref} is unreadable in canonical clones",
            )
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


def hook_evidence_readers() -> object:
    """The Done-flip hook's readers (OMN-20368); see ``handler_hook_evidence_readers``."""
    from omniclaude.nodes.node_linear_effect.handlers.handler_hook_evidence_readers import (
        shared_readers,
    )

    return shared_readers()


__all__ = [
    "DEFAULT_BUS_LANE",
    "LaneRepoEvidence",
    "ScmRunner",
    "hook_evidence_readers",
    "hook_lib_dir",
    "hook_module",
    "run_scm",
]
