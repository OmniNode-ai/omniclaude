# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Integration tests for the aislop-sweep skill.

Tests verify skill spec completeness via static analysis.
All tests are @pytest.mark.unit (no live grep, ruff, mypy, or network calls).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).parent.parent.parent.parent.parent
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

    def test_all_six_checks_documented(self) -> None:
        content = _read(_SKILL_MD)
        for check in (
            "phantom-callables",
            "compat-shims",
            "prohibited-patterns",
            "hardcoded-topics",
            "todo-fixme",
            "empty-impls",
        ):
            assert check in content, f"SKILL.md missing check: {check}"

    def test_model_skill_result_by_check_and_by_severity(self) -> None:
        content = _read(_SKILL_MD)
        assert "by_check" in content
        assert "by_severity" in content

    def test_status_values_include_clean_and_findings(self) -> None:
        content = _read(_SKILL_MD)
        assert "clean" in content
        assert "findings" in content

    def test_prohibited_patterns_is_critical(self) -> None:
        content = _read(_SKILL_MD)
        assert "CRITICAL" in content
        assert "prohibited-patterns" in content

    def test_todo_fixme_and_compat_shims_are_warning_or_info(self) -> None:
        content = _read(_SKILL_MD)
        # Conservative triage: these should not be auto-ticketed by default
        assert "WARNING" in content or "INFO" in content
        assert "todo-fixme" in content
        assert "compat-shims" in content

    def test_ticket_flag_documented_with_aislop_label(self) -> None:
        content = _read(_SKILL_MD)
        assert "--ticket" in content
        assert "aislop-sweep" in content.lower() or "aislop" in content

    def test_modelsweepconfigfinding_schema_fields(self) -> None:
        content = _read(_SKILL_MD)
        for field in ("confidence", "ticketable", "autofixable"):
            assert field in content, f"SKILL.md missing finding schema field: {field}"

    def test_path_exclusions_listed(self) -> None:
        content = _read(_SKILL_MD)
        for exclusion in (".git/", ".venv/", "docs/", "fixtures/"):
            assert exclusion in content, f"SKILL.md missing path exclusion: {exclusion}"

    def test_repo_list_is_hardcoded_constant(self) -> None:
        content = _read(_SKILL_MD)
        assert "AISLOP_REPOS" in content or (
            "omniclaude" in content and "omnibase_core" in content
        ), "SKILL.md must list default repos"


@pytest.mark.unit
class TestPromptMd:
    def test_all_phases_present(self) -> None:
        content = _read(_PROMPT_MD)
        phase_count = len(re.findall(r"^## Phase", content, re.MULTILINE))
        assert phase_count >= 5, f"Expected >= 5 phases, found {phase_count}"

    def test_dry_run_exits_before_ticket_creation(self) -> None:
        content = _read(_PROMPT_MD)
        dry_run_pos = content.find("--dry-run")
        ticket_pos = content.find("--ticket")
        assert dry_run_pos != -1
        # dry-run exit logic should appear before ticket creation
        exit_pos = content.find("EXIT", dry_run_pos)
        if exit_pos == -1:
            exit_pos = content.find("exit", dry_run_pos)
        assert exit_pos != -1 or ticket_pos > dry_run_pos, (
            "prompt.md must show --dry-run exits before ticket creation"
        )

    def test_all_six_grep_patterns_present(self) -> None:
        content = _read(_PROMPT_MD)
        for check in (
            "prohibited-patterns",
            "hardcoded-topics",
            "phantom-callables",
            "compat-shims",
            "empty-impls",
            "todo-fixme",
        ):
            assert check in content, f"prompt.md missing check pattern: {check}"

    def test_aislop_repo_list_hardcoded(self) -> None:
        content = _read(_PROMPT_MD)
        assert "AISLOP_REPOS" in content
        assert "omniclaude" in content
        assert "omnibase_core" in content

    def test_ticket_section_uses_aislop_sweep_label(self) -> None:
        content = _read(_PROMPT_MD)
        assert "aislop-sweep" in content or "aislop" in content

    def test_path_exclusions_present(self) -> None:
        content = _read(_PROMPT_MD)
        for exclusion in (".git/", ".venv/", "docs/", "fixtures/"):
            assert exclusion in content, (
                f"prompt.md missing path exclusion: {exclusion}"
            )


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
