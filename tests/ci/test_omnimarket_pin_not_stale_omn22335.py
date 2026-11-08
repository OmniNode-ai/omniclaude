# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The omnimarket pin is not the tag the Pre-commit Suite recorded as stale (OMN-22335).

On 2026-11-03 the Pre-commit Suite failed on every open pull request because the
core ``stale_pin`` rule found omnimarket pinned 75 merges behind the newest dev
merge tag. The failed-log excerpt is kept in ``fixtures/``. This test reads the
stale tag out of that excerpt and requires the three places that name the pin
(the dependency, ``[tool.uv.sources]`` and ``uv.lock``) to agree on one tag that
is not the recorded stale one.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
EXCERPT = ROOT / "tests/ci/fixtures/precommit_stale_omnimarket_pin_omn22335.txt"
TAG = r"dev-[0-9]{14}-[0-9a-f]{12}"
STALE_RULE = re.compile(rf"\[stale_pin\] stale_pin: omnimarket@({TAG}) trails newest")
LOCK_TAG = re.compile(rf'omnimarket\.git\?tag=({TAG})#[0-9a-f]{{40}}"')


def _recorded_stale_tag() -> str:
    found = STALE_RULE.search(EXCERPT.read_text(encoding="utf-8"))
    assert found, "the recorded excerpt no longer names a stale omnimarket pin"
    return found.group(1)


def _pyproject_tags() -> tuple[set[str], set[str]]:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    deps = set(re.findall(rf'"omnimarket @ git\+[^"@]+@({TAG})"', text))
    source = tomllib.loads(text)["tool"]["uv"]["sources"]["omnimarket"]
    return deps, {source["tag"]}


def test_the_excerpt_names_the_stale_tag() -> None:
    assert re.fullmatch(TAG, _recorded_stale_tag())


def test_pyproject_does_not_pin_the_recorded_stale_tag() -> None:
    deps, sources = _pyproject_tags()
    stale = _recorded_stale_tag()
    assert deps, "no omnimarket direct-url pin found in pyproject.toml"
    assert stale not in deps
    assert stale not in sources


def test_pyproject_and_lock_name_one_omnimarket_tag() -> None:
    deps, sources = _pyproject_tags()
    lock = set(LOCK_TAG.findall((ROOT / "uv.lock").read_text(encoding="utf-8")))
    assert len(deps | sources | lock) == 1, (deps, sources, lock)
