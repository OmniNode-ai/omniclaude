# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for the thin /onex:overnight dispatch shim (OMN-8751).

Validates that the overnight skill contains no inline LLM orchestration
and dispatches directly to node_overnight via `onex run-node`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

SKILL_DIR = (
    Path(__file__).resolve().parents[3] / "plugins" / "onex" / "skills" / "overnight"
)


@pytest.mark.unit
class TestOvernightSkillMd:
    """Validate the overnight SKILL.md artifact is a thin shim."""

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

    def test_skill_md_tagged_dispatch_only(self) -> None:
        content = (SKILL_DIR / "SKILL.md").read_text()
        fm = yaml.safe_load(content.split("---", 2)[1])
        assert "dispatch-only" in fm["tags"]
        assert "routing-enforced" in fm["tags"]

    def test_skill_md_declares_thin_shim_args(self) -> None:
        content = (SKILL_DIR / "SKILL.md").read_text()
        fm = yaml.safe_load(content.split("---", 2)[1])
        arg_names = [a["name"] for a in fm["args"]]
        assert "--max-cycles" in arg_names
        assert "--dry-run" in arg_names
        assert "--skip-build-loop" in arg_names
        assert "--skip-merge-sweep" in arg_names

    def test_skill_md_not_deprecated(self) -> None:
        """OMN-8751: overnight is no longer deprecated — it is the thin shim."""
        content = (SKILL_DIR / "SKILL.md").read_text()
        # No "DEPRECATED" banner anywhere in the document.
        assert "DEPRECATED" not in content.upper()
        assert "will be removed" not in content.lower()
        # "superseded" may appear only when framed as direct-entry-point context.
        if "superseded" in content.lower():
            assert "direct entry point" in content.lower()

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
    """Validate the overnight prompt.md is dispatch-only."""

    def test_prompt_md_exists(self) -> None:
        assert (SKILL_DIR / "prompt.md").is_file()

    def test_prompt_md_has_announce(self) -> None:
        content = (SKILL_DIR / "prompt.md").read_text()
        assert "Announce" in content

    def test_prompt_md_dispatches_to_node(self) -> None:
        content = (SKILL_DIR / "prompt.md").read_text()
        assert "onex run-node node_overnight" in content

    def test_prompt_md_no_inline_phase_orchestration(self) -> None:
        """Prompt must not contain inline per-phase orchestration loops."""
        content = (SKILL_DIR / "prompt.md").read_text()
        # No session_bootstrap, session_post_mortem, platform_readiness
        # dispatch in the shim — the node owns those phases.
        assert "node_session_bootstrap" not in content
        assert "node_session_post_mortem" not in content
        assert "node_platform_readiness" not in content

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

    def test_prompt_md_single_dispatch(self) -> None:
        """A4 invariant: exactly one onex run-node dispatch."""
        content = (SKILL_DIR / "prompt.md").read_text()
        matches = re.findall(r"onex\s+run-node\s+node_overnight", content)
        assert len(matches) == 1, (
            f"Expected exactly 1 onex run-node dispatch, found {len(matches)}"
        )

    def test_prompt_md_surfaces_skill_routing_error(self) -> None:
        content = (SKILL_DIR / "prompt.md").read_text()
        assert "SkillRoutingError" in content
        assert "do not produce prose" in content.lower()

    def test_prompt_md_preserves_cli_args(self) -> None:
        content = (SKILL_DIR / "prompt.md").read_text()
        assert "--max-cycles" in content
        assert "--dry-run" in content
        assert "--skip-build-loop" in content
        assert "--skip-merge-sweep" in content

    def test_prompt_md_no_subprocess_wrappers(self) -> None:
        """A4 invariant: no subprocess.run / Popen / shell helpers."""
        content = (SKILL_DIR / "prompt.md").read_text()
        assert "subprocess.run" not in content
        assert "subprocess.Popen" not in content

    def test_prompt_md_is_thin(self) -> None:
        """Shim must be ≤ 100 lines — anything larger drifts back into orchestration."""
        content = (SKILL_DIR / "prompt.md").read_text()
        line_count = len(content.splitlines())
        assert line_count <= 100, (
            f"Thin shim must be ≤ 100 lines, got {line_count}. "
            f"If the skill is growing logic, move it into node_overnight."
        )


@pytest.mark.unit
class TestOvernightSkillCompleteness:
    """Cross-cutting validation that the shim contract is whole."""

    def test_skill_dir_has_required_files(self) -> None:
        assert (SKILL_DIR / "SKILL.md").is_file()
        assert (SKILL_DIR / "prompt.md").is_file()

    def test_no_phantom_callables(self) -> None:
        """Shim must not invent callables beyond the onex CLI."""
        content = (SKILL_DIR / "prompt.md").read_text()
        # Only onex run-node is permitted for execution in the shim.
        assert "execute.py" not in content
        assert "run_overnight(" not in content
        assert "dispatch_workers(" not in content
