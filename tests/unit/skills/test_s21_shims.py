# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for S21 tier-2 dispatch-only shims (OMN-8768).

Validates that each skill shim contains no inline logic and dispatches
through the manifest-canonical onex run-node path.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

SKILLS_DIR = Path(__file__).resolve().parents[3] / "plugins" / "onex" / "skills"


def _skill_dir(name: str) -> Path:
    return SKILLS_DIR / name


def _read_skill(name: str) -> str:
    return (_skill_dir(name) / "SKILL.md").read_text()


def _read_prompt(name: str) -> str:
    return (_skill_dir(name) / "prompt.md").read_text()


def _frontmatter(content: str) -> dict:
    parts = content.split("---", 2)
    assert len(parts) >= 3, "Frontmatter not properly delimited"
    return yaml.safe_load(parts[1])


def _assert_thin_skill(name: str, node: str, cmd_topic: str) -> None:
    """Common assertions for all dispatch-only shims."""
    content = _read_skill(name)
    fm = _frontmatter(content)

    assert fm.get("description"), f"{name}: description required"
    tags = fm.get("tags", [])
    assert "dispatch-only" in tags, f"{name}: missing dispatch-only tag"
    assert "routing-enforced" in tags, f"{name}: missing routing-enforced tag"

    assert node in content, f"{name}: missing backing node reference {node}"
    assert f"onex run-node {node}" in content, f"{name}: missing dispatch command"
    assert cmd_topic in content, f"{name}: missing command topic"


def _assert_thin_prompt(name: str, node: str) -> None:
    """Common assertions for dispatch-only prompt.md files."""
    content = _read_prompt(name)

    assert "Announce" in content, f"{name}: prompt missing Announce section"
    assert f"onex run-node {node}" in content, f"{name}: prompt missing dispatch"
    assert (
        "SkillRoutingError" in content
        or "do not produce prose" in content.lower()
        or "stop" in content.lower()
    ), f"{name}: prompt must declare error handling"

    # No inline agent spawning
    assert "Agent(" not in content, f"{name}: prompt must not spawn Agent()"
    assert "TeamCreate" not in content, f"{name}: prompt must not call TeamCreate"

    # No LLM SDK imports
    assert "import anthropic" not in content, f"{name}: no LLM SDK imports"
    assert "import openai" not in content, f"{name}: no LLM SDK imports"

    # Prompt must be thin
    line_count = len(content.splitlines())
    assert line_count <= 100, (
        f"{name}: prompt exceeds 100 lines ({line_count}). Move logic to backing node."
    )


# ─── coderabbit_triage ────────────────────────────────────────────────────────


@pytest.mark.unit
class TestCoderabbitTriageShim:
    def test_skill_md_exists(self) -> None:
        assert (_skill_dir("coderabbit_triage") / "SKILL.md").is_file()

    def test_skill_md_thin(self) -> None:
        _assert_thin_skill(
            "coderabbit_triage",
            "node_coderabbit_triage",
            "onex.cmd.omnimarket.coderabbit-triage-start.v1",
        )

    def test_prompt_md_thin(self) -> None:
        _assert_thin_prompt("coderabbit_triage", "node_coderabbit_triage")

    def test_skill_md_has_required_args(self) -> None:
        fm = _frontmatter(_read_skill("coderabbit_triage"))
        arg_names = [a["name"] for a in fm["args"]]
        assert "repo" in arg_names
        assert "pr" in arg_names
        assert "--dry-run" in arg_names

    def test_skill_md_no_inline_gh_calls(self) -> None:
        content = _read_skill("coderabbit_triage")
        assert "gh pr comment" not in content
        assert "graphql" not in content.lower()


# ─── dod_verify ──────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestDodVerifyShim:
    def test_skill_md_exists(self) -> None:
        assert (_skill_dir("dod_verify") / "SKILL.md").is_file()

    def test_skill_md_thin(self) -> None:
        _assert_thin_skill(
            "dod_verify",
            "node_dod_verify",
            "onex.cmd.omnimarket.dod-verify-start.v1",
        )

    def test_prompt_md_thin(self) -> None:
        _assert_thin_prompt("dod_verify", "node_dod_verify")

    def test_skill_md_has_required_args(self) -> None:
        fm = _frontmatter(_read_skill("dod_verify"))
        arg_names = [a["name"] for a in fm["args"]]
        assert "ticket_id" in arg_names
        assert "--contract-path" in arg_names


# ─── doc_freshness_sweep ──────────────────────────────────────────────────────


@pytest.mark.unit
class TestDocFreshnessSweepShim:
    def test_skill_md_exists(self) -> None:
        assert (_skill_dir("doc_freshness_sweep") / "SKILL.md").is_file()

    def test_skill_md_thin(self) -> None:
        _assert_thin_skill(
            "doc_freshness_sweep",
            "node_doc_freshness_sweep",
            "onex.cmd.omnimarket.doc-freshness-sweep-start.v1",
        )

    def test_prompt_md_thin(self) -> None:
        _assert_thin_prompt("doc_freshness_sweep", "node_doc_freshness_sweep")

    def test_skill_md_has_required_args(self) -> None:
        fm = _frontmatter(_read_skill("doc_freshness_sweep"))
        arg_names = [a["name"] for a in fm["args"]]
        assert "--repo" in arg_names
        assert "--claude-md-only" in arg_names
        assert "--dry-run" in arg_names

    def test_prompt_md_no_inline_git_scanning(self) -> None:
        content = _read_prompt("doc_freshness_sweep")
        assert "git log --name-only" not in content
        assert "staleness_score" not in content


# ─── coverage_sweep ──────────────────────────────────────────────────────────


@pytest.mark.unit
class TestCoverageSweepShim:
    def test_skill_md_exists(self) -> None:
        assert (_skill_dir("coverage_sweep") / "SKILL.md").is_file()

    def test_skill_md_thin(self) -> None:
        _assert_thin_skill(
            "coverage_sweep",
            "node_coverage_sweep",
            "onex.cmd.omnimarket.coverage-sweep-start.v1",
        )

    def test_prompt_md_thin(self) -> None:
        _assert_thin_prompt("coverage_sweep", "node_coverage_sweep")

    def test_skill_md_has_required_args(self) -> None:
        fm = _frontmatter(_read_skill("coverage_sweep"))
        arg_names = [a["name"] for a in fm["args"]]
        assert "--repos" in arg_names
        assert "--target" in arg_names
        assert "--dry-run" in arg_names

    def test_prompt_md_no_inline_pytest(self) -> None:
        content = _read_prompt("coverage_sweep")
        assert "pytest --cov" not in content
        assert "coverage run" not in content


# ─── database_sweep ──────────────────────────────────────────────────────────


@pytest.mark.unit
class TestDatabaseSweepShim:
    def test_skill_md_exists(self) -> None:
        assert (_skill_dir("database_sweep") / "SKILL.md").is_file()

    def test_skill_md_thin(self) -> None:
        _assert_thin_skill(
            "database_sweep",
            "node_database_sweep",
            "onex.cmd.omnimarket.database-sweep-start.v1",
        )

    def test_prompt_md_thin(self) -> None:
        _assert_thin_prompt("database_sweep", "node_database_sweep")

    def test_skill_md_has_required_args(self) -> None:
        fm = _frontmatter(_read_skill("database_sweep"))
        arg_names = [a["name"] for a in fm["args"]]
        assert "--dry-run" in arg_names
        assert "--staleness-threshold" in arg_names

    def test_prompt_md_no_inline_psql(self) -> None:
        content = _read_prompt("database_sweep")
        assert "psql -c" not in content
        assert "psql -U" not in content
        assert "SELECT" not in content


# ─── duplication_sweep ────────────────────────────────────────────────────────


@pytest.mark.unit
class TestDuplicationSweepShim:
    def test_skill_md_exists(self) -> None:
        assert (_skill_dir("duplication_sweep") / "SKILL.md").is_file()

    def test_skill_md_thin(self) -> None:
        _assert_thin_skill(
            "duplication_sweep",
            "node_duplication_sweep",
            "onex.cmd.omnimarket.duplication-sweep-start.v1",
        )

    def test_prompt_md_thin(self) -> None:
        _assert_thin_prompt("duplication_sweep", "node_duplication_sweep")

    def test_prompt_md_no_inline_d1_d4_logic(self) -> None:
        content = _read_prompt("duplication_sweep")
        assert "pgTable(" not in content
        assert "base64 -d" not in content
        assert "gh api repos" not in content


# ─── auto_merge ──────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestAutoMergeShim:
    def test_skill_md_exists(self) -> None:
        assert (_skill_dir("auto_merge") / "SKILL.md").is_file()

    def test_skill_md_thin(self) -> None:
        _assert_thin_skill(
            "auto_merge",
            "node_auto_merge_effect",
            "onex.cmd.omnimarket.auto-merge-requested.v1",
        )

    def test_prompt_md_thin(self) -> None:
        _assert_thin_prompt("auto_merge", "node_auto_merge_effect")

    def test_skill_md_has_required_args(self) -> None:
        fm = _frontmatter(_read_skill("auto_merge"))
        arg_names = [a["name"] for a in fm["args"]]
        assert "pr_number" in arg_names
        assert "repo" in arg_names
        assert "--strategy" in arg_names
        assert "--gate-timeout-hours" in arg_names
        assert "--ticket-id" in arg_names

    def test_skill_md_no_inline_gh_merge(self) -> None:
        content = _read_skill("auto_merge")
        assert "gh pr merge --auto" not in content
        assert "gh pr merge --squash" not in content
        assert "gh pr merge --merge" not in content

    def test_prompt_md_no_inline_polling(self) -> None:
        content = _read_prompt("auto_merge")
        assert "mergeStateStatus" not in content
        assert "poll_interval" not in content
        assert "while True" not in content


# ─── pr_polish ────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestPrPolishShim:
    def test_skill_md_exists(self) -> None:
        assert (_skill_dir("pr_polish") / "SKILL.md").is_file()

    def test_skill_md_thin(self) -> None:
        _assert_thin_skill(
            "pr_polish",
            "node_pr_polish",
            "onex.cmd.omnimarket.pr-polish-start.v1",
        )

    def test_prompt_md_thin(self) -> None:
        _assert_thin_prompt("pr_polish", "node_pr_polish")

    def test_skill_md_has_required_args(self) -> None:
        fm = _frontmatter(_read_skill("pr_polish"))
        arg_names = [a["name"] for a in fm["args"]]
        assert "--required-clean-runs" in arg_names
        assert "--max-iterations" in arg_names
        assert "--skip-conflicts" in arg_names
        assert "--no-push" in arg_names
        assert "--dry-run" in arg_names

    def test_prompt_md_no_inline_phases(self) -> None:
        content = _read_prompt("pr_polish")
        assert "Phase 0" not in content
        assert "Phase 1" not in content
        assert "resolve_coderabbit_threads" not in content


# ─── pr_review ────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestPrReviewShim:
    def test_skill_md_exists(self) -> None:
        assert (_skill_dir("pr_review") / "SKILL.md").is_file()

    def test_skill_md_thin(self) -> None:
        _assert_thin_skill(
            "pr_review",
            "node_pr_review_bot",
            "onex.cmd.omnimarket.pr-review-bot-start.v1",
        )

    def test_prompt_md_thin(self) -> None:
        _assert_thin_prompt("pr_review", "node_pr_review_bot")

    def test_skill_md_has_required_args(self) -> None:
        fm = _frontmatter(_read_skill("pr_review"))
        arg_names = [a["name"] for a in fm["args"]]
        assert "pr_number" in arg_names
        assert "repo" in arg_names
        assert "--dry-run" in arg_names

    def test_skill_md_no_legacy_bash_scripts(self) -> None:
        content = _read_skill("pr_review")
        assert "pr-quick-review" not in content
        assert "collate-issues" not in content
        assert "review-pr" not in content
        assert "pr-review-production" not in content


# ─── hostile_reviewer ─────────────────────────────────────────────────────────


@pytest.mark.unit
class TestHostileReviewerShim:
    def test_skill_md_exists(self) -> None:
        assert (_skill_dir("hostile_reviewer") / "SKILL.md").is_file()

    def test_skill_md_thin(self) -> None:
        _assert_thin_skill(
            "hostile_reviewer",
            "node_hostile_reviewer",
            "onex.cmd.omnimarket.hostile-reviewer-start.v1",
        )

    def test_prompt_md_thin(self) -> None:
        _assert_thin_prompt("hostile_reviewer", "node_hostile_reviewer")

    def test_skill_md_has_required_args(self) -> None:
        fm = _frontmatter(_read_skill("hostile_reviewer"))
        arg_names = [a["name"] for a in fm["args"]]
        assert "pr" in arg_names
        assert "repo" in arg_names
        assert "static" in arg_names
        assert "gate" in arg_names

    def test_skill_md_disabled_notice(self) -> None:
        content = _read_skill("hostile_reviewer")
        assert "OMN-10111" in content
        assert "DISABLED" in content

    def test_skill_md_stderr_redirect_required(self) -> None:
        content = _read_skill("hostile_reviewer")
        assert "2>/dev/null" in content

    def test_prompt_md_no_inline_model_inference(self) -> None:
        content = _read_prompt("hostile_reviewer")
        assert "aggregate_reviews.py" not in content
        assert "codex" not in content.lower() or "model" in content.lower()


# ─── design_to_plan ───────────────────────────────────────────────────────────


@pytest.mark.unit
class TestDesignToPlanShim:
    def test_skill_md_exists(self) -> None:
        assert (_skill_dir("design_to_plan") / "SKILL.md").is_file()

    def test_skill_md_thin(self) -> None:
        _assert_thin_skill(
            "design_to_plan",
            "node_design_to_plan",
            "onex.cmd.omnimarket.design-to-plan-start.v1",
        )

    def test_prompt_md_thin(self) -> None:
        _assert_thin_prompt("design_to_plan", "node_design_to_plan")

    def test_skill_md_has_required_args(self) -> None:
        fm = _frontmatter(_read_skill("design_to_plan"))
        arg_names = [a["name"] for a in fm["args"]]
        assert "--phase" in arg_names
        assert "--topic" in arg_names
        assert "--plan-path" in arg_names
        assert "--no-launch" in arg_names


# ─── plan_to_tickets ──────────────────────────────────────────────────────────


@pytest.mark.unit
class TestPlanToTicketsShim:
    def test_skill_md_exists(self) -> None:
        assert (_skill_dir("plan_to_tickets") / "SKILL.md").is_file()

    def test_skill_md_thin(self) -> None:
        _assert_thin_skill(
            "plan_to_tickets",
            "node_plan_to_tickets",
            "onex.cmd.omnimarket.plan-to-tickets-start.v1",
        )

    def test_prompt_md_thin(self) -> None:
        _assert_thin_prompt("plan_to_tickets", "node_plan_to_tickets")

    def test_skill_md_has_required_args(self) -> None:
        fm = _frontmatter(_read_skill("plan_to_tickets"))
        arg_names = [a["name"] for a in fm["args"]]
        assert "plan-file" in arg_names
        assert "--dry-run" in arg_names
        assert "--team" in arg_names
        assert "--no-create-epic" in arg_names


# ─── create_ticket ────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestCreateTicketShim:
    def test_skill_md_exists(self) -> None:
        assert (_skill_dir("create_ticket") / "SKILL.md").is_file()

    def test_skill_md_thin(self) -> None:
        _assert_thin_skill(
            "create_ticket",
            "node_create_ticket",
            "onex.cmd.omnimarket.create-ticket-start.v1",
        )

    def test_prompt_md_thin(self) -> None:
        _assert_thin_prompt("create_ticket", "node_create_ticket")

    def test_skill_md_has_required_args(self) -> None:
        fm = _frontmatter(_read_skill("create_ticket"))
        arg_names = [a["name"] for a in fm["args"]]
        assert "--from-contract" in arg_names
        assert "--from-plan" in arg_names
        assert "--parent" in arg_names
        assert "--dry-run" in arg_names


# ─── linear_housekeeping ──────────────────────────────────────────────────────


@pytest.mark.unit
class TestLinearHousekeepingShim:
    def test_skill_md_exists(self) -> None:
        assert (_skill_dir("linear_housekeeping") / "SKILL.md").is_file()

    def test_skill_md_thin(self) -> None:
        _assert_thin_skill(
            "linear_housekeeping",
            "node_linear_triage",
            "onex.cmd.omnimarket.linear-triage-start.v1",
        )

    def test_prompt_md_thin(self) -> None:
        _assert_thin_prompt("linear_housekeeping", "node_linear_triage")

    def test_prompt_md_no_inline_linear_queries(self) -> None:
        content = _read_prompt("linear_housekeeping")
        assert "mcp__linear" not in content
        assert "ticketing_triage" not in content
        assert "ticketing_epic_org" not in content
