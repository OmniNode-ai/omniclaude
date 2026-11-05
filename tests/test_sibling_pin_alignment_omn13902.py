# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-13902: the omnimarket git tag is one dev-merge tag on every surface (OMN-21900).

The sibling-lock refresh advances a clone-governed git source forward only, and
rewrites the dependency occurrence and the source occurrence together. These
tests read the three places a tag lives -- the dependency line, the
``[tool.uv.sources]`` entry and ``uv.lock`` -- and refuse a refresh that moved
one and left another behind.

The alignment check is a function of file text, so each test that reads the
repo's own files is paired with a planted-skew case that proves the same check
refuses a skewed copy. A check that has only ever seen the aligned tree has not
shown it can fail.

The installed sibling also preserves complete Git output for plan parsing while
keeping human-facing command reports truncated. That regression fails with the
pre-refresh dependency even when its pins agree with one another.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[1]
_TAG = re.compile(r"dev-[0-9]{14}-[0-9a-f]{12}")
_DEPENDENCY_PIN = re.compile(
    r'"omnimarket @ git\+https://github\.com/OmniNode-ai/omnimarket\.git@(dev-[0-9]{14}-[0-9a-f]{12})"'
)
_SOURCE_PIN = re.compile(
    r'^omnimarket = \{ git = "[^"]+", tag = "(dev-[0-9]{14}-[0-9a-f]{12})" \}',
    flags=re.MULTILINE,
)
_LOCK_PIN = re.compile(r"omnimarket\.git\?tag=(dev-[0-9]{14}-[0-9a-f]{12})")

# A dev-merge tag that is no tag omnimarket has ever carried: every planted skew
# below moves exactly one surface onto it.
_PLANTED_REV = "dev-20000101000000-0123456789ab"


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
            f"omnimarket must have exactly one [tool.uv.sources] tag, found {len(source)}"
        )
    if len(dependency) == 1 and len(source) == 1 and dependency[0] != source[0]:
        problems.append(
            f"dependency tag {dependency[0]} differs from source tag {source[0]}"
        )
    locked = set(_LOCK_PIN.findall(lock_text))
    if len(source) == 1 and locked != {source[0]}:
        problems.append(
            f"uv.lock resolves omnimarket at {sorted(locked)}, not the source tag {source[0]}"
        )
    return problems


def _repo_texts() -> tuple[str, str]:
    return (
        (_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"),
        (_REPO_ROOT / "uv.lock").read_text(encoding="utf-8"),
    )


def _source_rev(pyproject_text: str) -> str:
    match = _SOURCE_PIN.search(pyproject_text)
    assert match is not None
    return match.group(1)


def test_omnimarket_tag_is_one_dev_merge_tag_on_every_surface() -> None:
    pyproject_text, lock_text = _repo_texts()
    assert skew_problems(pyproject_text, lock_text) == []
    assert _TAG.fullmatch(_source_rev(pyproject_text))


def test_planted_source_skew_is_refused() -> None:
    pyproject_text, lock_text = _repo_texts()
    live = _source_rev(pyproject_text)
    skewed = _SOURCE_PIN.sub(
        lambda m: m.group(0).replace(live, _PLANTED_REV), pyproject_text
    )
    assert skewed != pyproject_text
    problems = skew_problems(skewed, lock_text)
    assert any("differs from source tag" in p for p in problems), problems


def test_planted_lock_skew_is_refused() -> None:
    pyproject_text, lock_text = _repo_texts()
    live = _source_rev(pyproject_text)
    skewed = lock_text.replace(
        f"omnimarket.git?tag={live}", f"omnimarket.git?tag={_PLANTED_REV}"
    )
    assert skewed != lock_text
    problems = skew_problems(pyproject_text, skewed)
    assert any("uv.lock resolves omnimarket" in p for p in problems), problems


def test_planted_truncated_tag_is_refused() -> None:
    pyproject_text, lock_text = _repo_texts()
    live = _source_rev(pyproject_text)
    skewed = _DEPENDENCY_PIN.sub(
        lambda m: m.group(0).replace(live, live[:20]), pyproject_text
    )
    assert skewed != pyproject_text
    problems = skew_problems(skewed, lock_text)
    assert any("exactly one git dependency" in p for p in problems), problems


def test_refreshed_git_parser_retains_older_plan_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The installed sibling must retain records beyond its report tail limit."""
    from omnimarket.nodes.node_morning_ground_state_orchestrator.tools.base import (
        _git,
        _git_out,
    )

    # Hooks export Git locations that otherwise override this isolated index.
    env = os.environ.copy()
    for name in (
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_INDEX_FILE",
        "GIT_COMMON_DIR",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_CEILING_DIRECTORIES",
        "GIT_NAMESPACE",
    ):
        env.pop(name, None)
        monkeypatch.delenv(name, raising=False)
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, env=env)
    plans = tmp_path / "plans"
    plans.mkdir()
    expected = [
        f"plans/2026-01-01-{index:04d}-older-plan-with-a-long-title.md"
        for index in range(160)
    ]
    for path in expected:
        (tmp_path / path).write_text("plan\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "plans"], check=True, env=env)

    parsed = _git_out(tmp_path, "ls-files", "--", "plans")
    report = _git(tmp_path, "ls-files", "--", "plans")

    assert parsed is not None
    assert len(parsed) > 4000
    assert parsed.splitlines() == expected
    assert expected[0] not in str(report["stdout"])
    assert str(report["stdout"]).endswith(expected[-1] + "\n")
