# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""A PR's merge state from the local surfaces, never from GitHub (OMN-20368).

The Done-flip guard needs to know whether a cited PR merged. A lane cannot ask
GitHub: the gh shim refuses every read from a lane (OMN-19856, operator ruling
2026-10-07 "read PR state locally; gh only for writes"), so on 2026-10-19 three
tickets whose PRs had merged were refused as ``pr_not_merged``. Two local
sources answer instead, tried in this order:

1. The PR watcher state, read through ``pr_state_local.py --json``. It holds a
   PR's state, head sha and merge time for every open and recently merged PR.
2. The canonical clone's base branch, for a PR the watcher no longer tracks.
   Every squash merge lands as one commit whose subject ends ``(#N)``; that
   commit on ``origin/<base>`` proves the merge and is its merge commit.

Only when neither source proves a state does the read fail, and the error names
the PR and both reasons. Nothing here runs ``gh``.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

from omnibase_core.validators.no_unguarded_git_subprocess import (
    scrub_git_location_env,
)

from omniclaude.nodes.node_linear_effect.models import (
    ModelLocalPrStateRequest,
    ModelLocalPrStateResult,
)

LOCAL_READ_TIMEOUT_S = 30
_WATCHER_SCRIPT = Path("skills") / "merge-drain" / "scripts" / "pr_state_local.py"
_INTERNAL_PLUGIN = Path("omniclaude-internal") / "plugins" / "omni"
_FALLBACK_BASES = ("dev", "main")


class HandlerLocalPrState:
    """Reads one PR's merge state from the PR watcher state, then the canonical clone."""

    def __init__(self, env: Mapping[str, str] | None = None) -> None:
        self._env: Mapping[str, str] = os.environ if env is None else env

    def handle(self, request: ModelLocalPrStateRequest) -> ModelLocalPrStateResult:
        name = request.repo.rsplit("/", 1)[-1]
        facts, watcher_why = self._read_watcher(name, request.number)
        state = str((facts or {}).get("state") or "").upper()
        if facts is not None and state == "MERGED":
            clone_sha, _, _ = self._read_clone(name, request.number)
            return ModelLocalPrStateResult(
                state="MERGED",
                title=str(facts.get("title") or ""),
                head_sha=str(facts.get("head_sha") or ""),
                merge_commit_sha=clone_sha,
                merged_at=str(facts.get("merged_at") or ""),
            )
        if facts is not None and state in ("OPEN", "CLOSED"):
            body = str(facts.get("body") or "")
            return ModelLocalPrStateResult(
                state=state,
                title=str(facts.get("title") or ""),
                head_sha=str(facts.get("head_sha") or ""),
                closing_notes=(body,) if state == "CLOSED" and body else (),
            )
        clone_sha, committed_at, clone_why = self._read_clone(name, request.number)
        if clone_sha:
            return ModelLocalPrStateResult(
                state="MERGED", merge_commit_sha=clone_sha, merged_at=committed_at
            )
        return ModelLocalPrStateResult(
            state="UNKNOWN",
            error=(
                f"cannot prove {request.repo}#{request.number} merged: PR watcher "
                f"state: {watcher_why or 'record is neither merged, open nor closed'}; "
                f"canonical clone: {clone_why}"
            ),
        )

    # -- the PR watcher -----------------------------------------------------

    def _watcher_script(self) -> Path | None:
        roots = (
            [Path(self._env["OMNI_PLUGIN_ROOT"])]
            if self._env.get("OMNI_PLUGIN_ROOT")
            else []
        )
        if self._env.get("OMNI_HOME"):
            roots.append(Path(self._env["OMNI_HOME"]) / _INTERNAL_PLUGIN)
        return next(
            (r / _WATCHER_SCRIPT for r in roots if (r / _WATCHER_SCRIPT).is_file()),
            None,
        )

    def _read_watcher(
        self, name: str, number: int
    ) -> tuple[Mapping[str, object] | None, str]:
        """The watcher's facts for the PR via ``pr_state_local.py --json``, or why none."""
        script = self._watcher_script()
        if script is None:
            return None, "pr_state_local.py not found (OMNI_PLUGIN_ROOT unset)"
        try:
            done = subprocess.run(
                [sys.executable, str(script), "--pr", f"{name}#{number}", "--json"],
                capture_output=True,
                text=True,
                timeout=LOCAL_READ_TIMEOUT_S,
                check=False,
                env=dict(self._env),
            )
        except (subprocess.SubprocessError, OSError) as exc:
            return None, f"pr_state_local.py did not run: {exc}"
        if done.returncode != 0:
            detail = (done.stdout.strip() or done.stderr.strip()).splitlines()
            return None, detail[0][:200] if detail else f"exit {done.returncode}"
        try:
            record = json.loads(done.stdout)
        except ValueError:
            return None, "pr_state_local.py printed no JSON record"
        facts = record.get("facts") if isinstance(record, dict) else None
        if not isinstance(facts, dict):
            return None, "watcher record carries no facts"
        if str(facts.get("repo") or "") != name or facts.get("number") != number:
            return None, "watcher record is for a different PR"
        return facts, ""

    # -- the canonical clone ------------------------------------------------

    def _canonical_clones(self, name: str) -> list[Path]:
        """Clones (``.git`` is a directory) of ``name`` under the registry roots."""
        roots = [
            self._env.get("OMNI_HOME", ""),
            *self._env.get("ONEX_REGISTRY_ROOTS", "").split(":"),
        ]
        candidates = [Path(r) / name for r in roots if r and Path(r).is_absolute()]
        if name == "omnibase_internal":
            # The sibling of the registry, not a child of it (OMN-17427).
            named = self._env.get("OMNIBASE_INTERNAL_HOME", "")
            if named:
                candidates.append(Path(named))
            elif self._env.get("OMNI_HOME"):
                candidates.append(Path(self._env["OMNI_HOME"]).parent / name)
        clones: list[Path] = []
        for candidate in candidates:
            if (candidate / ".git").is_dir() and candidate.resolve() not in {
                c.resolve() for c in clones
            }:
                clones.append(candidate)
        return clones

    @staticmethod
    def _git(clone: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(clone), *args],
            capture_output=True,
            text=True,
            timeout=LOCAL_READ_TIMEOUT_S,
            check=False,
            env=scrub_git_location_env(os.environ),
        )

    def _base_ref(self, clone: Path) -> str | None:
        """``origin/<default>`` from the clone's own ``origin/HEAD``, else dev, else main."""
        head = self._git(
            clone, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"
        )
        if head.returncode == 0 and head.stdout.strip():
            return head.stdout.strip()
        for base in _FALLBACK_BASES:
            ref = f"origin/{base}"
            if (
                self._git(clone, "rev-parse", "--verify", "--quiet", ref).returncode
                == 0
            ):
                return ref
        return None

    def _read_clone(self, name: str, number: int) -> tuple[str, str, str]:
        """``(sha, committed_at, why)``: the base-branch commit whose subject ends ``(#N)``."""
        clones = self._canonical_clones(name)
        if not clones:
            return "", "", f"no canonical clone of {name} under the registered roots"
        ending = re.compile(rf"\(#{number}\)\s*$")
        reasons: list[str] = []
        for clone in clones:
            base = self._base_ref(clone)
            if base is None:
                reasons.append(f"{clone.name}: no origin base branch")
                continue
            try:
                log = self._git(
                    clone,
                    "log",
                    base,
                    "--fixed-strings",
                    f"--grep=(#{number})",
                    "--format=%H%x00%cI%x00%s",
                )
            except (subprocess.SubprocessError, OSError) as exc:
                reasons.append(f"{clone.name}: git log failed: {exc}")
                continue
            if log.returncode != 0:
                reasons.append(
                    f"{clone.name}: git log {base} failed: {log.stderr.strip()[-160:]}"
                )
                continue
            for line in log.stdout.splitlines():
                sha, _, rest = line.partition("\0")
                committed_at, _, subject = rest.partition("\0")
                if ending.search(subject):
                    return sha, committed_at, ""
            reasons.append(f"{clone.name}: no commit on {base} ends (#{number})")
        return "", "", "; ".join(reasons)


__all__ = ["HandlerLocalPrState"]
