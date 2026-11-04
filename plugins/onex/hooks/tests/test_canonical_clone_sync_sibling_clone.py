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
import stat
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


# OMN-22145: on a lab host a root-owned mode-0700 directory sits beside the
# registry root. A caller that is not root cannot stat anything inside it, and
# the refresh used to die with PermissionError instead of refreshing.
_LOCKED = "locked_neighbour"


def _locked_neighbour(reg: Registry, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A sibling directory whose contents the caller cannot stat.

    Mode 0 on a real directory stands in for the root-owned 0700 one. The
    patched ``is_dir`` raises the same error for it, so the layout also holds
    when the suite itself runs as root (root ignores directory modes).
    """
    locked = reg.home.parent / _LOCKED
    locked.mkdir()
    locked.chmod(0)
    real_is_dir = Path.is_dir

    def is_dir(self: Path) -> bool:
        if _LOCKED in self.parts and self != locked:
            raise PermissionError(13, os.strerror(13), str(self))
        return real_is_dir(self)

    monkeypatch.setattr(Path, "is_dir", is_dir)
    return locked


@pytest.fixture
def _restore_modes(reg: Registry) -> Iterator[None]:
    yield
    for child in reg.home.parent.iterdir():
        if child.name == _LOCKED:
            child.chmod(stat.S_IRWXU)


def test_sibling_clone_permission_unstattable_directory_is_skipped(
    reg: Registry,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    _restore_modes: None,
) -> None:
    clone = reg.make(_BESIDE, branch="main", owner="OmniNode-ai", root=reg.home.parent)
    target = reg.advance(_BESIDE, owner="OmniNode-ai", branch="main")
    locked = _locked_neighbour(reg, monkeypatch)

    results = ccs.run_refresh(reg.env(), _BESIDE_SLUG, None, cwd=reg.tmp)

    assert [(Path(r.clone), r.result) for r in results] == [(clone, ccs.REFRESHED)]
    assert _origin(clone, "main") == target
    notes = [ln for ln in capsys.readouterr().err.splitlines() if str(locked) in ln]
    assert notes == [f"NOTE       skipped {locked}: permission denied"]


def test_sibling_clone_permission_up_to_date_with_unstattable_directory(
    reg: Registry, monkeypatch: pytest.MonkeyPatch, _restore_modes: None
) -> None:
    clone = reg.make(_BESIDE, branch="main", owner="OmniNode-ai", root=reg.home.parent)
    _locked_neighbour(reg, monkeypatch)
    results = ccs.run_refresh(reg.env(), _BESIDE_SLUG, None, cwd=reg.tmp)
    assert [(Path(r.clone), r.result) for r in results] == [(clone, ccs.UP_TO_DATE)]


def test_sibling_clone_permission_cli_prints_one_note_and_exits_zero(
    reg: Registry,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    _restore_modes: None,
) -> None:
    reg.make(_BESIDE, branch="main", owner="OmniNode-ai", root=reg.home.parent)
    locked = _locked_neighbour(reg, monkeypatch)
    for key, value in reg.env().items():
        monkeypatch.setenv(key, value)
    monkeypatch.chdir(reg.tmp)

    code = ccs.main(["refresh", _BESIDE_SLUG, "--wait"])

    out = capsys.readouterr()
    assert code == 0
    assert ccs.UP_TO_DATE in out.out
    notes = [line for line in out.err.splitlines() if str(locked) in line]
    assert len(notes) == 1, out.err
