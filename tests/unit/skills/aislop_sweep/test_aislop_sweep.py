# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Integration tests for the aislop-sweep skill.

Verifies the thin dispatch-only shim structure (OMN-8753 / A4 amendment):
SKILL.md + prompt.md must not contain script fallback, inline grep patterns,
or subprocess wrappers — all scan logic lives in node_aislop_sweep.

All tests are @pytest.mark.unit (no live grep, ruff, mypy, or network calls).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[4]
_SKILLS_ROOT = _REPO_ROOT / "plugins" / "onex" / "skills"
_AISLOP_SWEEP_DIR = _SKILLS_ROOT / "aislop_sweep"
_SKILL_MD = _AISLOP_SWEEP_DIR / "SKILL.md"
_PROMPT_MD = _AISLOP_SWEEP_DIR / "prompt.md"
_TOPICS_YAML = _AISLOP_SWEEP_DIR / "topics.yaml"
_GOLDEN_PATH_DIR = _SKILLS_ROOT / "_golden_path_validate"
_FIXTURE_JSON = _GOLDEN_PATH_DIR / "node_skill_aislop_sweep_orchestrator.json"
_SAMPLE_SLOP = Path(__file__).parent / "fixtures" / "sample_slop.py"


def _read(path: Path) -> str:
    if not path.exists():
        pytest.skip(f"File not found: {path}")
    return path.read_text(encoding="utf-8")


@pytest.mark.unit
class TestSkillMd:
    def test_dry_run_documented(self) -> None:
        content = _read(_SKILL_MD)
        assert "--dry-run" in content

    def test_all_checks_documented(self) -> None:
        content = _read(_SKILL_MD)
        for check in (
            "phantom-callables",
            "compat-shims",
            "prohibited-patterns",
            "hardcoded-topics",
            "hardcoded-paths",
            "todo-fixme",
            "empty-impls",
        ):
            assert check in content, f"SKILL.md missing check: {check}"

    def test_status_values_include_clean_and_findings(self) -> None:
        content = _read(_SKILL_MD)
        assert "clean" in content
        assert "findings" in content

    def test_ticket_flag_documented_with_aislop_label(self) -> None:
        content = _read(_SKILL_MD)
        assert "--ticket" in content
        assert "aislop-sweep" in content.lower() or "aislop" in content

    def test_path_exclusions_listed(self) -> None:
        content = _read(_SKILL_MD)
        for exclusion in (".git/", ".venv/", "docs/", "fixtures/"):
            assert exclusion in content, f"SKILL.md missing path exclusion: {exclusion}"

    def test_dispatch_target_is_omnimarket_node(self) -> None:
        """SKILL.md must dispatch to the omnimarket node, not embed scan logic."""
        content = _read(_SKILL_MD)
        assert "node_aislop_sweep" in content
        assert "omnimarket" in content

    def test_uses_local_runtime_dispatch(self) -> None:
        """SKILL.md must use `onex node` (local RuntimeLocal), not `onex run-node` (Kafka)."""
        content = _read(_SKILL_MD)
        assert "onex node" in content
        # run-node is the Kafka path — not allowed for a dispatch-only shim
        assert "onex run-node" not in content, (
            "thin shim must not use `onex run-node` (Kafka dispatch)"
        )


@pytest.mark.unit
class TestPromptMd:
    """Enforce dispatch-only shim invariants on prompt.md (OMN-8753 / A4).

    prompt.md must be a thin shim: announce + parse args + dispatch + render.
    It must not contain grep patterns, script fallbacks, or inline scan logic.
    """

    def test_has_announce(self) -> None:
        content = _read(_PROMPT_MD)
        assert "Announce" in content or "announce" in content.lower()

    def test_dispatches_to_node(self) -> None:
        content = _read(_PROMPT_MD)
        assert "node_aislop_sweep" in content

    def test_uses_local_runtime_not_kafka(self) -> None:
        """Must use `uv run onex node` (RuntimeLocal), not `onex run-node` (Kafka)."""
        content = _read(_PROMPT_MD)
        assert "uv run onex node" in content or "onex node " in content
        assert "onex run-node" not in content, (
            "thin shim must not use `onex run-node` (Kafka dispatch path)"
        )

    def test_no_script_fallback(self) -> None:
        """prompt.md must not include any script fallback or inline grep patterns."""
        content = _read(_PROMPT_MD)
        forbidden = (
            "grep -r",
            "grep -rn",
            "rg --type",
            "run_aislop_sweep.py",
            "run_aislop_precommit.py",
        )
        for pattern in forbidden:
            assert pattern not in content, (
                f"prompt.md must be dispatch-only — forbidden fallback pattern: {pattern!r}"
            )

    def test_no_inline_phase_logic(self) -> None:
        """Thin shim has no multi-phase scan/triage/ticket logic embedded in prompt."""
        content = _read(_PROMPT_MD)
        # Count `## Phase` headings (fat-prompt style) — thin shim has 0
        phase_count = len(re.findall(r"^## Phase \d", content, re.MULTILINE))
        assert phase_count == 0, (
            f"thin shim must not enumerate scan phases inline; found {phase_count}"
        )

    def test_dry_run_documented(self) -> None:
        content = _read(_PROMPT_MD)
        assert "--dry-run" in content

    def test_ticket_flag_documented(self) -> None:
        content = _read(_PROMPT_MD)
        assert "--ticket" in content

    def test_error_handling_surfaces_skill_routing_error(self) -> None:
        content = _read(_PROMPT_MD)
        assert "SkillRoutingError" in content


@pytest.mark.unit
class TestTopicsYaml:
    def test_exactly_three_topics(self) -> None:
        content = _read(_TOPICS_YAML)
        topics = [
            line.strip().lstrip("- ")
            for line in content.splitlines()
            if line.strip().startswith("- onex.")
        ]
        assert len(topics) == 3, f"Expected 3 topics, found {len(topics)}: {topics}"

    def test_topic_naming_convention(self) -> None:
        content = _read(_TOPICS_YAML)
        assert "onex.cmd.omniclaude.aislop-sweep.v1" in content
        assert "onex.evt.omniclaude.aislop-sweep-completed.v1" in content
        assert "onex.evt.omniclaude.aislop-sweep-failed.v1" in content

    def test_spdx_header_present(self) -> None:
        content = _read(_TOPICS_YAML)
        assert "SPDX" in content


@pytest.mark.unit
class TestGoldenPathFixture:
    def test_fixture_exists(self) -> None:
        assert _FIXTURE_JSON.exists(), f"Golden-path fixture not found: {_FIXTURE_JSON}"

    def test_fixture_correct_topics(self) -> None:
        if not _FIXTURE_JSON.exists():
            pytest.skip("Fixture not found")
        data = json.loads(_FIXTURE_JSON.read_text())
        assert data["input"]["topic"] == "onex.cmd.omniclaude.aislop-sweep.v1"
        assert (
            data["output"]["topic"] == "onex.evt.omniclaude.aislop-sweep-completed.v1"
        )

    def test_fixture_has_dry_run(self) -> None:
        if not _FIXTURE_JSON.exists():
            pytest.skip("Fixture not found")
        data = json.loads(_FIXTURE_JSON.read_text())
        args = data["input"]["fixture"].get("args", {})
        assert args.get("--dry-run") is True


@pytest.mark.unit
class TestOrchestratorNode:
    def test_node_directory_exists(self) -> None:
        node_dir = (
            _REPO_ROOT
            / "src"
            / "omniclaude"
            / "nodes"
            / "node_skill_aislop_sweep_orchestrator"
        )
        assert node_dir.exists(), f"Orchestrator node directory not found: {node_dir}"

    def test_node_files_exist(self) -> None:
        node_dir = (
            _REPO_ROOT
            / "src"
            / "omniclaude"
            / "nodes"
            / "node_skill_aislop_sweep_orchestrator"
        )
        if not node_dir.exists():
            pytest.skip("Node directory not found")
        assert (node_dir / "__init__.py").exists()
        assert (node_dir / "node.py").exists()
        assert (node_dir / "contract.yaml").exists()

    def test_contract_correct_topic(self) -> None:
        contract = (
            _REPO_ROOT
            / "src"
            / "omniclaude"
            / "nodes"
            / "node_skill_aislop_sweep_orchestrator"
            / "contract.yaml"
        )
        if not contract.exists():
            pytest.skip("contract.yaml not found")
        content = contract.read_text()
        assert "aislop-sweep" in content


@pytest.mark.unit
class TestCuratedCorpus:
    def test_sample_slop_exists(self) -> None:
        assert _SAMPLE_SLOP.exists(), f"Sample slop fixture not found: {_SAMPLE_SLOP}"

    def test_prohibited_pattern_detected_in_fixture(self) -> None:
        if not _SAMPLE_SLOP.exists():
            pytest.skip("Sample slop fixture not found")
        content = _SAMPLE_SLOP.read_text()
        assert "ONEX_EVENT_BUS_TYPE" in content
        assert "inmemory" in content

    def test_hardcoded_topic_detected_in_fixture(self) -> None:
        if not _SAMPLE_SLOP.exists():
            pytest.skip("Sample slop fixture not found")
        content = _SAMPLE_SLOP.read_text()
        assert '"onex.' in content

    def test_compat_shim_detected_in_fixture(self) -> None:
        if not _SAMPLE_SLOP.exists():
            pytest.skip("Sample slop fixture not found")
        content = _SAMPLE_SLOP.read_text()
        assert "_unused_" in content

    def test_empty_impl_detected_in_fixture(self) -> None:
        if not _SAMPLE_SLOP.exists():
            pytest.skip("Sample slop fixture not found")
        content = _SAMPLE_SLOP.read_text()
        assert "pass" in content

    def test_hardcoded_path_detected_in_fixture(self) -> None:
        if not _SAMPLE_SLOP.exists():
            pytest.skip("Sample slop fixture not found")
        content = _SAMPLE_SLOP.read_text()
        assert "/Volumes/" in content
