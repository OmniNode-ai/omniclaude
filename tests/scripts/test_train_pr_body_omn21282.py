# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-21282 AC1: the nightly train opens one pin-bump PR body per consumer.

RULING 2026-10-19T10:11:00Z: "turn this into a nightly release train where all
the tags are rolled up to a single bump". The train script renders the one PR
body the night's bump opens with. Over a fixture of three new dev tags it is one
body, it names every tag the bump rolls in, and the pin lands on the newest.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from omnibase_core.validators.no_unguarded_git_subprocess import scrub_git_location_env

pytestmark = pytest.mark.unit

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
_CORE_URL = "https://github.com/OmniNode-ai/omnibase_core.git"


@pytest.fixture
def mod():
    sys.path.insert(0, str(_SCRIPTS))
    try:
        import relock_git_sources

        yield relock_git_sources
    finally:
        sys.path.remove(str(_SCRIPTS))


def _git(cwd: Path, *args: str) -> str:
    identity = ["-c", "user.name=t", "-c", "user.email=t@example.invalid"]
    return subprocess.run(
        ["git", "-C", str(cwd), *identity, *args],
        check=True,
        capture_output=True,
        text=True,
        env=scrub_git_location_env(os.environ),
    ).stdout.strip()


def _clone_with_tags(root: Path, repo: str, stamps: list[str]) -> list[str]:
    clone = root / repo
    clone.mkdir(parents=True)
    _git(clone, "init", "-q", "-b", "dev")
    tags: list[str] = []
    for stamp in stamps:
        (clone / "f").write_text(stamp)
        _git(clone, "add", "f")
        _git(clone, "commit", "-q", "-m", stamp)
        tag = f"dev-{stamp}-{_git(clone, 'rev-parse', 'HEAD')[:12]}"
        _git(clone, "tag", tag)
        tags.append(tag)
    return tags


def test_three_new_dev_tags_roll_into_one_pr_body(mod, tmp_path: Path) -> None:
    clones = tmp_path / "clones"
    pinned, *new = _clone_with_tags(
        clones,
        "omnibase_core",
        ["20261019000000", "20261019010000", "20261019020000", "20261019030000"],
    )
    assert len(new) == 3
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "consumer"\nversion = "0.0.0"\n'
        'dependencies = ["omnibase-core>=0.47.0"]\n\n[tool.uv.sources]\n'
        f'omnibase-core = {{ git = "{_CORE_URL}", tag = "{pinned}" }}\n'
    )

    def mover(path: Path, pin, new_tag: str) -> None:
        path.write_text(path.read_text().replace(pin.tag, new_tag))

    plan = mod.run_dev_tag_train(
        pyproject=pyproject,
        registry_root=str(clones),
        is_green=lambda r, s: True,
        mover=mover,
        apply=True,
    )
    [move] = plan.moves
    assert move.new_tag == new[-1]
    assert move.rolled == list(reversed(new))

    body = mod.render_pr_body(plan)
    assert isinstance(body, str)
    assert body.count("omnibase-core") == 1, "one bump line per sibling"
    for tag in new:
        assert tag in body, f"{tag} is rolled into the bump but not named"
    assert new[-1] in pyproject.read_text()


def test_body_out_writes_the_one_body(mod, tmp_path: Path, monkeypatch) -> None:
    clones = tmp_path / "clones"
    pinned, *new = _clone_with_tags(
        clones, "omnibase_core", ["20261019000000", "20261019010000"]
    )
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "consumer"\nversion = "0.0.0"\n\n[tool.uv.sources]\n'
        f'omnibase-core = {{ git = "{_CORE_URL}", tag = "{pinned}" }}\n'
    )
    body_out = tmp_path / "body.md"
    rc = mod.main(
        [
            "--dev-tag-train",
            "--repo-root",
            str(repo),
            "--registry-root",
            str(clones),
            "--green-from",
            "none",
            "--body-out",
            str(body_out),
        ]
    )
    assert rc == 0
    body = body_out.read_text()
    # --green-from none reads no CI, so the tag is passed over and named so.
    assert "no sibling moved" in body
    assert new[0] in body


def test_empty_plan_renders_a_body_that_says_nothing_moved(mod) -> None:
    plan = mod.ModelTrainPlan(moves=[], unchanged=["omnibase-core"], skipped={})
    assert "no sibling moved" in mod.render_pr_body(plan)
