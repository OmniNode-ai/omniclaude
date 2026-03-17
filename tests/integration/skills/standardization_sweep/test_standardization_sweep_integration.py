# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Integration tests for the standardization-sweep skill.

Tests verify skill spec completeness via static analysis.
All tests are @pytest.mark.unit (no live ruff, mypy, or network calls).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).parent.parent.parent.parent.parent
_SKILLS_ROOT = _REPO_ROOT / "plugins" / "onex" / "skills"
_STD_SWEEP_DIR = _SKILLS_ROOT / "standardization-sweep"
_SKILL_MD = _STD_SWEEP_DIR / "SKILL.md"
_PROMPT_MD = _STD_SWEEP_DIR / "prompt.md"
_TOPICS_YAML = _STD_SWEEP_DIR / "topics.yaml"
_GOLDEN_PATH_DIR = _SKILLS_ROOT / "_golden_path_validate"
_FIXTURE_JSON = _GOLDEN_PATH_DIR / "node_skill_standardization_sweep_orchestrator.json"


def _read(path: Path) -> str:
    if not path.exists():
        pytest.skip(f"File not found: {path}")
    return path.read_text(encoding="utf-8")


@pytest.mark.unit
class TestSkillMd:
    def test_dry_run_documented(self) -> None:
        content = _read(_SKILL_MD)
        assert "--dry-run" in content

    def test_all_five_checks_documented(self) -> None:
        content = _read(_SKILL_MD)
        for check in ("ruff", "mypy", "spdx", "type-unions", "pip-usage"):
            assert check in content, f"SKILL.md missing check: {check}"

    def test_all_check_commands_present(self) -> None:
        content = _read(_SKILL_MD)
        assert "uv run ruff check" in content
        assert "uv run mypy" in content
        assert "onex spdx fix" in content
        assert "Optional" in content

    def test_model_skill_result_status_values(self) -> None:
        content = _read(_SKILL_MD)
        for status in ("clean", "violations_found", "partial", "error"):
            assert status in content, f"SKILL.md missing status value: {status}"

    def test_python_repos_listed(self) -> None:
        content = _read(_SKILL_MD)
        for repo in ("omniclaude", "omnibase_core", "omnibase_infra"):
            assert repo in content, f"SKILL.md missing repo: {repo}"

    def test_algorithm_numbered_steps(self) -> None:
        content = _read(_SKILL_MD)
        assert "1. PARSE" in content or "1." in content


@pytest.mark.unit
class TestPromptMd:
    def test_all_phases_present(self) -> None:
        content = _read(_PROMPT_MD)
        phase_count = len(re.findall(r"^## Phase", content, re.MULTILINE))
        assert phase_count >= 5, f"Expected >= 5 phases, found {phase_count}"

    def test_dry_run_exits_before_fix_dispatch(self) -> None:
        content = _read(_PROMPT_MD)
        dry_run_pos = content.find("--dry-run")
        dispatch_pos = content.find("DISPATCH")
        assert dry_run_pos != -1, "prompt.md must reference --dry-run"
        assert dispatch_pos != -1, "prompt.md must reference DISPATCH"
        assert dry_run_pos < dispatch_pos, "--dry-run must appear before fix dispatch"

    def test_python_repo_list_hardcoded(self) -> None:
        content = _read(_PROMPT_MD)
        assert "PYTHON_REPOS" in content, "Repo list must be a hardcoded constant PYTHON_REPOS"
        assert "omniclaude" in content
        assert "omnibase_core" in content

    def test_all_check_commands_present(self) -> None:
        content = _read(_PROMPT_MD)
        assert "uv run ruff check" in content
        assert "uv run mypy" in content
        assert "onex spdx fix" in content

    def test_auto_fix_before_dispatch(self) -> None:
        content = _read(_PROMPT_MD)
        auto_fix_pos = content.find("Auto-Fix")
        dispatch_pos = content.find("Fix Agent Dispatch")
        if auto_fix_pos != -1 and dispatch_pos != -1:
            assert auto_fix_pos < dispatch_pos, "--auto-fix phase must precede fix-agent dispatch"

    def test_path_exclusions_present(self) -> None:
        content = _read(_PROMPT_MD)
        for exclusion in (".git/", ".venv/", "docs/", "fixtures/"):
            assert exclusion in content, f"prompt.md missing path exclusion: {exclusion}"


@pytest.mark.unit
class TestTopicsYaml:
    def test_exactly_three_topics(self) -> None:
        content = _read(_TOPICS_YAML)
        topics = [line.strip().lstrip("- ") for line in content.splitlines() if line.strip().startswith("- onex.")]
        assert len(topics) == 3, f"Expected 3 topics, found {len(topics)}: {topics}"

    def test_topic_naming_convention(self) -> None:
        content = _read(_TOPICS_YAML)
        assert "onex.cmd.omniclaude.standardization-sweep.v1" in content
        assert "onex.evt.omniclaude.standardization-sweep-completed.v1" in content
        assert "onex.evt.omniclaude.standardization-sweep-failed.v1" in content

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
        assert data["input"]["topic"] == "onex.cmd.omniclaude.standardization-sweep.v1"
        assert data["output"]["topic"] == "onex.evt.omniclaude.standardization-sweep-completed.v1"

    def test_fixture_has_dry_run(self) -> None:
        if not _FIXTURE_JSON.exists():
            pytest.skip("Fixture not found")
        data = json.loads(_FIXTURE_JSON.read_text())
        args = data["input"]["fixture"].get("args", {})
        assert args.get("--dry-run") is True


@pytest.mark.unit
class TestOrchestratorNode:
    def test_node_directory_exists(self) -> None:
        node_dir = _REPO_ROOT / "src" / "omniclaude" / "nodes" / "node_skill_standardization_sweep_orchestrator"
        assert node_dir.exists(), f"Orchestrator node directory not found: {node_dir}"

    def test_node_files_exist(self) -> None:
        node_dir = _REPO_ROOT / "src" / "omniclaude" / "nodes" / "node_skill_standardization_sweep_orchestrator"
        if not node_dir.exists():
            pytest.skip("Node directory not found")
        assert (node_dir / "__init__.py").exists()
        assert (node_dir / "node.py").exists()
        assert (node_dir / "contract.yaml").exists()

    def test_contract_correct_topic(self) -> None:
        contract = _REPO_ROOT / "src" / "omniclaude" / "nodes" / "node_skill_standardization_sweep_orchestrator" / "contract.yaml"
        if not contract.exists():
            pytest.skip("contract.yaml not found")
        content = contract.read_text()
        assert "standardization-sweep" in content
