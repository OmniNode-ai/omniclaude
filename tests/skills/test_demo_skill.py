# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for the /onex:demo delegation skill runtime dispatcher.

This verifies:
- SKILL.md exists and parses as YAML frontmatter
- Required frontmatter keys are present
- The dispatcher module is importable
- The dispatcher routes through runtime-dispatched OmniMarket demo nodes
- The dispatcher rejects unknown subcommands
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import yaml


@pytest.mark.unit
class TestDemoSkillScaffolding:
    """Verify the /onex:demo skill runtime shim is wired correctly."""

    SKILL_DIR = (
        Path(__file__).resolve().parents[2] / "plugins" / "onex" / "skills" / "demo"
    )

    def test_skill_dir_exists(self) -> None:
        assert self.SKILL_DIR.is_dir(), f"{self.SKILL_DIR} should exist"

    def test_skill_md_exists(self) -> None:
        assert (self.SKILL_DIR / "SKILL.md").is_file()

    def test_dispatch_py_exists(self) -> None:
        assert (self.SKILL_DIR / "_lib" / "dispatch.py").is_file()

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
        dispatch_path = self.SKILL_DIR / "_lib" / "dispatch.py"
        spec = importlib.util.spec_from_file_location(
            "onex_demo_dispatch", dispatch_path
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        assert hasattr(module, "dispatch")
        assert hasattr(module, "SUPPORTED_SUBCOMMANDS")

    def _load_dispatch(self):
        dispatch_path = self.SKILL_DIR / "_lib" / "dispatch.py"
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

    def test_dispatch_delegation_routes_native_demo_nodes(self, monkeypatch) -> None:
        module = self._load_dispatch()
        calls: list[str] = []

        def fake_dispatch_runtime(*, command_name, payload, response_topic):
            calls.append(command_name)
            if command_name == "demo_fanout_orchestrator":
                assert payload["dry_run"] is True
                return {
                    "results": [
                        {
                            "model_id": "gemini/gemini-2.0-flash",
                            "prompt_tokens": 1,
                            "completion_tokens": 1,
                            "latency_ms": 1.0,
                            "output_text": "ok",
                        },
                        {
                            "model_id": "onex-deterministic",
                            "prompt_tokens": 0,
                            "completion_tokens": 0,
                            "latency_ms": 0.0,
                            "output_text": "ok",
                        },
                    ]
                }
            if command_name == "demo_cost_compute":
                return {
                    "costs": [
                        {
                            "model_id": "gemini/gemini-2.0-flash",
                            "total_cost_usd": 0.01,
                        },
                        {
                            "model_id": "onex-deterministic",
                            "total_cost_usd": 0.0,
                        },
                    ],
                    "cheapest_model_id": "onex-deterministic",
                }
            if command_name == "demo_renderer_effect":
                return {"chart_lines": ["chart", "Cheapest: onex-deterministic"]}
            raise AssertionError(command_name)

        monkeypatch.setattr(module, "_dispatch_runtime", fake_dispatch_runtime)

        result = module.dispatch("delegation", count=3, dry_run=True)

        assert result["success"] is True
        assert result["dry_run"] is True
        assert result["runtime_path"] == "omnimarket.native_nodes"
        assert calls == [
            "demo_fanout_orchestrator",
            "demo_cost_compute",
            "demo_renderer_effect",
        ]
        assert result["cheapest_llm_model"] == "gemini/gemini-2.0-flash"
        assert result["cheapest_overall_path"] == "onex-deterministic"
