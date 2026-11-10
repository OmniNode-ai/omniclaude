# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The omnimarket pin carries omnimarket#5470 (A3a), merged 2026-11-08T20:35:40Z (OMN-23162).

omnimarket's ``check_wire_compatibility`` grades a wire change against this
repository's pin, so the pin must be a dev merge tag at or after the A3a merge.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
A3A_MERGE_STAMP = "20261108203540"
TAG = re.compile(r"dev-([0-9]{14})-[0-9a-f]{12}")


def test_omnimarket_source_tag_is_at_or_after_a3a() -> None:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    tag = tomllib.loads(text)["tool"]["uv"]["sources"]["omnimarket"]["tag"]
    found = TAG.fullmatch(tag)
    assert found, tag
    assert found.group(1) >= A3A_MERGE_STAMP, tag
