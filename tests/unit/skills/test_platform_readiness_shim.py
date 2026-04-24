# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for the thin /onex:platform_readiness dispatch shim (OMN-8755).

Validates that the platform_readiness skill contains no inline probe
aggregation and dispatches directly to node_platform_readiness via
`onex run-node`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

SKILL_DIR = (
    Path(__file__).resolve().parents[3]
    / "plugins"
    / "onex"
    / "skills"
    / "platform_readiness"
)


@pytest.mark.unit
class TestPlatformReadinessSkillMd:
    """Validate the platform_readiness SKILL.md artifact is a thin shim."""

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
        assert fm["category"] == "verification"

    def test_skill_md_tagged_dispatch_only(self) -> None:
        content = (SKILL_DIR / "SKILL.md").read_text()
        fm = yaml.safe_load(content.split("---", 2)[1])
        assert "dispatch-only" in fm["tags"]
        assert "routing-enforced" in fm["tags"]

    def test_skill_md_declares_thin_shim_args(self) -> None:
        content = (SKILL_DIR / "SKILL.md").read_text()
        fm = yaml.safe_load(content.split("---", 2)[1])
        arg_names = [a["name"] for a in fm["args"]]
        assert "--json" in arg_names
        assert "--dimension" in arg_names

    def test_skill_md_not_deprecated(self) -> None:
        content = (SKILL_DIR / "SKILL.md").read_text()
        assert "DEPRECATED" not in content.upper()
        assert "will be removed" not in content.lower()

    def test_skill_md_references_backing_node(self) -> None:
        content = (SKILL_DIR / "SKILL.md").read_text()
        assert "node_platform_readiness" in content
        assert "omnimarket" in content

    def test_skill_md_has_dispatch_command(self) -> None:
        content = (SKILL_DIR / "SKILL.md").read_text()
        assert "onex run-node node_platform_readiness" in content

    def test_skill_md_declares_skill_routing_error(self) -> None:
        content = (SKILL_DIR / "SKILL.md").read_text()
        assert "SkillRoutingError" in content
        assert "do not produce prose" in content.lower()


@pytest.mark.unit
class TestPlatformReadinessPromptMd:
    """Validate the platform_readiness prompt.md is dispatch-only."""

    def test_prompt_md_exists(self) -> None:
        assert (SKILL_DIR / "prompt.md").is_file()

    def test_prompt_md_has_announce(self) -> None:
        content = (SKILL_DIR / "prompt.md").read_text()
        assert "Announce" in content

    def test_prompt_md_dispatches_to_node(self) -> None:
        content = (SKILL_DIR / "prompt.md").read_text()
        assert "onex run-node node_platform_readiness" in content

    def test_prompt_md_no_inline_probe_aggregation(self) -> None:
        """Prompt must not contain inline probe aggregation across dimensions."""
        content = (SKILL_DIR / "prompt.md").read_text()
        # No invocation of other sweep nodes/scripts to aggregate dimensions.
        assert "node_golden_chain_sweep" not in content
        assert "node_data_flow_sweep" not in content
        assert "node_runtime_sweep" not in content
        assert "node_contract_sweep" not in content

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
        matches = re.findall(r"onex\s+run-node\s+node_platform_readiness", content)
        assert len(matches) == 1, (
            f"Expected exactly 1 onex run-node dispatch, found {len(matches)}"
        )

    def test_prompt_md_surfaces_skill_routing_error(self) -> None:
        content = (SKILL_DIR / "prompt.md").read_text()
        assert "SkillRoutingError" in content
        assert "do not produce prose" in content.lower()

    def test_prompt_md_preserves_cli_args(self) -> None:
        content = (SKILL_DIR / "prompt.md").read_text()
        assert "--json" in content
        assert "--dimension" in content

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
            f"If the skill is growing logic, move it into node_platform_readiness."
        )


@pytest.mark.unit
class TestPlatformReadinessSkillCompleteness:
    """Cross-cutting validation that the shim contract is whole."""

    def test_skill_dir_has_required_files(self) -> None:
        assert (SKILL_DIR / "SKILL.md").is_file()
        assert (SKILL_DIR / "prompt.md").is_file()

    def test_no_phantom_callables(self) -> None:
        """Shim must not invent callables beyond the onex CLI."""
        content = (SKILL_DIR / "prompt.md").read_text()
        assert "execute.py" not in content
        assert "run_platform_readiness(" not in content
        assert "aggregate_dimensions(" not in content
