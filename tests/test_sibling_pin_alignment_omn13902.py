# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-13902: the omnimarket git rev is one commit on every surface.

The sibling-lock refresh advances a clone-governed git source forward only, and
rewrites the dependency occurrence and the source occurrence together. These
tests read the three places a rev lives -- the dependency line, the
``[tool.uv.sources]`` entry and ``uv.lock`` -- and refuse a refresh that moved
one and left another behind.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SHA = re.compile(r"[0-9a-f]{40}")


def _dependency_rev() -> str:
    text = (_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    pins = re.findall(
        r'"omnimarket @ git\+https://github\.com/OmniNode-ai/omnimarket\.git@([0-9a-f]{40})"',
        text,
    )
    assert len(pins) == 1, "omnimarket must be pinned by exactly one git dependency"
    return pins[0]


def _source_rev() -> str:
    text = (_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    revs = re.findall(
        r'^omnimarket = \{ git = "[^"]+", rev = "([0-9a-f]{40})" \}',
        text,
        flags=re.MULTILINE,
    )
    assert len(revs) == 1, "omnimarket must have exactly one [tool.uv.sources] rev"
    return revs[0]


def _locked_revs() -> set[str]:
    lock = (_REPO_ROOT / "uv.lock").read_text(encoding="utf-8")
    return set(
        re.findall(r"omnimarket\.git\?rev=([0-9a-f]{40})", lock),
    )


def test_omnimarket_rev_is_a_full_commit_sha() -> None:
    assert _SHA.fullmatch(_dependency_rev())
    assert _SHA.fullmatch(_source_rev())


def test_dependency_and_source_rev_are_the_same_commit() -> None:
    assert _dependency_rev() == _source_rev()


def test_lock_resolves_omnimarket_at_the_declared_rev() -> None:
    assert _locked_revs() == {_source_rev()}
