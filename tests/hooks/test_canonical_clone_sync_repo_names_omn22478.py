# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""A repository named with a hyphen or an underscore reaches its clone (OMN-22478).

A clone's ``onex.repo`` can spell its name with underscores while its remote,
and the name the lane git-fetch refusal quotes, spell it with hyphens. The
refresh the refusal recommends answered NO_CLONE for the name it had just been
given. The stand-in below has the same
split: the remote URL says ``kb-internal`` and ``onex.repo`` says
``kb_internal``.
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


@pytest.fixture
def reg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Registry:
    registry = Registry(tmp_path)
    for key in _GIT_LOCATION_ENV:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("OMNIBASE_INTERNAL_HOME", raising=False)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    return registry


@pytest.fixture
def split_name_clone(reg: Registry) -> Path:
    clone = reg.make("kb-internal")
    _git("config", "onex.repo", "Acme/kb_internal", cwd=clone)
    return clone


@pytest.mark.parametrize(
    "name",
    [
        "Acme/kb-internal",
        "Acme/kb_internal",
        "acme/KB-INTERNAL",
        "kb-internal",
        "kb_internal",
        "Acme/kb-internal.git",
    ],
)
def test_refresh_reaches_the_clone_by_either_spelling(
    name: str, reg: Registry, split_name_clone: Path
) -> None:
    target = reg.advance("kb-internal")
    results = ccs.run_refresh(reg.env(), name, None, cwd=reg.tmp)
    assert [r.result for r in results] == [ccs.REFRESHED], (name, results)
    assert Path(results[0].clone) == split_name_clone
    assert _git("rev-parse", "refs/remotes/origin/dev", cwd=split_name_clone) == target


def test_refresh_still_reports_no_clone_for_a_name_matching_none(
    reg: Registry, split_name_clone: Path
) -> None:
    results = ccs.run_refresh(reg.env(), "Acme/kb-external", None, cwd=reg.tmp)
    assert [r.result for r in results] == [ccs.NO_CLONE]


def test_the_merge_triggered_sync_reaches_the_clone_by_the_hyphen_name(
    reg: Registry, split_name_clone: Path
) -> None:
    reg.make("other")
    results = ccs.run_sync(reg.env(), ["Acme/kb-internal"], "merge")
    assert [Path(r.clone) for r in results] == [split_name_clone]
    assert all(r.result != ccs.NO_CLONE for r in results)
