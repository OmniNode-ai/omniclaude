# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The omnimarket pin and lock retain the OMN-19998 staleness repair.

Read TOML fields rather than counting tag mentions in comments. Later dev tag
bumps remain valid, while restoring the stale merge-base pin fails the floor.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
GIT = "https://github.com/OmniNode-ai/omnimarket.git"
PIN_FLOOR_TAG = "dev-20261108030126-b88810068556"
PIN_FLOOR_SHA = "b888100685565b7b4a01ab2b95e079f2004dd9c8"


def _uv_config() -> dict[str, Any]:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)["tool"]["uv"]


def _lock() -> dict[str, Any]:
    with (ROOT / "uv.lock").open("rb") as handle:
        return tomllib.load(handle)


def test_source_pin_is_at_least_the_repaired_dev_tag() -> None:
    source = _uv_config()["sources"]["omnimarket"]
    assert set(source) == {"git", "tag"}, source
    assert source["git"] == GIT, source
    tag = source["tag"]
    match = re.fullmatch(r"dev-(\d{14})-([0-9a-f]{12})", tag)
    assert match is not None, tag
    assert match[1] >= PIN_FLOOR_TAG.split("-")[1], tag


def test_override_matches_the_source_pin() -> None:
    config = _uv_config()
    overrides = [
        value
        for value in config["override-dependencies"]
        if value.split(" @ ", 1)[0] == "omnimarket"
    ]
    tag = config["sources"]["omnimarket"]["tag"]
    assert overrides == [f"omnimarket @ git+{GIT}@{tag}"]


def test_lock_resolves_the_source_tag_to_its_commit() -> None:
    packages = [p for p in _lock()["package"] if p["name"] == "omnimarket"]
    assert len(packages) == 1, packages
    source = packages[0]["source"]
    assert set(source) == {"git"}, source
    url = urlsplit(source["git"])
    tag = _uv_config()["sources"]["omnimarket"]["tag"]
    assert url._replace(query="", fragment="").geturl() == GIT
    assert parse_qs(url.query) == {"tag": [tag]}
    assert re.fullmatch(r"[0-9a-f]{40}", url.fragment), url.fragment
    assert tag.endswith(f"-{url.fragment[:12]}")
    if tag == PIN_FLOOR_TAG:
        assert url.fragment == PIN_FLOOR_SHA


def test_lock_override_and_requirement_match_the_source_tag() -> None:
    lock = _lock()
    tag = _uv_config()["sources"]["omnimarket"]["tag"]
    expected = {"name": "omnimarket", "git": f"{GIT}?tag={tag}"}
    assert [p for p in lock["manifest"]["overrides"] if p["name"] == "omnimarket"] == [
        expected
    ]
    consumer = next(p for p in lock["package"] if p["name"] == "omninode-claude")
    requirements = consumer["metadata"]["requires-dist"]
    assert [p for p in requirements if p["name"] == "omnimarket"] == [expected]
