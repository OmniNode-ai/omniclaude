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

import errno
import json
import os
import subprocess
import sys
import threading
import time
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


def test_refresh_waits_for_a_live_holder_and_accepts_its_fetch(
    reg: Registry, monkeypatch: pytest.MonkeyPatch
) -> None:
    clone = reg.make("svc")
    target = reg.advance("svc")
    common = ccs._common_dir(clone)
    assert common is not None
    ready = threading.Event()
    released = threading.Event()

    def holder() -> None:
        with ccs.clone_lock(common, 30, "sync") as lock:
            assert lock.acquired
            ready.set()
            time.sleep(1.0)
            _git(
                "fetch",
                "--quiet",
                "origin",
                "+refs/heads/dev:refs/remotes/origin/dev",
                cwd=clone,
            )
            time.sleep(1.5)
        released.set()

    fetch_calls = 0
    run_git = ccs.run_git

    def counting_run_git(path: Path, *args: str, **kwargs: object) -> ccs.GitResult:
        nonlocal fetch_calls
        if args and args[0] == "fetch":
            fetch_calls += 1
        return run_git(path, *args, **kwargs)

    monkeypatch.setattr(ccs, "run_git", counting_run_git)
    thread = threading.Thread(target=holder)
    thread.start()
    try:
        assert ready.wait(5)
        results = ccs.refresh_clone(clone, None, wait_seconds=20)
        assert [r.result for r in results] == [ccs.REFRESHED], results
        assert results[0].after == target
        assert "lock holder" in (results[0].reason or "")
        assert fetch_calls == 0
        # The landed ref is enough; the holder still has work under its lock.
        assert not released.is_set()
    finally:
        thread.join(timeout=5)
    assert not thread.is_alive()


def test_refresh_fails_loud_at_the_bound_behind_a_holder_that_never_finishes(
    reg: Registry,
) -> None:
    clone = reg.make("svc")
    before = _origin(clone)
    reg.advance("svc")
    common = ccs._common_dir(clone)
    assert common is not None
    ready = threading.Event()
    release = threading.Event()

    def holder() -> None:
        with ccs.clone_lock(common, 30, "sync") as lock:
            assert lock.acquired
            ready.set()
            release.wait(8)

    thread = threading.Thread(target=holder)
    thread.start()
    try:
        assert ready.wait(5)
        started = time.monotonic()
        results = ccs.refresh_clone(clone, None, wait_seconds=2)
        elapsed = time.monotonic() - started
        assert [r.result for r in results] == [ccs.FAILED], results
        reason = results[0].reason or ""
        assert "was held by pid" in reason
        assert str(os.getpid()) in reason
        assert "past the" in reason and "bound" in reason
        assert 1.5 <= elapsed < 10
        assert _origin(clone) == before
    finally:
        release.set()
        thread.join(timeout=5)
    assert not thread.is_alive()


def test_refresh_takes_a_stale_lock_left_by_a_dead_pid(reg: Registry) -> None:
    clone = reg.make("svc")
    common = ccs._common_dir(clone)
    assert common is not None
    dead = subprocess.Popen(["true"])
    dead.wait(timeout=5)
    path = common / ccs.CLONE_LOCK_REF_PATH
    path.write_text(
        json.dumps(
            {
                "pid": dead.pid,
                "role": "sync",
                "host": "h201",
                "since": "2026-10-07T14:00:00Z",
            }
        )
    )
    assert "not running" in ccs.describe_holder(path)
    target = reg.advance("svc")
    started = time.monotonic()
    results = ccs.refresh_clone(clone, None)
    assert time.monotonic() - started < 5
    assert [r.result for r in results] == [ccs.REFRESHED], results
    assert _origin(clone) == target
    assert path.read_text() == ""


def test_refresh_of_a_current_ref_never_touches_the_lock(
    reg: Registry, monkeypatch: pytest.MonkeyPatch
) -> None:
    clone = reg.make("svc")
    common = ccs._common_dir(clone)
    assert common is not None
    ready = threading.Event()
    release = threading.Event()

    def holder() -> None:
        with ccs.clone_lock(common, 30, "sync") as lock:
            assert lock.acquired
            ready.set()
            release.wait(8)

    def unexpected_lock(*args: object, **kwargs: object) -> None:
        pytest.fail("a current ref must not touch the clone lock")

    thread = threading.Thread(target=holder)
    thread.start()
    try:
        assert ready.wait(5)
        monkeypatch.setattr(ccs, "clone_lock", unexpected_lock)
        started = time.monotonic()
        results = ccs.refresh_clone(clone, None, wait_seconds=2)
        assert time.monotonic() - started < 1.5
        assert [r.result for r in results] == [ccs.UP_TO_DATE], results
    finally:
        release.set()
        thread.join(timeout=5)
    assert not thread.is_alive()


def test_refresh_reports_an_unopenable_lock_as_such(
    reg: Registry, monkeypatch: pytest.MonkeyPatch
) -> None:
    clone = reg.make("svc")
    reg.advance("svc")
    open_file = ccs.os.open

    def read_only_lock(path: object, flags: int, mode: int = 0o777) -> int:
        if str(path).endswith(ccs.CLONE_LOCK_NAME):
            raise OSError(errno.EROFS, "Read-only file system")
        return open_file(path, flags, mode)

    monkeypatch.setattr(ccs.os, "open", read_only_lock)
    started = time.monotonic()
    results = ccs.refresh_clone(clone, None)
    assert time.monotonic() - started < 2
    assert [r.result for r in results] == [ccs.FAILED], results
    reason = results[0].reason or ""
    assert reason.startswith("cannot open the clone lock")
    assert "held" not in reason


def test_the_refs_lock_file_is_invisible_to_git(reg: Registry) -> None:
    clone = reg.make("svc")
    reg.advance("svc")
    results = ccs.refresh_clone(clone, None)
    assert [r.result for r in results] == [ccs.REFRESHED], results
    common = ccs._common_dir(clone)
    assert common is not None
    assert (common / ccs.CLONE_LOCK_REF_PATH).exists()
    assert "onex-canonical-clone-sync" not in _git("for-each-ref", cwd=clone)
    _git("fsck", cwd=clone)


@pytest.mark.parametrize("denied_errno", [errno.EROFS, errno.EACCES, errno.EPERM])
def test_refresh_fetches_when_only_the_legacy_lock_is_unwritable(
    reg: Registry, monkeypatch: pytest.MonkeyPatch, denied_errno: int
) -> None:
    clone = reg.make("svc")
    target = reg.advance("svc")
    common = ccs._common_dir(clone)
    assert common is not None
    legacy = common / ccs.CLONE_LOCK_NAME
    open_file = ccs.os.open

    def refs_only(path: object, flags: int, mode: int = 0o777) -> int:
        if path == legacy:
            raise OSError(denied_errno, "legacy lock denied")
        return open_file(path, flags, mode)

    monkeypatch.setattr(ccs.os, "open", refs_only)
    results = ccs.refresh_clone(clone, None)
    assert [r.result for r in results] == [ccs.REFRESHED], results
    assert _origin(clone) == target
    assert (common / ccs.CLONE_LOCK_REF_PATH).read_text() == ""
    # These files are outside the lane's grants, so the fetch must not write them.
    assert not (common / "FETCH_HEAD").exists()


def test_clone_lock_reports_other_legacy_open_errors_immediately(
    reg: Registry, monkeypatch: pytest.MonkeyPatch
) -> None:
    clone = reg.make("svc")
    common = ccs._common_dir(clone)
    assert common is not None
    legacy = common / ccs.CLONE_LOCK_NAME
    open_file = ccs.os.open

    def broken_legacy(path: object, flags: int, mode: int = 0o777) -> int:
        if path == legacy:
            raise OSError(errno.EIO, "Input/output error")
        return open_file(path, flags, mode)

    monkeypatch.setattr(ccs.os, "open", broken_legacy)
    with ccs.clone_lock(common, 30, "refresh") as lock:
        assert not lock.acquired
        assert lock.error and lock.error.startswith(
            f"cannot open the clone lock {legacy}"
        )
        assert lock.waited < 1


def test_clone_lock_still_serializes_with_a_legacy_engine(reg: Registry) -> None:
    clone = reg.make("svc")
    common = ccs._common_dir(clone)
    assert common is not None
    with ccs.file_lock(common / ccs.CLONE_LOCK_NAME, 1) as held:
        assert held
        with ccs.clone_lock(common, 0.3, "refresh") as lock:
            assert not lock.acquired
            assert not lock.abandoned
            assert lock.error is None
            assert lock.waited >= 0.3
            assert "older than the refs/ lock" in (lock.holder or "")
    # Timing out on the legacy lock must also release the primary flock.
    with ccs.clone_lock(common, 1, "refresh") as lock:
        assert lock.acquired
    assert (common / ccs.CLONE_LOCK_REF_PATH).read_text() == ""


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
