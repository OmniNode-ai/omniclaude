# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for ``canonical_clone_sync.py refresh`` (OMN-20495).

The refresh is the one sanctioned way a lane asks for a fresher view of a
remote branch than the canonical-clone sync last gave it. A worktree shares its
canonical clone's refs, so refreshing the clone is refreshing every worktree of
it. Everything runs against hermetic repositories under ``tmp_path`` (the
OMN-19607 test registry); nothing reaches the network.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from tests.hooks.test_canonical_clone_sync import (
    _ENGINE_PATH,
    _GIT_LOCATION_ENV,
    Registry,
    _git,
    ccs,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def reg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Registry:
    registry = Registry(tmp_path)
    for key in _GIT_LOCATION_ENV:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    return registry


def _origin(clone: Path, branch: str = "dev") -> str:
    return _git("rev-parse", f"refs/remotes/origin/{branch}", cwd=clone)


def _worktree(clone: Path, tmp: Path) -> Path:
    wt = tmp / "omni_worktrees" / "OMN-1" / clone.name
    wt.parent.mkdir(parents=True, exist_ok=True)
    _git("worktree", "add", "--quiet", "--detach", str(wt), "HEAD", cwd=clone)
    return wt


def test_refresh_moves_the_origin_ref_to_the_remote_head(reg: Registry) -> None:
    clone = reg.make("svc")
    before = _origin(clone)
    target = reg.advance("svc")
    results = ccs.refresh_clone(clone, None)
    assert [r.result for r in results] == [ccs.REFRESHED], results
    assert (results[0].before, results[0].after, results[0].remote_head) == (
        before,
        target,
        target,
    )
    assert _origin(clone) == target
    # A refresh fetches; it never moves the checked-out branch. That is the
    # sync's job, with all of its refusals.
    assert _git("rev-parse", "HEAD", cwd=clone) == before


def test_refresh_is_seen_by_every_worktree_of_the_clone(
    reg: Registry, tmp_path: Path
) -> None:
    clone = reg.make("svc")
    wt = _worktree(clone, tmp_path)
    target = reg.advance("svc")
    assert _origin(wt) != target
    ccs.refresh_clone(clone, None)
    assert _origin(wt) == target


def test_refresh_from_a_worktree_updates_the_shared_refs(
    reg: Registry, tmp_path: Path
) -> None:
    clone = reg.make("svc")
    wt = _worktree(clone, tmp_path)
    target = reg.advance("svc")
    results = ccs.refresh_clone(wt, None)
    assert [r.result for r in results] == [ccs.REFRESHED], results
    assert _origin(clone) == target


def test_refresh_reports_up_to_date_without_moving_anything(reg: Registry) -> None:
    clone = reg.make("svc")
    head = _origin(clone)
    results = ccs.refresh_clone(clone, None)
    assert [r.result for r in results] == [ccs.UP_TO_DATE], results
    assert _origin(clone) == head


def test_refresh_takes_a_named_branch(reg: Registry) -> None:
    clone = reg.make("svc")
    target = reg.advance("svc", branch="feature/x")
    results = ccs.refresh_clone(clone, ["feature/x"])
    assert [r.result for r in results] == [ccs.REFRESHED], results
    assert _origin(clone, "feature/x") == target


def test_refresh_with_tags_fetches_a_new_tag(reg: Registry) -> None:
    clone = reg.make("svc")
    seed = reg.seeds / "Acme" / "svc"
    _git("tag", "v1.0.0", cwd=seed)
    _git("push", "--quiet", "origin", "v1.0.0", cwd=seed)
    assert ccs.refresh_clone(clone, None)[0].result == ccs.UP_TO_DATE
    assert _git("tag", "--list", "v1.0.0", cwd=clone) == ""
    ccs.refresh_clone(clone, None, tags=True)
    assert _git("tag", "--list", "v1.0.0", cwd=clone) == "v1.0.0"


def test_refresh_fails_for_a_branch_the_remote_does_not_have(reg: Registry) -> None:
    clone = reg.make("svc")
    results = ccs.refresh_clone(clone, ["no-such-branch"])
    assert [r.result for r in results] == [ccs.FAILED], results
    assert "no-such-branch" in (results[0].reason or "")


def test_refresh_follows_main_on_a_main_only_clone(reg: Registry) -> None:
    clone = reg.make("svc", branch="main")
    target = reg.advance("svc", branch="main")
    results = ccs.refresh_clone(clone, None)
    assert [(r.branch, r.result) for r in results] == [("main", ccs.REFRESHED)]
    assert _origin(clone, "main") == target


def test_refresh_waits_for_the_sync_lock_then_skips_a_redundant_fetch(
    reg: Registry,
) -> None:
    """Single flight: a refresh that queued behind a sync which already
    fetched the head reports UP_TO_DATE and fetches nothing."""
    clone = reg.make("svc")
    target = reg.advance("svc")
    ccs.sync_clone(clone)
    results = ccs.refresh_clone(clone, None)
    assert [r.result for r in results] == [ccs.UP_TO_DATE], results
    assert results[0].after == target


def test_run_refresh_resolves_a_repository_by_slug_or_by_name(reg: Registry) -> None:
    clone = reg.make("svc")
    reg.make("other")
    target = reg.advance("svc")
    env = reg.env()
    by_name = ccs.run_refresh(env, "svc", None, cwd=reg.tmp)
    assert {Path(r.clone) for r in by_name} == {clone}
    assert _origin(clone) == target
    by_slug = ccs.run_refresh(env, "acme/SVC", None, cwd=reg.tmp)
    assert [r.result for r in by_slug] == [ccs.UP_TO_DATE]


def test_run_refresh_reports_no_clone_for_an_unknown_repository(
    reg: Registry,
) -> None:
    reg.make("svc")
    results = ccs.run_refresh(reg.env(), "Acme/none", None, cwd=reg.tmp)
    assert [r.result for r in results] == [ccs.NO_CLONE]


def test_run_refresh_without_a_repository_uses_the_cwd(
    reg: Registry, tmp_path: Path
) -> None:
    clone = reg.make("svc")
    wt = _worktree(clone, tmp_path)
    target = reg.advance("svc")
    results = ccs.run_refresh(reg.env(), None, None, cwd=wt)
    assert [r.result for r in results] == [ccs.REFRESHED]
    assert _origin(wt) == target


def test_refresh_cli_waits_and_exits_zero_once_refs_moved(reg: Registry) -> None:
    clone = reg.make("svc")
    target = reg.advance("svc")
    proc = subprocess.run(
        [sys.executable, str(_ENGINE_PATH), "refresh", "Acme/svc", "--wait"],
        capture_output=True,
        text=True,
        env=reg.env(),
        cwd=reg.tmp,
        check=False,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.startswith("REFRESHED"), proc.stdout
    assert _origin(clone) == target
    logged = [r for r in reg.log() if r.get("trigger") == "refresh"]
    assert logged and logged[0]["result"] == ccs.REFRESHED


def test_refresh_cli_exits_one_on_an_unknown_repository(reg: Registry) -> None:
    reg.make("svc")
    proc = subprocess.run(
        [sys.executable, str(_ENGINE_PATH), "refresh", "Acme/none", "--wait"],
        capture_output=True,
        text=True,
        env=reg.env(),
        cwd=reg.tmp,
        check=False,
        timeout=60,
    )
    assert proc.returncode == 1
    assert proc.stdout.startswith("NO_CLONE"), proc.stdout


def test_refresh_cli_without_wait_starts_a_detached_refresh(reg: Registry) -> None:
    clone = reg.make("svc")
    reg.advance("svc")
    proc = subprocess.run(
        [sys.executable, str(_ENGINE_PATH), "refresh", "Acme/svc"],
        capture_output=True,
        text=True,
        env=reg.env(),
        cwd=reg.tmp,
        check=False,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.startswith("STARTED"), proc.stdout
    del clone
