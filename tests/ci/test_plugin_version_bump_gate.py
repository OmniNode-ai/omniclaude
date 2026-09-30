# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-16913: a change under plugins/onex needs a plugin version bump.

The Claude Code plugin cache is keyed on the manifest ``version``, so a content
edit that lands without a bump never reaches an installed cache (``claude plugin
update`` reports already-latest). On 2026-09-30 the onex cache was 2.3.2 from
2026-08-29 and differed from the tree by ~180 files.

Each test builds a throwaway git repo so the gate is exercised against a real
merge base, with a known-positive (must fail) and a known-negative (must pass).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from scripts.validation import validate_plugin_version_bump as gate  # noqa: E402

PLUGIN_JSON = "plugins/onex/.claude-plugin/plugin.json"
MARKETPLACE_JSON = "plugins/onex-dev-marketplace/.claude-plugin/marketplace.json"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        env={
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.com",
            "PATH": "/usr/bin:/bin:/opt/homebrew/bin",
            "HOME": str(repo),
        },
    ).stdout


def _write_versions(repo: Path, plugin: str, marketplace: str | None = None) -> None:
    (repo / PLUGIN_JSON).parent.mkdir(parents=True, exist_ok=True)
    (repo / MARKETPLACE_JSON).parent.mkdir(parents=True, exist_ok=True)
    (repo / PLUGIN_JSON).write_text(json.dumps({"name": "onex", "version": plugin}))
    (repo / MARKETPLACE_JSON).write_text(
        json.dumps({"plugins": [{"name": "onex", "version": marketplace or plugin}]})
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q", "-b", "dev")
    _write_versions(tmp_path, "1.0.0")
    (tmp_path / "plugins/onex/skills/a").mkdir(parents=True)
    (tmp_path / "plugins/onex/skills/a/SKILL.md").write_text("one\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "base")
    _git(tmp_path, "checkout", "-q", "-b", "feature")
    return tmp_path


def _commit(repo: Path) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "change")


@pytest.mark.unit
def test_content_change_without_bump_fails(repo: Path) -> None:
    (repo / "plugins/onex/skills/a/SKILL.md").write_text("two\n")
    _commit(repo)
    findings = gate.check(repo, "dev")
    assert [f.kind for f in findings] == ["NO_BUMP"]
    assert "plugins/onex/skills/a/SKILL.md" in findings[0].detail


@pytest.mark.unit
def test_content_change_with_bump_passes(repo: Path) -> None:
    (repo / "plugins/onex/skills/a/SKILL.md").write_text("two\n")
    _write_versions(repo, "1.0.1")
    _commit(repo)
    assert gate.check(repo, "dev") == []


@pytest.mark.unit
def test_change_outside_the_plugin_needs_no_bump(repo: Path) -> None:
    (repo / "README.md").write_text("x\n")
    _commit(repo)
    assert gate.check(repo, "dev") == []


@pytest.mark.unit
def test_plugin_tests_and_bytecode_need_no_bump(repo: Path) -> None:
    (repo / "plugins/onex/tests").mkdir()
    (repo / "plugins/onex/tests/test_x.py").write_text("x\n")
    (repo / "plugins/onex/hooks/lib/__pycache__").mkdir(parents=True)
    (repo / "plugins/onex/hooks/lib/__pycache__/x.pyc").write_text("x\n")
    _commit(repo)
    assert gate.check(repo, "dev") == []


@pytest.mark.unit
def test_bump_that_does_not_increase_fails(repo: Path) -> None:
    (repo / "plugins/onex/skills/a/SKILL.md").write_text("two\n")
    _commit(repo)
    _write_versions(repo, "0.9.9")
    _commit(repo)
    assert [f.kind for f in gate.check(repo, "dev")] == ["NO_BUMP"]


@pytest.mark.unit
def test_version_compare_is_numeric_not_lexical(repo: Path) -> None:
    _write_versions(repo, "1.0.9")
    _commit(repo)
    _git(repo, "checkout", "-q", "dev")
    _git(repo, "merge", "-q", "--ff-only", "feature")
    _git(repo, "checkout", "-q", "-b", "f2")
    (repo / "plugins/onex/skills/a/SKILL.md").write_text("two\n")
    _write_versions(repo, "1.0.10")
    _commit(repo)
    assert gate.check(repo, "dev") == []


@pytest.mark.unit
def test_marketplace_version_must_match_plugin(repo: Path) -> None:
    (repo / "plugins/onex/skills/a/SKILL.md").write_text("two\n")
    _write_versions(repo, "1.0.1", marketplace="1.0.0")
    _commit(repo)
    assert [f.kind for f in gate.check(repo, "dev")] == ["MARKETPLACE_SKEW"]


@pytest.mark.unit
def test_uncommitted_changes_count_for_the_precommit_run(repo: Path) -> None:
    (repo / "plugins/onex/skills/a/SKILL.md").write_text("two\n")
    _git(repo, "add", "-A")
    assert [f.kind for f in gate.check(repo, "dev")] == ["NO_BUMP"]


@pytest.mark.unit
def test_unresolvable_base_is_an_error_not_a_pass(repo: Path) -> None:
    with pytest.raises(gate.GateError):
        gate.check(repo, "no-such-ref")


@pytest.mark.unit
def test_real_repo_manifests_agree() -> None:
    """The committed plugin.json and dev marketplace.json never disagree."""
    assert gate.marketplace_skew(REPO_ROOT) == []
