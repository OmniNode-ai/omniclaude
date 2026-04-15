# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Smoke test: skill_shim_audit.yaml is present and structurally valid."""

import os
from pathlib import Path

import pytest
import yaml

OMNI_HOME = Path(os.environ.get("OMNI_HOME", str(Path.home() / "Code" / "omni_home")))
AUDIT_PATH = OMNI_HOME / ".onex_state" / "skill_shim_audit.yaml"

REQUIRED_TOP_KEYS = {
    "audit_date",
    "total_skills",
    "deterministic_count",
    "prose_heavy_count",
    "skills",
}
REQUIRED_SKILL_KEYS = {
    "name",
    "path",
    "invocation_pattern",
    "prose_fallback_lines",
    "llm_sdk_imports",
    "inline_orchestration_flags",
    "classification",
}
VALID_CLASSIFICATIONS = {"deterministic", "prose-heavy"}


@pytest.fixture(scope="module")
def audit() -> dict:
    assert AUDIT_PATH.exists(), f"Audit YAML missing: {AUDIT_PATH}"
    with open(AUDIT_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data


def test_audit_top_level_keys(audit: dict) -> None:
    assert set(audit.keys()) >= REQUIRED_TOP_KEYS


def test_audit_skill_count_nonzero(audit: dict) -> None:
    assert audit["total_skills"] > 0
    assert len(audit["skills"]) == audit["total_skills"]


def test_audit_counts_consistent(audit: dict) -> None:
    skills = audit["skills"]
    assert (
        audit["deterministic_count"] + audit["prose_heavy_count"]
        == audit["total_skills"]
    )
    actual_det = sum(1 for s in skills if s["classification"] == "deterministic")
    actual_ph = sum(1 for s in skills if s["classification"] == "prose-heavy")
    assert actual_det == audit["deterministic_count"]
    assert actual_ph == audit["prose_heavy_count"]


def test_each_skill_has_required_keys(audit: dict) -> None:
    for skill in audit["skills"]:
        missing = REQUIRED_SKILL_KEYS - set(skill.keys())
        assert not missing, f"Skill '{skill.get('name')}' missing keys: {missing}"


def test_each_skill_classification_valid(audit: dict) -> None:
    for skill in audit["skills"]:
        assert skill["classification"] in VALID_CLASSIFICATIONS, (
            f"Skill '{skill['name']}' has invalid classification: {skill['classification']}"
        )


def test_prose_lines_matches_classification(audit: dict) -> None:
    for skill in audit["skills"]:
        if skill["prose_fallback_lines"] <= 50:
            assert skill["classification"] == "deterministic", (
                f"Skill '{skill['name']}': {skill['prose_fallback_lines']} prose lines but classified prose-heavy"
            )
        else:
            assert skill["classification"] == "prose-heavy", (
                f"Skill '{skill['name']}': {skill['prose_fallback_lines']} prose lines but classified deterministic"
            )
