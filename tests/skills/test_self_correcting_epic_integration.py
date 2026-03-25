#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Integration tests: structural validation for P2 initiative skills (self-correcting epic, ci-recovery, review-gate)."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[2] / "plugins" / "onex"


@pytest.mark.unit
class TestSelfCorrectingEpicStructure:
    """Verify self-correcting-epic skill has all required files."""

    def test_skill_md_exists(self) -> None:
        """SKILL.md file exists for self-correcting-epic."""
        skill_path = PLUGIN_ROOT / "skills" / "self_correcting_epic" / "SKILL.md"
        assert skill_path.exists(), f"Missing: {skill_path}"

    def test_prompt_md_exists(self) -> None:
        """prompt.md file exists for self-correcting-epic."""
        prompt_path = PLUGIN_ROOT / "skills" / "self_correcting_epic" / "prompt.md"
        assert prompt_path.exists(), f"Missing: {prompt_path}"

    def test_topics_yaml_exists(self) -> None:
        """topics.yaml file exists for self-correcting-epic."""
        topics_path = PLUGIN_ROOT / "skills" / "self_correcting_epic" / "topics.yaml"
        assert topics_path.exists(), f"Missing: {topics_path}"

    def test_preflight_gate_script_executable(self) -> None:
        """epic_preflight_gate.sh exists and is executable."""
        script = PLUGIN_ROOT / "hooks" / "scripts" / "epic_preflight_gate.sh"
        assert script.exists(), f"Missing: {script}"
        assert os.access(script, os.X_OK), f"Not executable: {script}"

    def test_postaction_gate_script_executable(self) -> None:
        """epic_postaction_gate.sh exists and is executable."""
        script = PLUGIN_ROOT / "hooks" / "scripts" / "epic_postaction_gate.sh"
        assert script.exists(), f"Missing: {script}"
        assert os.access(script, os.X_OK), f"Not executable: {script}"


@pytest.mark.unit
class TestCIRecoveryStructure:
    """Verify ci-recovery skill has all required files and the classifier is importable."""

    def test_skill_md_exists(self) -> None:
        """SKILL.md file exists for ci-recovery."""
        skill_path = PLUGIN_ROOT / "skills" / "ci_recovery" / "SKILL.md"
        assert skill_path.exists(), f"Missing: {skill_path}"

    def test_classifier_importable(self) -> None:
        """CI failure classifier module is importable and exports classify_ci_failure."""
        spec = importlib.util.spec_from_file_location(
            "classifier",
            PLUGIN_ROOT / "skills" / "_lib" / "ci_recovery" / "classifier.py",
        )
        assert spec is not None
        assert spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert hasattr(mod, "classify_ci_failure")


@pytest.mark.unit
class TestReviewGateStructure:
    """Verify review-gate skill has all required files and the aggregator is importable."""

    def test_skill_md_exists(self) -> None:
        """SKILL.md file exists for review-gate."""
        skill_path = PLUGIN_ROOT / "skills" / "review_gate" / "SKILL.md"
        assert skill_path.exists(), f"Missing: {skill_path}"

    def test_aggregator_importable(self) -> None:
        """Review gate aggregator module is importable and exports aggregate_verdicts."""
        spec = importlib.util.spec_from_file_location(
            "aggregator",
            PLUGIN_ROOT / "skills" / "_lib" / "review_gate" / "aggregator.py",
        )
        assert spec is not None
        assert spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert hasattr(mod, "aggregate_verdicts")
