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
