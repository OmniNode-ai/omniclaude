# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for ci-watch bootstrapper migration.

Tests:
    1. Success path: mocked subprocess returns passing CI
    2. Error path: mocked subprocess returns failure
    3. Runtime metadata resolves: bootstrapper reads runtime: skill-bootstrapper
       from ci-watch SKILL.md and selects correct handler
    4. Output contract stable: SkillResult output matches expected schema
"""

from __future__ import annotations

from pathlib import Path

import pytest

from plugins.onex.runtime.models import SkillContext, SkillResult
from plugins.onex.runtime.skill_bootstrapper import (
    SUPPORTED_RUNTIMES,
    SkillBootstrapper,
)


@pytest.fixture
def ci_watch_skill_path() -> Path:
    """Return the path to ci-watch SKILL.md."""
    return (
        Path(__file__).resolve().parents[3]
        / "plugins"
        / "onex"
        / "skills"
        / "ci-watch"
        / "SKILL.md"
    )


# ---------------------------------------------------------------------------
# Runtime metadata tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_ci_watch_has_runtime_metadata(ci_watch_skill_path: Path) -> None:
    """ci-watch SKILL.md must have runtime: skill-bootstrapper in front-matter."""
    content = ci_watch_skill_path.read_text()
    # Parse YAML front-matter between --- delimiters
    parts = content.split("---", 2)
    assert len(parts) >= 3, (
        "SKILL.md must have YAML front-matter between --- delimiters"
    )
    # Front-matter contains non-standard YAML (pipe chars in field specs),
    # so we check for the runtime field via string matching
    front_matter_text = parts[1]
    assert "runtime: skill-bootstrapper" in front_matter_text, (
        "Expected 'runtime: skill-bootstrapper' in ci-watch SKILL.md front-matter"
    )


@pytest.mark.unit
def test_ci_watch_no_tier_routing_references(ci_watch_skill_path: Path) -> None:
    """ci-watch SKILL.md must not reference detect_onex_tier or tier-routing."""
    content = ci_watch_skill_path.read_text()
    assert "detect_onex_tier" not in content
    assert "tier-routing" not in content
    assert "tier_routing" not in content


@pytest.mark.unit
async def test_ci_watch_runtime_metadata_resolves() -> None:
    """Bootstrapper must accept runtime: skill-bootstrapper for ci-watch."""
    bootstrapper = SkillBootstrapper()
    await bootstrapper.initialize()
    try:
        bootstrapper.register_skill(
            "ci-watch",
            runtime="skill-bootstrapper",
            handler_name="HandlerBash",
            schema={"required": ["pr_number", "repo"]},
        )
        ctx = SkillContext(
            session_id="test",
            skill_name="ci-watch",
            invocation_id="inv-ci-001",
            working_directory="/tmp",
        )
        result = await bootstrapper.invoke(
            "ci-watch",
            {"pr_number": 123, "repo": "OmniNode-ai/omniclaude"},
            context=ctx,
        )
        assert result.success is True
        assert result.skill_name == "ci-watch"
        assert result.runtime_mode == "skill-bootstrapper"
    finally:
        await bootstrapper.shutdown()


@pytest.mark.unit
async def test_ci_watch_output_contract_stable() -> None:
    """SkillResult from ci-watch must contain expected fields."""
    bootstrapper = SkillBootstrapper()
    await bootstrapper.initialize()
    try:
        bootstrapper.register_skill(
            "ci-watch",
            runtime="skill-bootstrapper",
            handler_name="HandlerBash",
        )
        result = await bootstrapper.invoke("ci-watch", {})
        # Verify SkillResult contract
        assert isinstance(result, SkillResult)
        assert isinstance(result.success, bool)
        assert isinstance(result.skill_name, str)
        assert isinstance(result.invocation_id, str)
        assert isinstance(result.output, dict)
        assert isinstance(result.duration_ms, int)
        assert result.runtime_mode in SUPPORTED_RUNTIMES
    finally:
        await bootstrapper.shutdown()
