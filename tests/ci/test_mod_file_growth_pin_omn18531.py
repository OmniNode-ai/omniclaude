# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""OMN-18531: the canonical-file-shape pin carries the mod-file-growth rule.

Operator ruling 2026-10-15T08:14:15Z: canonical shapes for all mod work. omnibase_core
d7ed23f1 refuses a baselined script under ``plugins/``, ``.claude/`` or a ``hooks/``
directory that gains code lines. The rule binds here only while the pre-commit hook and the
CI job run core at a commit carrying it, so this test runs the pinned validator against a
planted growth (refused) and a comment-only edit (accepted).
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
CORE_URL = "https://github.com/OmniNode-ai/omnibase_core"
MOD_SCRIPT = "plugins/onex/hooks/lib/hook_planted.py"
# Git exports these into a hook's environment; they override cwd and -C.
_GIT_LOCATION_VARS = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_CEILING_DIRECTORIES",
    "GIT_NAMESPACE",
)


def scrub_git_location_env(env: Mapping[str, str]) -> dict[str, str]:
    return {k: v for k, v in env.items() if k not in _GIT_LOCATION_VARS}


def _hook_pin() -> str:
    config = yaml.safe_load(
        (ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    )
    (rev,) = {
        repo["rev"]
        for repo in config["repos"]
        if repo["repo"] == CORE_URL
        and any(hook["id"] == "canonical-file-shape" for hook in repo["hooks"])
    }
    return rev


def _ci_pin() -> str:
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    )
    spec = workflow["jobs"]["canonical-file-shape"]["env"]["CANONICAL_FILE_SHAPE_CORE"]
    return spec.rsplit("@", 1)[1]


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        env=scrub_git_location_env(os.environ),
    )


def _ratchet(repo: Path, rev: str, base: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "uv",
            "run",
            "--no-project",
            "--with",
            f"omnibase-core @ git+{CORE_URL}@{rev}",
            "python",
            "-m",
            "omnibase_core.nodes.node_canonical_file_shape_check_compute.runtime_canonical_file_shape_check",
            "--rules",
            "file-shape",
            "--base",
            base,
            "--head",
            "HEAD",
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
        env=scrub_git_location_env(os.environ),
    )


@pytest.fixture
def planted_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    script = repo / MOD_SCRIPT
    script.parent.mkdir(parents=True)
    script.write_text("x = 1\n", encoding="utf-8")
    baseline = repo / ".onex_ratchets/canonical_file_shape_baseline.txt"
    baseline.parent.mkdir()
    baseline.write_text(f"{MOD_SCRIPT}\n", encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "t")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    base = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        env=scrub_git_location_env(os.environ),
    ).stdout.strip()
    return repo, base


def test_hook_and_ci_run_the_same_shape_commit() -> None:
    assert _hook_pin() == _ci_pin()


def test_pinned_ratchet_refuses_code_growth_in_a_baselined_mod_script(
    planted_repo: tuple[Path, str],
) -> None:
    repo, base = planted_repo
    with (repo / MOD_SCRIPT).open("a", encoding="utf-8") as handle:
        handle.write("y = 2\n")
    _git(repo, "commit", "-q", "-am", "grow")
    result = _ratchet(repo, _hook_pin(), base)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "[baselined-file-growth]" in result.stdout + result.stderr


def test_pinned_ratchet_accepts_comment_growth_in_a_baselined_mod_script(
    planted_repo: tuple[Path, str],
) -> None:
    repo, base = planted_repo
    with (repo / MOD_SCRIPT).open("a", encoding="utf-8") as handle:
        handle.write("# a comment\n")
    _git(repo, "commit", "-q", "-am", "comment")
    result = _ratchet(repo, _hook_pin(), base)
    assert result.returncode == 0, result.stdout + result.stderr
