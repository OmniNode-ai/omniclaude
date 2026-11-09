# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The omnimarket pin is at or after dev-20261109213140-ea2af8addd71 (OMN-23386).

The first-party-ref validator's ``stale_pin`` rule grades omniclaude's omnimarket
pin against omnimarket's newest dev merge tag and refuses a pin that trails it by
more than the bound omnibase_core declares (50 merges, 72 hours at the pin CI runs
with). On 2026-11-09 the pin trailed by 56 merges and 16.2 hours, which reddened
``first-party-ref`` on dev and held every other omniclaude change behind it.

This test pins the floor the bump established, so a later pin can only move
forward. It reads both homes of the pin, because the two can drift apart:
``tool.uv.override-dependencies`` carries the direct git reference and
``tool.uv.sources.omnimarket`` carries the tag the resolver uses.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]

# The pin OMN-23386 moved to; a pin older than this stamp is the stale_pin red.
OMN23386_PIN_STAMP = "20261109213140"

TAG = re.compile(r"dev-([0-9]{14})-[0-9a-f]{12}")


def _pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_uv_source_tag_is_at_or_after_the_omn23386_pin() -> None:
    tag = _pyproject()["tool"]["uv"]["sources"]["omnimarket"]["tag"]
    found = TAG.fullmatch(tag)
    assert found, tag
    assert found.group(1) >= OMN23386_PIN_STAMP, tag


def test_override_dependency_tag_is_at_or_after_the_omn23386_pin() -> None:
    """The ``omnimarket @ git+...@<tag>`` override must not trail the uv source."""
    deps = _pyproject()["tool"]["uv"]["override-dependencies"]
    direct = [d for d in deps if d.startswith("omnimarket @ ")]
    assert len(direct) == 1, deps
    found = TAG.search(direct[0])
    assert found, direct[0]
    assert found.group(1) >= OMN23386_PIN_STAMP, direct[0]


def test_both_homes_name_the_same_tag() -> None:
    data = _pyproject()
    source_tag = data["tool"]["uv"]["sources"]["omnimarket"]["tag"]
    direct = next(
        d
        for d in data["tool"]["uv"]["override-dependencies"]
        if d.startswith("omnimarket @ ")
    )
    found = TAG.search(direct)
    assert found, direct
    assert found.group(0) == source_tag, (found.group(0), source_tag)
