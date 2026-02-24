# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Unit tests for scripts/generate_skill_node.py.

Tests the snake_to_pascal conversion function and the dry-run output of the
generate_node_for_skill function.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from scripts.generate_skill_node import (
    generate_node_for_skill,
    kebab_to_snake,
    render_template,
    snake_to_pascal,
)

# ---------------------------------------------------------------------------
# snake_to_pascal tests (4 required by ticket)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_snake_to_pascal_single_word() -> None:
    """Single-word input should capitalize the first letter only."""
    assert snake_to_pascal("review") == "Review"


@pytest.mark.unit
def test_snake_to_pascal_multi_word() -> None:
    """Two-word snake_case should produce two-part PascalCase."""
    assert snake_to_pascal("local_review") == "LocalReview"


@pytest.mark.unit
def test_snake_to_pascal_ci_fix_pipeline() -> None:
    """Three-segment name including an acronym-like prefix."""
    assert snake_to_pascal("ci_fix_pipeline") == "CiFixPipeline"


@pytest.mark.unit
def test_snake_to_pascal_pr_release_ready() -> None:
    """Three-segment name starting with a two-letter prefix."""
    assert snake_to_pascal("pr_release_ready") == "PrReleaseReady"


# ---------------------------------------------------------------------------
# kebab_to_snake tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_kebab_to_snake_basic() -> None:
    assert kebab_to_snake("local-review") == "local_review"


@pytest.mark.unit
def test_kebab_to_snake_ci_fix() -> None:
    assert kebab_to_snake("ci-fix-pipeline") == "ci_fix_pipeline"


@pytest.mark.unit
def test_kebab_to_snake_no_hyphens() -> None:
    assert kebab_to_snake("review") == "review"


# ---------------------------------------------------------------------------
# render_template tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_render_template_substitutes_all_placeholders() -> None:
    template = "Name: SKILL_NAME, Snake: SKILL_NAME_SNAKE, Desc: SKILL_DESCRIPTION, Date: CREATED_DATE"
    result = render_template(
        template,
        {
            "SKILL_NAME": "local-review",
            "SKILL_NAME_SNAKE": "local_review",
            "SKILL_DESCRIPTION": "Reviews code locally.",
            "CREATED_DATE": "2026-02-24",
        },
    )
    assert (
        result
        == "Name: local-review, Snake: local_review, Desc: Reviews code locally., Date: 2026-02-24"
    )


@pytest.mark.unit
def test_render_template_no_placeholders() -> None:
    template = "No placeholders here."
    assert render_template(template, {"SKILL_NAME": "x"}) == "No placeholders here."


# ---------------------------------------------------------------------------
# dry-run integration tests (filesystem fixture)
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_repo(tmp_path: Path) -> Path:
    """Build a minimal fake repository layout for script testing."""
    # Skills directory with one skill
    skill_dir = tmp_path / "plugins" / "onex" / "skills" / "local-review"
    skill_dir.mkdir(parents=True)
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(
        textwrap.dedent(
            """\
            ---
            name: local-review
            description: Local code review loop that iterates through review, fix, commit cycles
            version: 2.0.0
            ---
            # Body content here
            """
        ),
        encoding="utf-8",
    )

    # Template file
    template_dir = tmp_path / "docs" / "templates"
    template_dir.mkdir(parents=True)
    template = template_dir / "skill_node_contract.yaml.template"
    template.write_text(
        textwrap.dedent(
            """\
            name: node_skill_SKILL_NAME_SNAKE_orchestrator
            skill: SKILL_NAME
            description: SKILL_DESCRIPTION
            created: CREATED_DATE
            """
        ),
        encoding="utf-8",
    )

    # src/omniclaude/nodes directory (no existing node for local-review)
    nodes_dir = tmp_path / "src" / "omniclaude" / "nodes"
    nodes_dir.mkdir(parents=True)

    return tmp_path


@pytest.mark.unit
def test_dry_run_prints_three_would_create_lines(
    fake_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Dry run for a single skill must print exactly 3 '[DRY RUN] Would create:' lines."""
    result = generate_node_for_skill("local-review", repo_root=fake_repo, dry_run=True)
    assert result is True

    captured = capsys.readouterr()
    dry_run_lines = [
        line for line in captured.out.splitlines() if "[DRY RUN] Would create:" in line
    ]
    assert len(dry_run_lines) == 3, (
        f"Expected 3 '[DRY RUN] Would create:' lines, got {len(dry_run_lines)}:\n{captured.out}"
    )


@pytest.mark.unit
def test_dry_run_does_not_create_files(fake_repo: Path) -> None:
    """Dry run must not write any files to disk."""
    node_dir = (
        fake_repo
        / "src"
        / "omniclaude"
        / "nodes"
        / "node_skill_local_review_orchestrator"
    )
    assert not node_dir.exists()

    generate_node_for_skill("local-review", repo_root=fake_repo, dry_run=True)

    assert not node_dir.exists()


@pytest.mark.unit
def test_generate_creates_three_files(fake_repo: Path) -> None:
    """Non-dry-run must create __init__.py, node.py, and contract.yaml."""
    result = generate_node_for_skill("local-review", repo_root=fake_repo, dry_run=False)
    assert result is True

    node_dir = (
        fake_repo
        / "src"
        / "omniclaude"
        / "nodes"
        / "node_skill_local_review_orchestrator"
    )
    assert (node_dir / "__init__.py").exists()
    assert (node_dir / "node.py").exists()
    assert (node_dir / "contract.yaml").exists()


@pytest.mark.unit
def test_generate_skips_existing_node(
    fake_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Second invocation must skip and return False when node dir already exists."""
    generate_node_for_skill("local-review", repo_root=fake_repo, dry_run=False)
    result = generate_node_for_skill("local-review", repo_root=fake_repo, dry_run=False)
    assert result is False

    captured = capsys.readouterr()
    assert "[SKIP]" in captured.out


@pytest.mark.unit
def test_generated_contract_no_requested_suffix(fake_repo: Path) -> None:
    """Generated contract.yaml must not contain '-requested' in any topic name."""
    generate_node_for_skill("local-review", repo_root=fake_repo, dry_run=False)
    node_dir = (
        fake_repo
        / "src"
        / "omniclaude"
        / "nodes"
        / "node_skill_local_review_orchestrator"
    )
    contract_text = (node_dir / "contract.yaml").read_text(encoding="utf-8")
    assert "-requested" not in contract_text


@pytest.mark.unit
def test_generated_contract_no_env_prefix(fake_repo: Path) -> None:
    """Generated contract.yaml must not contain an '{env}.' prefix in topic names."""
    generate_node_for_skill("local-review", repo_root=fake_repo, dry_run=False)
    node_dir = (
        fake_repo
        / "src"
        / "omniclaude"
        / "nodes"
        / "node_skill_local_review_orchestrator"
    )
    contract_text = (node_dir / "contract.yaml").read_text(encoding="utf-8")
    # Topics should not contain {env}. prefix pattern
    assert "{env}." not in contract_text
