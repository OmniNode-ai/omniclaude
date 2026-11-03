# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""AC1/AC2: a refresh finds any canonical clone that sits beside the registry root.

The recorded layout (three lab hosts): the registry root holds the service
clones, and one more canonical clone, whose remote is under the OmniNode-ai
owner, sits one level up, beside the root. Before the fix the refresh answered
NO_CLONE for it unless it was the one clone the code named, and its
``origin/main`` stayed stale. The sync's own clone set must stay unchanged.

The beside-root repository is a neutral name here: the public-repo hygiene gate
refuses a private repository's name on an added line, and the lookup names no
repository, so the layout is what the tests record, not the name.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.hooks.test_canonical_clone_sync import (
    _GIT_LOCATION_ENV,
    Registry,
    _git,
    ccs,
)

pytestmark = pytest.mark.unit

_BESIDE = "beside_clone"
_BESIDE_SLUG = f"OmniNode-ai/{_BESIDE}"


@pytest.fixture
def reg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Registry:
    registry = Registry(tmp_path)
    for key in _GIT_LOCATION_ENV:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("OMNIBASE_INTERNAL_HOME", raising=False)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    return registry


def _origin(clone: Path, branch: str) -> str:
    return _git("rev-parse", f"refs/remotes/origin/{branch}", cwd=clone)


def test_sibling_clone_refresh_finds_a_clone_beside_the_root(reg: Registry) -> None:
    clone = reg.make(_BESIDE, branch="main", owner="OmniNode-ai", root=reg.home.parent)
    target = reg.advance(_BESIDE, owner="OmniNode-ai", branch="main")
    assert _origin(clone, "main") != target

    results = ccs.run_refresh(reg.env(), _BESIDE_SLUG, None, cwd=reg.tmp)

    assert [(Path(r.clone), r.result) for r in results] == [(clone, ccs.REFRESHED)]
    assert _origin(clone, "main") == target


def test_sibling_clone_refresh_reports_up_to_date_not_no_clone(reg: Registry) -> None:
    clone = reg.make(_BESIDE, branch="main", owner="OmniNode-ai", root=reg.home.parent)
    results = ccs.run_refresh(reg.env(), _BESIDE_SLUG, None, cwd=reg.tmp)
    assert [(Path(r.clone), r.result) for r in results] == [(clone, ccs.UP_TO_DATE)]


def test_sibling_clone_refresh_honours_any_internal_home_override(
    reg: Registry,
) -> None:
    root = reg.tmp / "elsewhere"
    root.mkdir()
    clone = reg.make(_BESIDE, branch="main", owner="OmniNode-ai", root=root)
    target = reg.advance(_BESIDE, owner="OmniNode-ai", branch="main")
    results = ccs.run_refresh(
        reg.env(BESIDE_INTERNAL_HOME=str(clone)), _BESIDE_SLUG, None, cwd=reg.tmp
    )
    assert [(Path(r.clone), r.result) for r in results] == [(clone, ccs.REFRESHED)]
    assert _origin(clone, "main") == target


def test_sibling_clone_refresh_ignores_a_relative_override(reg: Registry) -> None:
    results = ccs.run_refresh(
        reg.env(BESIDE_INTERNAL_HOME="relative/path"), _BESIDE_SLUG, None, cwd=reg.tmp
    )
    assert [r.result for r in results] == [ccs.NO_CLONE]


def test_sibling_clone_refresh_finds_every_clone_beside_the_root(
    reg: Registry,
) -> None:
    first = reg.make(_BESIDE, branch="main", owner="OmniNode-ai", root=reg.home.parent)
    second = reg.make("other_beside", root=reg.home.parent)
    for slug, expected in ((_BESIDE_SLUG, first), ("Acme/other_beside", second)):
        results = ccs.run_refresh(reg.env(), slug, None, cwd=reg.tmp)
        assert [Path(r.clone) for r in results] == [expected], slug


def test_sibling_clone_worktree_is_not_a_canonical_clone(reg: Registry) -> None:
    root = reg.tmp / "elsewhere"
    root.mkdir()
    clone = reg.make(_BESIDE, branch="main", owner="OmniNode-ai", root=root)
    beside = reg.home.parent / _BESIDE
    _git("worktree", "add", "--quiet", "--detach", str(beside), "HEAD", cwd=clone)
    assert (beside / ".git").is_file()
    results = ccs.run_refresh(reg.env(), _BESIDE_SLUG, None, cwd=reg.tmp)
    assert [r.result for r in results] == [ccs.NO_CLONE]


def test_sibling_clone_sync_does_not_pick_up_a_clone_beside_the_root(
    reg: Registry,
) -> None:
    beside = reg.make(_BESIDE, branch="main", owner="OmniNode-ai", root=reg.home.parent)
    clone = reg.make("svc")
    results = ccs.run_sync(reg.env(), None, "manual", None)
    assert all(Path(r.clone) != beside for r in results)
    assert {Path(r.clone) for r in results} == {clone}


@pytest.fixture
def locked_child(reg: Registry) -> Iterator[Path]:
    """A directory beside the registry root whose ``.git`` cannot be statted.

    Mode 000 reproduces on any non-root account what a root-owned ``0700``
    installer directory does to a home directory scan (OMN-17427): the stat of
    ``<child>/.git`` raises ``PermissionError``."""
    if os.geteuid() == 0:
        pytest.skip("root reads a mode 000 directory")
    child = reg.home.parent / "locked_installer"
    child.mkdir()
    child.chmod(0o000)
    try:
        yield child
    finally:
        child.chmod(0o700)


def test_unreadable_directory_beside_the_root_does_not_abort_the_refresh(
    reg: Registry, locked_child: Path
) -> None:
    clone = reg.make(_BESIDE, branch="main", owner="OmniNode-ai", root=reg.home.parent)
    results = ccs.run_refresh(reg.env(), _BESIDE_SLUG, None, cwd=reg.tmp)
    assert locked_child.exists()
    assert [(Path(r.clone), r.result) for r in results] == [(clone, ccs.UP_TO_DATE)]


def test_unreadable_directory_in_a_declared_root_does_not_abort_discovery(
    reg: Registry, locked_child: Path
) -> None:
    clone = reg.make(_BESIDE, branch="main", owner="OmniNode-ai", root=reg.home.parent)
    assert ccs.discover_clones([reg.home.parent]) == [clone]


def test_home_directory_is_never_listed_for_sibling_clones(reg: Registry) -> None:
    """A registry root directly under the account's home: the home is not a root to list."""
    listed = reg.make(_BESIDE, branch="main", owner="OmniNode-ai", root=reg.home.parent)
    env = reg.env(HOME=str(reg.home.parent))
    assert ccs.sibling_clones(env) == []
    results = ccs.run_refresh(env, _BESIDE_SLUG, None, cwd=reg.tmp)
    assert [r.result for r in results] == [ccs.NO_CLONE]
    assert listed.is_dir()


def test_home_directory_layout_reads_the_declared_clone_and_never_the_home(
    reg: Registry, locked_child: Path
) -> None:
    clone = reg.make(_BESIDE, branch="main", owner="OmniNode-ai", root=reg.home.parent)
    target = reg.advance(_BESIDE, owner="OmniNode-ai", branch="main")
    env = reg.env(HOME=str(reg.home.parent), BESIDE_INTERNAL_HOME=str(clone))
    assert ccs.sibling_clones(env) == [clone]
    results = ccs.run_refresh(env, _BESIDE_SLUG, None, cwd=reg.tmp)
    assert [(Path(r.clone), r.result) for r in results] == [(clone, ccs.REFRESHED)]
    assert _origin(clone, "main") == target


def test_non_home_parent_is_still_listed_for_sibling_clones(reg: Registry) -> None:
    clone = reg.make(_BESIDE, branch="main", owner="OmniNode-ai", root=reg.home.parent)
    home = reg.tmp / "account_home"
    home.mkdir()
    assert ccs.sibling_clones(reg.env(HOME=str(home))) == [clone]
