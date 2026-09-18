#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Git-sourced sibling pins answer to the canonical clone (OMN-18752).

## Why this module exists

Two sanctioned reconcilers claimed one venv with opposite authorities, and the
skew gate could only see one of them.

``plugins/onex/hooks/scripts/ensure-plugin-venv.sh:224`` builds the plugin CLI
venv with ``uv sync --frozen --no-dev`` — exact match to this repo's
``uv.lock``, which pins ``omnimarket`` by an immutable git rev. That sync is
all-or-nothing: it has no upgrade-only mode and no downgrade refusal.

``omnibase_infra/scripts/check-omnimarket-venv-drift.sh`` converges the same
venv to the canonical ``$OMNI_HOME/omnimarket`` clone (fast-forwarded to
``origin/dev``, OMN-16366), refuses downgrades (OMN-18675), and proves the
result by readback (OMN-18663). An in-process guard built from the same fact
refuses **every** ``onex delegate`` when the installed commit differs from that
clone HEAD.

Whichever ran last won, and left the other's gate red. On 2026-09-18 the venv
sat at the clone head while the lock named a rev 22 merged commits older, so
``check_daemon_venv_skew.py`` reported "pin drift" whose single remedy was a
22-commit downgrade that would have taken ``onex delegate`` down for every lane
on the host. Lane ``daemon-venv-skew-converge-1940`` correctly refused to run
it.

## The resolution

**For a git source the canonical clone is the authority, on every surface, and
the lock follows it.** The lock is re-pointed at the clone head by
``relock_git_sources.py`` under the sibling-lock-refresh workflow; it never
drags a venv backwards.

The consequence for this gate is that a git source is classified by COMMIT
ANCESTRY, never by comparing version strings:

- installed **at** the clone head — ``IN_SYNC``, whatever the lock names. This
  is the exact live condition that produced the OMN-18746 stop.
- installed **behind** the clone — a finding that names
  ``check-omnimarket-venv-drift.sh``, the reconciler that owns converging the
  surface. Deliberately NOT worded as registry pin drift, because that wording
  carries a remedy that moves the package backwards.
- installed **ahead** of the clone, or on a commit the clone does not contain —
  findings. A clone that cannot resolve the commit fails closed.

The LOCK lagging the clone is a separate condition with a separate owner: the
refresh workflow, not the venv reconciler. Reporting it against the venv sends
the reader to a surface that cannot fix it.

Only the version comparison is bypassed for git sources — they are not silent.
``check_daemon_venv_skew.py``'s ``_NON_PINNED_SOURCE_KEYS`` deliberately still
does not list ``git``; git sources are routed here instead.
"""

from __future__ import annotations

import json
import os
import subprocess
import tomllib
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from urllib.parse import urlsplit

# The two owners a finding can name. Kept as constants so the tests assert the
# routing rather than a wording that drifts.
CLONE_RECONCILER = "omnibase_infra/scripts/check-omnimarket-venv-drift.sh --repair"
LOCK_RELOCK_OWNER = ".github/workflows/sibling-lock-refresh.yml"

_GIT_TIMEOUT_SECONDS = 30


class EnumGitSourceAuthority(Enum):
    """Which surface decides what commit a git-sourced sibling must carry.

    ``CLONE`` is claimed only where something actually enforces it. Today that
    is ``omnimarket`` alone: the OMN-18675 in-process guard, which lives inside
    the venv, refuses every ``onex delegate`` when the installed commit differs
    from the canonical clone HEAD, so the clone is that package's authority
    whether this gate agrees or not.

    ``LOCK`` is the default, and it is the default for a reason. Inferring
    clone authority from "is a git source" would silently extend it to
    ``onex_change_control`` and ``omninode_intelligence``, whose revs are
    deliberately reviewed pins with no guard behind them — and would have the
    refresh workflow open unrequested bumps on a governance repo. The authority
    is therefore DECLARED in ``pyproject.toml`` under
    ``[tool.onex.git-source-authority]`` and pinned by a test, so widening it
    is a reviewable act rather than a side effect.
    """

    CLONE = "clone"
    LOCK = "lock"


class EnumGitPinState(Enum):
    """Where an installed git-sourced package sits relative to the clone head."""

    IN_SYNC = "in_sync"
    BEHIND_CLONE = "behind_clone"
    AHEAD_OF_CLONE = "ahead_of_clone"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ModelGitSource:
    """A ``[[package]]`` in ``uv.lock`` whose source is a git rev."""

    name: str
    url: str
    rev: str

    @property
    def repo(self) -> str:
        """The repository directory name under ``$OMNI_HOME``."""
        path = urlsplit(self.url).path
        return path.rsplit("/", 1)[-1].removesuffix(".git")


@dataclass(frozen=True)
class ModelGitPinVerdict:
    state: EnumGitPinState
    finding: str | None


# Git environment variables a caller may have exported that would override
# ``git -C <path>`` and silently retarget every probe at the WRONG repository.
# pre-commit exports GIT_DIR and GIT_INDEX_FILE to every hook it runs, so a
# gate that shells out to git without clearing them reads the repo being
# committed instead of the clone it was handed. This repo already records the
# class in .pre-commit-config.yaml (OMN-18434), and it bit this module on its
# first registered pre-commit run: the ancestry probe reported that the
# canonical clone did not contain a commit that was literally its own HEAD.
_GIT_ENV_OVERRIDES: tuple[str, ...] = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_CEILING_DIRECTORIES",
    "GIT_NAMESPACE",
)


def _clean_git_env() -> dict[str, str]:
    """``os.environ`` with every repository-retargeting git variable removed."""
    return {k: v for k, v in os.environ.items() if k not in _GIT_ENV_OVERRIDES}


def _git(clone: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(clone), *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=_GIT_TIMEOUT_SECONDS,
        env=_clean_git_env(),
    )


def parse_git_sources(lock_path: Path) -> dict[str, ModelGitSource]:
    """Git-sourced packages in ``uv.lock``, keyed by PEP 503 normalized name.

    A uv git source reads ``{ git = "<url>?rev=<sha>#<sha>" }``. The fragment is
    the resolved commit and the query carries the requested revision; the
    fragment is authoritative because a tag or branch in the query resolves to
    it. Both are read so an entry missing one still yields a rev.
    """
    data = tomllib.loads(lock_path.read_text(encoding="utf-8"))
    packages = data.get("package")
    if not isinstance(packages, list):
        return {}

    sources: dict[str, ModelGitSource] = {}
    for pkg in packages:
        if not isinstance(pkg, dict):
            continue
        source = pkg.get("source")
        name = pkg.get("name")
        if not isinstance(source, dict) or not isinstance(name, str):
            continue
        git_url = source.get("git")
        if not isinstance(git_url, str):
            continue

        split = urlsplit(git_url)
        rev = split.fragment
        if not rev:
            for part in split.query.split("&"):
                key, _, value = part.partition("=")
                if key == "rev" and value:
                    rev = value
                    break
        if not rev:
            continue
        base = git_url.split("?", 1)[0].split("#", 1)[0]
        sources[normalize(name)] = ModelGitSource(
            name=normalize(name), url=base, rev=rev
        )
    return sources


def normalize(name: str) -> str:
    """PEP 503 normalization, matching ``check_daemon_venv_skew.py``."""
    return name.lower().replace("_", "-").replace(".", "-")


def canonical_clone(repo: str, registry_root: str | None = None) -> Path | None:
    """The canonical clone for ``repo``, or None when this host has none.

    Absent is the ordinary CI state and is reported by the caller as a stated
    non-evaluation, never as a silent pass.
    """
    root = registry_root or os.environ.get("OMNI_HOME")
    if not root:
        return None
    clone = Path(root) / repo
    return clone if (clone / ".git").exists() else None


def clone_head(clone: Path, branch: str = "HEAD") -> str | None:
    result = _git(clone, "rev-parse", branch)
    return result.stdout.strip() if result.returncode == 0 else None


def _contains(clone: Path, commit: str) -> bool:
    return _git(clone, "cat-file", "-e", f"{commit}^{{commit}}").returncode == 0


def _is_ancestor(clone: Path, maybe_ancestor: str, descendant: str) -> bool:
    return (
        _git(
            clone, "merge-base", "--is-ancestor", maybe_ancestor, descendant
        ).returncode
        == 0
    )


def installed_git_commit(site_packages: Path, package: str) -> str | None:
    """The VCS commit an installed distribution was built from.

    ``direct_url.json`` (PEP 610) is written by the installer for a VCS install
    and carries ``vcs_info.commit_id``. A registry install has no such file,
    which is how a git-sourced package is told apart from a wheel of the same
    name.
    """
    prefix = package.replace("-", "_")
    for dist_info in sorted(site_packages.glob(f"{prefix}-*.dist-info")):
        direct_url = dist_info / "direct_url.json"
        if not direct_url.is_file():
            continue
        try:
            payload = json.loads(direct_url.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        commit = payload.get("vcs_info", {}).get("commit_id")
        if isinstance(commit, str) and commit:
            return commit
    return None


def classify(
    *, clone: Path, installed: str, locked: str, clone_head: str
) -> ModelGitPinVerdict:
    """Place an installed git commit relative to the canonical clone head.

    ``locked`` is carried so the finding can say what the lock names, but it is
    never the thing being judged — the clone is the authority.
    """
    if installed == clone_head:
        return ModelGitPinVerdict(state=EnumGitPinState.IN_SYNC, finding=None)

    for commit, label in ((installed, "installed"), (clone_head, "clone HEAD")):
        if not _contains(clone, commit):
            return ModelGitPinVerdict(
                state=EnumGitPinState.UNKNOWN,
                finding=(
                    f"git source: the {label} commit {commit[:12]} is not present in "
                    f"the canonical clone {clone} — ancestry cannot be resolved, so "
                    f"this fails closed. Fetch the clone, or resolve a diverged clone "
                    f"with {CLONE_RECONCILER}"
                ),
            )

    if _is_ancestor(clone, installed, clone_head):
        return ModelGitPinVerdict(
            state=EnumGitPinState.BEHIND_CLONE,
            finding=(
                f"git source is BEHIND the canonical clone: installed "
                f"{installed[:12]}, clone HEAD {clone_head[:12]} (lock names "
                f"{locked[:12]}). The canonical clone is the authority for a git "
                f"source; converge the venv forward with {CLONE_RECONCILER}. This "
                f"is not a version mismatch and must never be remedied by moving "
                f"the package backwards"
            ),
        )

    if _is_ancestor(clone, clone_head, installed):
        return ModelGitPinVerdict(
            state=EnumGitPinState.AHEAD_OF_CLONE,
            finding=(
                f"git source is AHEAD of the canonical clone: installed "
                f"{installed[:12]}, clone HEAD {clone_head[:12]}. The clone was "
                f"never advanced; fast-forward it (omnibase_infra/scripts/"
                f"pull-all.sh) rather than rolling the venv back"
            ),
        )

    return ModelGitPinVerdict(
        state=EnumGitPinState.UNKNOWN,
        finding=(
            f"git source has DIVERGED from the canonical clone: installed "
            f"{installed[:12]} and clone HEAD {clone_head[:12]} share no ancestry "
            f"line. Resolve the clone by hand before converging anything"
        ),
    )


def lock_lag_blocks() -> bool:
    """Whether a lock lagging the canonical clone should fail the gate. It does not.

    Measured on the operator Mac 2026-09-18: omnimarket published five
    releases in three hours. It is release-on-merge, so the interval in which
    omniclaude's lock equals the canonical clone head is the interval between
    one omnimarket merge and the next — minutes. Blocking on the lag would
    leave this gate red on a developer host essentially always, on a
    condition the person committing cannot fix and which
    ``sibling-lock-refresh.yml`` closes on its own daily schedule. A gate that
    is red on a correct, self-healing state is one people learn to ignore,
    which is rule 5's failure approached from the other side.

    Silence is not the alternative. The lag is ALWAYS printed, with the
    workflow that owns it and the command to run now, so "lagging, known,
    owned" stays distinguishable from "nobody is looking".

    The findings that do block are unchanged and are the ones that break
    something: a venv whose git source disagrees with the canonical clone
    means the OMN-18675 in-process guard refuses every ``onex delegate`` on
    that interpreter, and that is actionable by the person in front of it.
    """
    return False


def lock_lag_finding(
    *, name: str, locked: str, clone_head: str, clone: Path
) -> str | None:
    """Report ``uv.lock`` lagging the canonical clone, against its own owner.

    This is a different condition with a different owner from a venv that lags.
    The venv reconciler cannot fix a stale lock, so naming it here would send
    the reader to a surface that cannot act. Re-locking is
    ``relock_git_sources.py`` under the sibling-lock-refresh workflow.
    """
    if locked == clone_head:
        return None
    if not _contains(clone, locked) or not _contains(clone, clone_head):
        return (
            f"{name}: uv.lock names {locked[:12]}, which the canonical clone "
            f"{clone} does not contain — the lock cannot be checked against the "
            f"clone. Owner: {LOCK_RELOCK_OWNER}"
        )
    if _is_ancestor(clone, locked, clone_head):
        return (
            f"{name}: uv.lock is BEHIND the canonical clone — lock names "
            f"{locked[:12]}, clone HEAD is {clone_head[:12]}. The lock follows the "
            f"clone for a git source. Owner: {LOCK_RELOCK_OWNER} (run it on "
            f"workflow_dispatch to open the bump PR now)"
        )
    return (
        f"{name}: uv.lock names {locked[:12]}, which is not an ancestor of clone "
        f"HEAD {clone_head[:12]} — the lock is ahead of, or diverged from, the "
        f"clone. Owner: {LOCK_RELOCK_OWNER}"
    )


def read_authority(pyproject: Path) -> dict[str, EnumGitSourceAuthority]:
    """Read ``[tool.onex.git-source-authority]``; absent means all lock-governed.

    An unknown value is refused rather than defaulted: a typo that silently
    became ``LOCK`` would turn off the clone check for the one package that
    needs it, which is the failure this whole module exists to remove.
    """
    if not pyproject.is_file():
        return {}
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    table = data.get("tool", {}).get("onex", {}).get("git-source-authority", {})
    if not isinstance(table, dict):
        raise ValueError(
            f"{pyproject}: [tool.onex.git-source-authority] is not a table"
        )
    resolved: dict[str, EnumGitSourceAuthority] = {}
    for name, value in table.items():
        try:
            resolved[normalize(str(name))] = EnumGitSourceAuthority(str(value))
        except ValueError as exc:
            valid = ", ".join(sorted(m.value for m in EnumGitSourceAuthority))
            raise ValueError(
                f"{pyproject}: git-source-authority for {name!r} is {value!r}; "
                f"expected one of {valid}"
            ) from exc
    return resolved


def classify_lock_governed(
    *, name: str, installed: str, locked: str
) -> ModelGitPinVerdict:
    """Judge a lock-governed git source against the rev the lock names.

    Not silent — an installed commit that is not the locked one is an in-place
    mutation of a reviewed pin, which is exactly what this gate is for. What it
    must not do is chase the canonical clone head, which nothing has declared
    as this package's authority.
    """
    if installed == locked:
        return ModelGitPinVerdict(state=EnumGitPinState.IN_SYNC, finding=None)
    return ModelGitPinVerdict(
        state=EnumGitPinState.UNKNOWN,
        finding=(
            f"git source {name!r} is lock-governed and does not match its pin: "
            f"installed {installed[:12]}, uv.lock names {locked[:12]}. Re-sync "
            f"this surface from the lock; do not advance the pin to make the "
            f"mismatch go away"
        ),
    )
