# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for the /onex:demo delegation skill scaffolding.

This test stub verifies:
- SKILL.md exists and parses as YAML frontmatter
- Required frontmatter keys are present
- The dispatcher module is importable
- The dispatcher returns a structured failure envelope when downstream
  dependencies are missing (scaffolding mode)
- The dispatcher rejects unknown subcommands

It does NOT verify end-to-end multi-model fan-out — that is deferred to
follow-up PRs. See docs/plans/2026-04-10-demo-skill-plan.md.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import yaml


@pytest.mark.unit
class TestDemoSkillScaffolding:
    """Verify the /onex:demo skill scaffolding is wired correctly."""

    SKILL_DIR = (
        Path(__file__).resolve().parents[2] / "plugins" / "onex" / "skills" / "demo"
    )

    def test_skill_dir_exists(self) -> None:
        assert self.SKILL_DIR.is_dir(), f"{self.SKILL_DIR} should exist"

    def test_skill_md_exists(self) -> None:
        assert (self.SKILL_DIR / "SKILL.md").is_file()

    def test_dispatch_py_exists(self) -> None:
        assert (self.SKILL_DIR / "dispatch.py").is_file()

    def test_skill_md_has_frontmatter(self) -> None:
        content = (self.SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        assert content.startswith("---\n"), "SKILL.md must start with YAML frontmatter"
        _, _, rest = content.partition("---\n")
        frontmatter_text, sep, _ = rest.partition("\n---\n")
        assert sep, "SKILL.md frontmatter must be terminated by '---'"
        meta = yaml.safe_load(frontmatter_text)
        assert isinstance(meta, dict)
        for key in (
            "description",
            "mode",
            "version",
            "level",
            "category",
            "tags",
            "author",
            "args",
        ):
            assert key in meta, f"SKILL.md frontmatter missing '{key}'"
        assert meta["category"] == "demo"
        assert isinstance(meta["args"], list) and meta["args"], "args must be non-empty"
        arg_names = {arg.get("name") for arg in meta["args"] if isinstance(arg, dict)}
        assert "subcommand" in arg_names

    def test_dispatch_module_importable(self) -> None:
        dispatch_path = self.SKILL_DIR / "dispatch.py"
        spec = importlib.util.spec_from_file_location(
            "onex_demo_dispatch", dispatch_path
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        assert hasattr(module, "dispatch")
        assert hasattr(module, "SCAFFOLD_MARKER")
        assert module.SCAFFOLD_MARKER == "demo-skill-scaffolding"

    def _load_dispatch(self):
        dispatch_path = self.SKILL_DIR / "dispatch.py"
        spec = importlib.util.spec_from_file_location(
            "onex_demo_dispatch", dispatch_path
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_dispatch_rejects_unknown_subcommand(self) -> None:
        module = self._load_dispatch()
        result = module.dispatch("totally-not-a-subcommand")
        assert result["success"] is False
        assert "Unknown subcommand" in result["error"]
        assert result["scaffold_marker"] == "demo-skill-scaffolding"

    def test_dispatch_delegation_returns_scaffold_failure(self) -> None:
        """Until the fan-out handler lands, delegation returns structured failure."""
        module = self._load_dispatch()
        result = module.dispatch("delegation", count=3, dry_run=True)
        # In scaffolding mode the downstream import fails and we get a
        # structured envelope. If follow-up PRs have already landed the
        # dispatcher will raise NotImplementedError instead — in that case
        # this test should be rewritten, not silently passed.
        assert result["success"] is False
        assert result["scaffold_marker"] == "demo-skill-scaffolding"
        assert result["missing_dependency"] == (
            "omnimarket.nodes.node_demo_fanout_orchestrator"
        )
        assert result["plan_path"].endswith("demo-skill-plan.md")
        assert result["dry_run"] is True
