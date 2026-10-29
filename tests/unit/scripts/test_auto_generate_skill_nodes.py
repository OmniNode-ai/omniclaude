# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for scripts/auto_generate_skill_nodes.py."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.auto_generate_skill_nodes import find_skills_missing_nodes, main


@pytest.fixture
def fake_repo(tmp_path: Path) -> Path:
    """Build a minimal fake repo layout with skills and nodes dirs."""
    skills_dir = tmp_path / "plugins" / "onex" / "skills"
    nodes_dir = tmp_path / "src" / "omniclaude" / "nodes"
    skills_dir.mkdir(parents=True)
    nodes_dir.mkdir(parents=True)
    return tmp_path


def _add_skill(repo: Path, name: str) -> None:
    """Create a skill directory with SKILL.md."""
    skill_dir = repo / "plugins" / "onex" / "skills" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\ndescription: Test skill {name}\nlevel: basic\ndebug: false\n---\n",
        encoding="utf-8",
    )


def _add_node(repo: Path, skill_name: str) -> None:
    """Create a node directory for a skill."""
    snake = skill_name.replace("-", "_")
    node_dir = (
        repo / "src" / "omniclaude" / "nodes" / f"node_skill_{snake}_orchestrator"
    )
    node_dir.mkdir(parents=True, exist_ok=True)
    (node_dir / "contract.yaml").write_text("name: stub\n", encoding="utf-8")


@pytest.mark.unit
def test_no_missing_nodes(fake_repo: Path) -> None:
    """Returns empty list when all skills have nodes."""
    _add_skill(fake_repo, "local-review")
    _add_node(fake_repo, "local-review")

    with (
        patch(
            "scripts.auto_generate_skill_nodes._SKILLS_DIR",
            fake_repo / "plugins" / "onex" / "skills",
        ),
        patch(
            "scripts.auto_generate_skill_nodes._NODES_DIR",
            fake_repo / "src" / "omniclaude" / "nodes",
        ),
    ):
        result = find_skills_missing_nodes()

    assert result == []


@pytest.mark.unit
def test_detects_missing_node(fake_repo: Path) -> None:
    """Returns skill names that are missing orchestrator nodes."""
    _add_skill(fake_repo, "local-review")
    _add_skill(fake_repo, "hostile-reviewer")
    _add_node(fake_repo, "local-review")
    # hostile-reviewer has no node

    with (
        patch(
            "scripts.auto_generate_skill_nodes._SKILLS_DIR",
            fake_repo / "plugins" / "onex" / "skills",
        ),
        patch(
            "scripts.auto_generate_skill_nodes._NODES_DIR",
            fake_repo / "src" / "omniclaude" / "nodes",
        ),
    ):
        result = find_skills_missing_nodes()

    assert result == ["hostile-reviewer"]


@pytest.mark.unit
def test_skips_underscore_dirs(fake_repo: Path) -> None:
    """Directories starting with _ are skipped (shared/lib helpers)."""
    _add_skill(fake_repo, "_shared")
    _add_skill(fake_repo, "local-review")
    _add_node(fake_repo, "local-review")

    with (
        patch(
            "scripts.auto_generate_skill_nodes._SKILLS_DIR",
            fake_repo / "plugins" / "onex" / "skills",
        ),
        patch(
            "scripts.auto_generate_skill_nodes._NODES_DIR",
            fake_repo / "src" / "omniclaude" / "nodes",
        ),
    ):
        result = find_skills_missing_nodes()

    assert result == []


@pytest.mark.unit
def test_skips_dirs_without_skill_md(fake_repo: Path) -> None:
    """Directories without SKILL.md are not considered skills."""
    # Create dir without SKILL.md
    (fake_repo / "plugins" / "onex" / "skills" / "orphan-dir").mkdir(parents=True)
    _add_skill(fake_repo, "local-review")
    _add_node(fake_repo, "local-review")

    with (
        patch(
            "scripts.auto_generate_skill_nodes._SKILLS_DIR",
            fake_repo / "plugins" / "onex" / "skills",
        ),
        patch(
            "scripts.auto_generate_skill_nodes._NODES_DIR",
            fake_repo / "src" / "omniclaude" / "nodes",
        ),
    ):
        result = find_skills_missing_nodes()

    assert result == []


@pytest.mark.unit
def test_main_returns_zero_when_no_missing(fake_repo: Path) -> None:
    """main() exits 0 when all skills have nodes."""
    _add_skill(fake_repo, "local-review")
    _add_node(fake_repo, "local-review")

    with (
        patch(
            "scripts.auto_generate_skill_nodes._SKILLS_DIR",
            fake_repo / "plugins" / "onex" / "skills",
        ),
        patch(
            "scripts.auto_generate_skill_nodes._NODES_DIR",
            fake_repo / "src" / "omniclaude" / "nodes",
        ),
        patch("scripts.auto_generate_skill_nodes._REPO_ROOT", fake_repo),
    ):
        assert main() == 0


def _tree_snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


@pytest.mark.unit
def test_check_refuses_a_missing_node_and_writes_nothing(
    fake_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """T2.6 (OMN-21499): `--check` names the missing node and generates nothing."""
    _add_skill(fake_repo, "hostile-reviewer")  # no node
    before = _tree_snapshot(fake_repo)

    with (
        patch(
            "scripts.auto_generate_skill_nodes._SKILLS_DIR",
            fake_repo / "plugins" / "onex" / "skills",
        ),
        patch(
            "scripts.auto_generate_skill_nodes._NODES_DIR",
            fake_repo / "src" / "omniclaude" / "nodes",
        ),
        patch("scripts.auto_generate_skill_nodes._REPO_ROOT", fake_repo),
        patch("scripts.auto_generate_skill_nodes.subprocess.run") as run,
    ):
        assert main(["--check"]) == 1

    run.assert_not_called()  # neither generate_skill_node.py nor `git add`
    assert _tree_snapshot(fake_repo) == before
    err = capsys.readouterr().err
    assert "hostile-reviewer" in err
    assert "generate_skill_node.py hostile-reviewer" in err


@pytest.mark.unit
def test_check_accepts_a_tree_with_every_node(fake_repo: Path) -> None:
    """Positive control for the refusal above."""
    _add_skill(fake_repo, "local-review")
    _add_node(fake_repo, "local-review")

    with (
        patch(
            "scripts.auto_generate_skill_nodes._SKILLS_DIR",
            fake_repo / "plugins" / "onex" / "skills",
        ),
        patch(
            "scripts.auto_generate_skill_nodes._NODES_DIR",
            fake_repo / "src" / "omniclaude" / "nodes",
        ),
        patch("scripts.auto_generate_skill_nodes._REPO_ROOT", fake_repo),
    ):
        assert main(["--check"]) == 0


@pytest.mark.unit
def test_bootstrap_skill_is_not_listed_as_missing_a_node(fake_repo: Path) -> None:
    """A skill that declares bootstrap: true gets no generated node."""
    _add_skill(fake_repo, "plain-skill")
    boot = fake_repo / "plugins" / "onex" / "skills" / "boot-skill"
    boot.mkdir(parents=True)
    (boot / "SKILL.md").write_text(
        "---\ndescription: Bootstrap skill\nbootstrap: true\n---\n", encoding="utf-8"
    )
    quoted = fake_repo / "plugins" / "onex" / "skills" / "quoted-skill"
    quoted.mkdir(parents=True)
    (quoted / "SKILL.md").write_text(
        '---\ndescription: x\nbootstrap: "true"\n---\n', encoding="utf-8"
    )

    with (
        patch(
            "scripts.auto_generate_skill_nodes._SKILLS_DIR",
            fake_repo / "plugins" / "onex" / "skills",
        ),
        patch(
            "scripts.auto_generate_skill_nodes._NODES_DIR",
            fake_repo / "src" / "omniclaude" / "nodes",
        ),
    ):
        assert find_skills_missing_nodes() == ["plain-skill", "quoted-skill"]
