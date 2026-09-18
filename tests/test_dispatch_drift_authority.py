# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-18752: the drift guard resolves the SAME ref the canonical clone is on.

Until this change the two gates governing one package answered to different
refs. ``check_omnimarket_dispatch_drift.py`` resolved ``git ls-remote <remote>
refs/heads/main``; the OMN-18675 venv guard resolved the canonical clone, which
is checked out on ``dev``. omnimarket's ``main`` is release-synced, so it lags
``dev`` and the two demanded different commits at every moment except the
instant main caught up. Observed live 2026-09-18: the venv guard required
``cfd5b4eb`` (clone HEAD) while this gate required ``7f77f9d8`` (main), and this
gate's printed remedy -- "update pyproject.toml and run uv lock" -- would have
broken delegation for every lane on the host.

Neither gate's live half was registered anywhere, which is why it had never
surfaced.

The resolution: the canonical clone's CHECKED-OUT head is the authority,
whichever branch it is on, and this gate reads it before any network probe.
Where there is no clone (CI) it falls back to ``uv.lock``, which follows the
clone through the refresh workflow -- never to a remote branch chosen
independently of the clone.

The fourth touch point is gone rather than automated. A bump used to have to
move a hand-maintained 40-hex literal in the gate's own workflow, and that
literal is the one most easily missed -- it failed the PR on the previous two
bumps. It is now derived, so it cannot go stale.
"""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Mapping
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parent.parent
_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "omnimarket-dispatch-drift-gate.yml"

_GIT_LOCATION_VARS = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_CEILING_DIRECTORIES",
    "GIT_NAMESPACE",
)


def scrub_git_location_env(env: Mapping[str, str]) -> dict[str, str]:
    """OMN-18434: an exported GIT_DIR overrides ``git -C`` and retargets this repo."""
    return {k: v for k, v in env.items() if k not in _GIT_LOCATION_VARS}


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
        env=scrub_git_location_env(os.environ),
    ).stdout.strip()


@pytest.fixture
def clone_on_a_non_main_branch(tmp_path: Path) -> tuple[Path, str, str]:
    """A clone checked out on ``dev``, ahead of its own ``main`` — the live shape."""
    repo = tmp_path / "omnimarket"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "t")
    (repo / "f.txt").write_text("release\n", encoding="utf-8")
    _git(repo, "add", "f.txt")
    _git(repo, "commit", "-q", "-m", "release")
    main_sha = _git(repo, "rev-parse", "HEAD")

    _git(repo, "checkout", "-q", "-b", "dev")
    (repo / "f.txt").write_text("unreleased\n", encoding="utf-8")
    _git(repo, "add", "f.txt")
    _git(repo, "commit", "-q", "-m", "unreleased")
    dev_sha = _git(repo, "rev-parse", "HEAD")

    assert main_sha != dev_sha
    return repo, main_sha, dev_sha


def test_expected_sha_is_the_clones_checked_out_head_not_main(
    clone_on_a_non_main_branch: tuple[Path, str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The gate answers to the clone's checked-out head, whichever branch it is."""
    from scripts import check_omnimarket_dispatch_drift as drift  # noqa: PLC0415

    repo, main_sha, dev_sha = clone_on_a_non_main_branch
    for var in (
        "OMNIMARKET_EXPECTED_SHA",
        "OMNIMARKET_CANONICAL_SHA",
        "OMNIMARKET_ROOT",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("OMNI_HOME", str(tmp_path))

    sha, source = drift._resolve_expected_sha()

    assert sha == dev_sha, (
        "the gate resolved a ref other than the clone's checked-out head; a "
        "clone on dev and a guard on main is the split that produced the live "
        "refusals this change exists to remove"
    )
    assert sha != main_sha
    assert "clone" in source


def test_no_remote_branch_probe_decides_the_expected_sha(
    clone_on_a_non_main_branch: tuple[Path, str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A remote branch chosen independently of the clone must not be consulted.

    Enforced by reading the resolver's own source: a network probe that happens
    to be unreachable in a test environment would let the old behaviour pass.
    """
    from scripts import check_omnimarket_dispatch_drift as drift  # noqa: PLC0415

    source = Path(drift.__file__).read_text(encoding="utf-8")
    body = source.split("def _resolve_expected_sha", 1)[1].split("\ndef ", 1)[0]
    # Strip the docstring and the comments: both explain which source was
    # removed and why, and that explanation must survive. What must not
    # survive is the call itself.
    code = "\n".join(
        line
        for line in body.split('"""', 2)[-1].splitlines()
        if not line.lstrip().startswith("#")
    )
    assert "ls-remote" not in code, (
        "the resolver still probes a remote branch; the clone's checked-out "
        "head and, failing that, uv.lock are the only authorities"
    )


def test_lock_is_the_fallback_where_no_clone_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CI has no canonical clone, and must not fall through to a remote branch.

    ``uv.lock`` follows the clone through the refresh workflow, so reading it
    keeps CI and the host answering to one authority with at most a bump-PR of
    latency between them.
    """
    from scripts import check_omnimarket_dispatch_drift as drift  # noqa: PLC0415

    for var in (
        "OMNIMARKET_EXPECTED_SHA",
        "OMNIMARKET_CANONICAL_SHA",
        "OMNIMARKET_ROOT",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("OMNI_HOME", str(tmp_path / "no-registry"))

    sha, source = drift._resolve_expected_sha()

    lock_text = (_REPO_ROOT / "uv.lock").read_text(encoding="utf-8")
    assert sha in lock_text, "the fallback did not come from uv.lock"
    assert "lock" in source


def test_the_workflow_no_longer_carries_a_hand_held_sha_literal() -> None:
    """The fourth touch point is deleted, not automated.

    A bump used to have to move a 40-hex literal in this workflow by hand, and
    it is the touch point most easily missed -- the gate failed the PR on each
    of the two previous bumps naming exactly this literal. A derived value
    cannot go stale, so the way to keep it correct is for it not to exist.
    """
    text = _WORKFLOW.read_text(encoding="utf-8")
    body = "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )
    stale = re.findall(r"\b[0-9a-f]{40}\b", body)
    assert not stale, (
        f"a hand-held commit literal is back in {_WORKFLOW.name}: {stale}. "
        f"The expected sha is derived from uv.lock; reintroducing a literal "
        f"reintroduces the touch point that failed the last two bumps"
    )
