# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for the thin /onex:merge_sweep dispatch shim (OMN-8752).

Validates that the merge_sweep skill contains no inline GH script fallback,
no direct Kafka publish, no orchestration logic, and dispatches directly
to node_merge_sweep via `onex run-node`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

SKILL_DIR = (
    Path(__file__).resolve().parents[3] / "plugins" / "onex" / "skills" / "merge_sweep"
)


@pytest.mark.unit
class TestMergeSweepSkillMd:
    """Validate the merge_sweep SKILL.md artifact is a thin shim."""

    def test_skill_md_exists(self) -> None:
        assert (SKILL_DIR / "SKILL.md").is_file()

    def test_skill_md_has_valid_frontmatter(self) -> None:
        content = (SKILL_DIR / "SKILL.md").read_text()
        assert content.startswith("---")
        parts = content.split("---", 2)
        assert len(parts) >= 3, "Frontmatter not properly delimited"
        fm = yaml.safe_load(parts[1])
        assert fm["description"], "description required"
        assert fm["version"] == "6.1.0"
        assert fm["mode"] == "full"
        assert fm["category"] == "workflow"

    def test_skill_md_tagged_dispatch_only(self) -> None:
        content = (SKILL_DIR / "SKILL.md").read_text()
        fm = yaml.safe_load(content.split("---", 2)[1])
        assert "dispatch-only" in fm["tags"]
        assert "routing-enforced" in fm["tags"]

    def test_skill_md_preserves_cli_surface(self) -> None:
        content = (SKILL_DIR / "SKILL.md").read_text()
        fm = yaml.safe_load(content.split("---", 2)[1])
        arg_names = [a["name"] for a in fm["args"]]
        # Spot-check the critical v3.x+ flags are preserved
        for required in (
            "--repos",
            "--dry-run",
            "--merge-method",
            "--skip-polish",
            "--authors",
            "--since",
            "--resume",
            "--inventory-only",
            "--fix-only",
            "--merge-only",
            "--enable-auto-rebase",
            "--use-dag-ordering",
            "--enable-trivial-comment-resolution",
            "--enable-admin-merge-fallback",
            "--admin-fallback-threshold-minutes",
            "--verify",
            "--verify-timeout-seconds",
        ):
            assert required in arg_names, f"missing preserved arg: {required}"

    def test_skill_md_references_backing_node(self) -> None:
        content = (SKILL_DIR / "SKILL.md").read_text()
        assert "node_merge_sweep" in content
        assert "omnimarket" in content

    def test_skill_md_has_dispatch_command(self) -> None:
        content = (SKILL_DIR / "SKILL.md").read_text()
        assert "onex run-node node_merge_sweep" in content

    def test_skill_md_declares_skill_routing_error(self) -> None:
        """Dispatch-only shims must surface SkillRoutingError on failure."""
        content = (SKILL_DIR / "SKILL.md").read_text()
        assert "SkillRoutingError" in content
        assert "do not produce prose" in content.lower()

    def test_skill_md_no_inline_gh_script(self) -> None:
        """A4: no inline `gh pr merge` or subprocess gh fallback."""
        content = (SKILL_DIR / "SKILL.md").read_text()
        assert "gh pr merge --auto" not in content
        assert "gh pr merge --admin" not in content
        assert "gh pr merge --squash" not in content

    def test_skill_md_no_direct_kafka_publish(self) -> None:
        """A4: no direct `kcat -P` or event-bus publish in the shim."""
        content = (SKILL_DIR / "SKILL.md").read_text()
        assert "kcat -P" not in content
        assert "ModelEventEnvelope" not in content


@pytest.mark.unit
class TestMergeSweepPromptMd:
    """Validate the merge_sweep prompt.md is dispatch-only."""

    def test_prompt_md_exists(self) -> None:
        assert (SKILL_DIR / "prompt.md").is_file()

    def test_prompt_md_has_announce(self) -> None:
        content = (SKILL_DIR / "prompt.md").read_text()
        assert "Announce" in content

    def test_prompt_md_dispatches_to_node(self) -> None:
        content = (SKILL_DIR / "prompt.md").read_text()
        assert "onex run-node node_merge_sweep" in content

    def test_prompt_md_no_inline_orchestration(self) -> None:
        """Prompt must not contain inline per-repo or per-PR orchestration."""
        content = (SKILL_DIR / "prompt.md").read_text()
        # No inline Kafka publish, no inline claim registry, no inline polling.
        assert "kcat -P" not in content
        assert "ModelEventEnvelope" not in content
        assert "result.json" not in content
        assert "poll_interval" not in content

    def test_prompt_md_no_gh_subprocess(self) -> None:
        """A4: no `gh pr merge` or other gh subprocess invocations in the shim."""
        content = (SKILL_DIR / "prompt.md").read_text()
        assert "gh pr merge --auto" not in content
        assert "gh pr merge --admin" not in content
        assert "gh pr merge --squash" not in content
        assert "gh api graphql" not in content

    def test_prompt_md_no_agent_spawning(self) -> None:
        """Thin shim must not spawn Agent() workers or create teams."""
        content = (SKILL_DIR / "prompt.md").read_text()
        assert "TeamCreate" not in content
        assert "Agent(" not in content
        assert "CronCreate" not in content
        assert "SendMessage" not in content

    def test_prompt_md_no_llm_sdk_imports(self) -> None:
        """A4 AST lint: no LLM SDK imports allowed."""
        content = (SKILL_DIR / "prompt.md").read_text()
        assert "import anthropic" not in content
        assert "from anthropic" not in content
        assert "import openai" not in content
        assert "from openai" not in content

    def test_prompt_md_single_dispatch(self) -> None:
        """A4 invariant: exactly one onex run-node dispatch to node_merge_sweep."""
        content = (SKILL_DIR / "prompt.md").read_text()
        matches = re.findall(r"onex\s+run-node\s+node_merge_sweep", content)
        assert len(matches) == 1, (
            f"Expected exactly 1 onex run-node dispatch, found {len(matches)}"
        )

    def test_prompt_md_surfaces_skill_routing_error(self) -> None:
        content = (SKILL_DIR / "prompt.md").read_text()
        assert "SkillRoutingError" in content
        assert "do not produce prose" in content.lower()

    def test_prompt_md_preserves_cli_args(self) -> None:
        content = (SKILL_DIR / "prompt.md").read_text()
        # Spot-check critical flags
        for flag in (
            "--repos",
            "--dry-run",
            "--merge-method",
            "--skip-polish",
            "--authors",
            "--since",
            "--resume",
            "--inventory-only",
            "--enable-admin-merge-fallback",
            "--verify",
        ):
            assert flag in content, f"missing preserved arg in prompt: {flag}"

    def test_prompt_md_no_subprocess_wrappers(self) -> None:
        """A4 invariant: no subprocess.run / Popen / shell Python helpers."""
        content = (SKILL_DIR / "prompt.md").read_text()
        assert "subprocess.run" not in content
        assert "subprocess.Popen" not in content

    def test_prompt_md_is_thin(self) -> None:
        """Shim must be <= 100 lines — anything larger drifts back into orchestration."""
        content = (SKILL_DIR / "prompt.md").read_text()
        line_count = len(content.splitlines())
        assert line_count <= 100, (
            f"Thin shim must be <= 100 lines, got {line_count}. "
            f"If the skill is growing logic, move it into node_merge_sweep."
        )


@pytest.mark.unit
class TestMergeSweepSkillCompleteness:
    """Cross-cutting validation that the shim contract is whole."""

    def test_skill_dir_has_required_files(self) -> None:
        assert (SKILL_DIR / "SKILL.md").is_file()
        assert (SKILL_DIR / "prompt.md").is_file()

    def test_no_phantom_callables(self) -> None:
        """Shim must not invent callables beyond the onex CLI."""
        content = (SKILL_DIR / "prompt.md").read_text()
        # Only `uv run onex run-node` is permitted for execution in the shim.
        assert "pr_lifecycle_orchestrator(" not in content
        assert "dispatch_merge_sweep(" not in content
        assert "run_merge_sweep(" not in content

    def test_no_inline_claim_registry(self) -> None:
        """The claim registry belongs to the node, not the shim."""
        content = (SKILL_DIR / "prompt.md").read_text()
        assert "claim_registry" not in content.lower()
        assert "dispatched.yaml" not in content
