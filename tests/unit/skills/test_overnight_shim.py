# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for the retired /onex:overnight skill surface (OMN-9428).

Validates that the overnight skill is no longer user-invocable and its prompt
does not execute the old dispatch surface.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

SKILL_DIR = (
    Path(__file__).resolve().parents[3] / "plugins" / "onex" / "skills" / "overnight"
)


@pytest.mark.unit
class TestOvernightSkillMd:
    """Validate the overnight SKILL.md artifact is retired."""

    def test_skill_md_exists(self) -> None:
        assert (SKILL_DIR / "SKILL.md").is_file()

    def test_skill_md_has_valid_frontmatter(self) -> None:
        content = (SKILL_DIR / "SKILL.md").read_text()
        assert content.startswith("---")
        parts = content.split("---", 2)
        assert len(parts) >= 3, "Frontmatter not properly delimited"
        fm = yaml.safe_load(parts[1])
        assert fm["description"], "description required"
        assert fm["version"] == "2.0.0"
        assert fm["mode"] == "full"
        assert fm["category"] == "workflow"
        assert fm["user_invocable"] is False
        assert fm["retired"] is True
        assert fm["replacement_skill"] == "session"

    def test_skill_md_tagged_retired(self) -> None:
        content = (SKILL_DIR / "SKILL.md").read_text()
        fm = yaml.safe_load(content.split("---", 2)[1])
        assert "retired" in fm["tags"]

    def test_skill_md_declares_thin_shim_args(self) -> None:
        content = (SKILL_DIR / "SKILL.md").read_text()
        fm = yaml.safe_load(content.split("---", 2)[1])
        arg_names = [a["name"] for a in fm["args"]]
        assert "--max-cycles" in arg_names
        assert "--dry-run" in arg_names
        assert "--skip-build-loop" in arg_names
        assert "--skip-merge-sweep" in arg_names

    def test_skill_md_retired_banner(self) -> None:
        content = (SKILL_DIR / "SKILL.md").read_text()
        assert "RETIRED" in content
        assert "not user-invocable" in content
        assert "/onex:session --mode autonomous" in content

    def test_skill_md_references_backing_node(self) -> None:
        content = (SKILL_DIR / "SKILL.md").read_text()
        assert "node_overnight" in content
        assert "omnimarket" in content

    def test_skill_md_has_dispatch_command(self) -> None:
        content = (SKILL_DIR / "SKILL.md").read_text()
        assert "onex run-node node_overnight" in content

    def test_skill_md_declares_skill_routing_error(self) -> None:
        """Dispatch-only shims must surface SkillRoutingError on failure."""
        content = (SKILL_DIR / "SKILL.md").read_text()
        assert "SkillRoutingError" in content
        assert "do not produce prose" in content.lower()


@pytest.mark.unit
class TestOvernightPromptMd:
    """Validate the overnight prompt.md is retired."""

    def test_prompt_md_exists(self) -> None:
        assert (SKILL_DIR / "prompt.md").is_file()

    def test_prompt_md_is_retirement_stub(self) -> None:
        content = (SKILL_DIR / "prompt.md").read_text()
        assert "retired" in content.lower()
        assert "not user-invocable" in content
        assert "/onex:session --mode autonomous" in content

    def test_prompt_md_no_inline_phase_orchestration(self) -> None:
        """Prompt must not contain inline per-phase orchestration loops."""
        content = (SKILL_DIR / "prompt.md").read_text()
        # No session_bootstrap, session_post_mortem, platform_readiness
        # dispatch in the shim — the node owns those phases.
        assert "onex run-node" not in content

    def test_prompt_md_no_agent_spawning(self) -> None:
        """Thin shim must not spawn Agent() workers or create teams."""
        content = (SKILL_DIR / "prompt.md").read_text()
        assert "TeamCreate" not in content
        assert "Agent(" not in content
        assert "CronCreate" not in content
        assert "SendMessage" not in content

    def test_prompt_md_no_llm_sdk_imports(self) -> None:
        """AST lint: no LLM SDK imports allowed (A4)."""
        content = (SKILL_DIR / "prompt.md").read_text()
        assert "import anthropic" not in content
        assert "from anthropic" not in content
        assert "import openai" not in content
        assert "from openai" not in content

    def test_prompt_md_no_subprocess_wrappers(self) -> None:
        """A4 invariant: no subprocess.run / Popen / shell helpers."""
        content = (SKILL_DIR / "prompt.md").read_text()
        assert "subprocess.run" not in content
        assert "subprocess.Popen" not in content

    def test_prompt_md_is_thin(self) -> None:
        """Retirement stub must stay thin."""
        content = (SKILL_DIR / "prompt.md").read_text()
        line_count = len(content.splitlines())
        assert line_count <= 20


@pytest.mark.unit
class TestOvernightSkillCompleteness:
    """Cross-cutting validation that the retired surface is whole."""

    def test_skill_dir_has_required_files(self) -> None:
        assert (SKILL_DIR / "SKILL.md").is_file()
        assert (SKILL_DIR / "prompt.md").is_file()

    def test_no_phantom_callables(self) -> None:
        """Retirement prompt must not invent callables."""
        content = (SKILL_DIR / "prompt.md").read_text()
        assert "execute.py" not in content
        assert "run_overnight(" not in content
        assert "dispatch_workers(" not in content
