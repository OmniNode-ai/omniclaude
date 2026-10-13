# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-13902: the omnimarket git rev is one commit on every surface.

The sibling-lock refresh advances a clone-governed git source forward only, and
rewrites the dependency occurrence and the source occurrence together. These
tests read the three places a rev lives -- the dependency line, the
``[tool.uv.sources]`` entry and ``uv.lock`` -- and refuse a refresh that moved
one and left another behind.

The check is a function of file text, so each test that reads the repo's own
files is paired with a planted-skew case that proves the same check refuses a
skewed copy. A check that has only ever seen the aligned tree has not shown it
can fail.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SHA = re.compile(r"[0-9a-f]{40}")
_DEPENDENCY_PIN = re.compile(
    r'"omnimarket @ git\+https://github\.com/OmniNode-ai/omnimarket\.git@([0-9a-f]{40})"'
)
_SOURCE_PIN = re.compile(
    r'^omnimarket = \{ git = "[^"]+", rev = "([0-9a-f]{40})" \}',
    flags=re.MULTILINE,
)
_LOCK_PIN = re.compile(r"omnimarket\.git\?rev=([0-9a-f]{40})")

# A full sha that is no commit omnimarket has ever carried: every planted skew
# below moves exactly one surface onto it.
_PLANTED_REV = "0123456789abcdef0123456789abcdef01234567"


def skew_problems(pyproject_text: str, lock_text: str) -> list[str]:
    """Name every way the omnimarket rev differs between the three surfaces."""
    problems: list[str] = []
    dependency = _DEPENDENCY_PIN.findall(pyproject_text)
    source = _SOURCE_PIN.findall(pyproject_text)
    if len(dependency) != 1:
        problems.append(
            f"omnimarket must be pinned by exactly one git dependency, found {len(dependency)}"
        )
    if len(source) != 1:
        problems.append(
            f"omnimarket must have exactly one [tool.uv.sources] rev, found {len(source)}"
        )
    if len(dependency) == 1 and len(source) == 1 and dependency[0] != source[0]:
        problems.append(
            f"dependency rev {dependency[0]} differs from source rev {source[0]}"
        )
    locked = set(_LOCK_PIN.findall(lock_text))
    if len(source) == 1 and locked != {source[0]}:
        problems.append(
            f"uv.lock resolves omnimarket at {sorted(locked)}, not the source rev {source[0]}"
        )
    return problems


def _repo_texts() -> tuple[str, str]:
    return (
        (_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"),
        (_REPO_ROOT / "uv.lock").read_text(encoding="utf-8"),
    )


def _source_rev(pyproject_text: str) -> str:
    return _SOURCE_PIN.findall(pyproject_text)[0]


def test_omnimarket_rev_is_one_full_sha_on_every_surface() -> None:
    pyproject_text, lock_text = _repo_texts()
    assert skew_problems(pyproject_text, lock_text) == []
    assert _SHA.fullmatch(_source_rev(pyproject_text))


def test_planted_source_skew_is_refused() -> None:
    pyproject_text, lock_text = _repo_texts()
    live = _source_rev(pyproject_text)
    skewed = _SOURCE_PIN.sub(
        lambda m: m.group(0).replace(live, _PLANTED_REV), pyproject_text
    )
    assert skewed != pyproject_text
    problems = skew_problems(skewed, lock_text)
    assert any("differs from source rev" in p for p in problems), problems


def test_planted_lock_skew_is_refused() -> None:
    pyproject_text, lock_text = _repo_texts()
    live = _source_rev(pyproject_text)
    skewed = lock_text.replace(
        f"omnimarket.git?rev={live}", f"omnimarket.git?rev={_PLANTED_REV}"
    )
    assert skewed != lock_text
    problems = skew_problems(pyproject_text, skewed)
    assert any("uv.lock resolves omnimarket" in p for p in problems), problems


def test_planted_short_sha_is_refused() -> None:
    pyproject_text, lock_text = _repo_texts()
    live = _source_rev(pyproject_text)
    skewed = _DEPENDENCY_PIN.sub(
        lambda m: m.group(0).replace(live, live[:12]), pyproject_text
    )
    assert skewed != pyproject_text
    problems = skew_problems(skewed, lock_text)
    assert any("exactly one git dependency" in p for p in problems), problems
