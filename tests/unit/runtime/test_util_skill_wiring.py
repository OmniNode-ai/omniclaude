# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for wire_skill_handlers_only() and bootstrapper models.

Tests:
    1. HandlerGitHub is registered after wiring
    2. HandlerBash is registered after wiring
    3. No DB/Qdrant/Kafka handler is registered (negative test)
    4. HandlerGitHub fails fast if CLAUDE_PLUGIN_ROOT is unset
    5. HandlerBash rejects path traversal with ValueError
    6. SkillContext and SkillResult Pydantic models validate correctly
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from omnibase_core.container import ModelONEXContainer

from plugins.onex.runtime.handlers.handler_bash import HandlerBash
from plugins.onex.runtime.handlers.handler_github import HandlerGitHub
from plugins.onex.runtime.models import SkillContext, SkillResult
from plugins.onex.runtime.util_skill_wiring import wire_skill_handlers_only


@pytest.fixture
def container() -> ModelONEXContainer:
    """Fresh ONEX container for each test."""
    return ModelONEXContainer()


@pytest.fixture
async def wired_container(container: ModelONEXContainer) -> ModelONEXContainer:
    """Container with skill handlers already wired."""
    await wire_skill_handlers_only(container)
    return container


# ---------------------------------------------------------------------------
# Registration tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_github_handler_registered(wired_container: ModelONEXContainer) -> None:
    """HandlerGitHub must be registered after wiring."""
    registry = wired_container.service_registry
    name = HandlerGitHub.__name__
    assert name in registry._name_map, (
        f"HandlerGitHub not found in registry name map. "
        f"Registered names: {list(registry._name_map.keys())}"
    )


@pytest.mark.unit
async def test_bash_handler_registered(wired_container: ModelONEXContainer) -> None:
    """HandlerBash must be registered after wiring."""
    registry = wired_container.service_registry
    name = HandlerBash.__name__
    assert name in registry._name_map, (
        f"HandlerBash not found in registry name map. "
        f"Registered names: {list(registry._name_map.keys())}"
    )


@pytest.mark.unit
async def test_no_db_handler_registered(wired_container: ModelONEXContainer) -> None:
    """No database, Qdrant, or Kafka handler should be registered."""
    registry = wired_container.service_registry
    registered_names = set(registry._name_map.keys())
    forbidden_patterns = {"Database", "Qdrant", "Kafka", "Postgres", "Redis", "Valkey"}
    for name in registered_names:
        for pattern in forbidden_patterns:
            assert pattern.lower() not in name.lower(), (
                f"Forbidden handler {name!r} found in registry "
                f"(matched pattern {pattern!r})"
            )


# ---------------------------------------------------------------------------
# Handler behavior tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_github_handler_fails_without_plugin_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """HandlerGitHub must fail fast if CLAUDE_PLUGIN_ROOT is unset."""
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
    with pytest.raises(RuntimeError, match="CLAUDE_PLUGIN_ROOT not set"):
        HandlerGitHub()


@pytest.mark.unit
async def test_bash_handler_rejects_path_traversal() -> None:
    """HandlerBash must reject path traversal (../) with ValueError."""
    handler = HandlerBash()
    with pytest.raises(ValueError, match="Path traversal detected"):
        await handler.execute("run_script", {"path": "/tmp/../etc/passwd"})


@pytest.mark.unit
async def test_bash_handler_rejects_disallowed_operation() -> None:
    """HandlerBash must reject operations not in the allowlist."""
    handler = HandlerBash()
    with pytest.raises(ValueError, match="not allowed"):
        await handler.execute("delete_everything", {})


# ---------------------------------------------------------------------------
# Model validation tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_skill_context_validates() -> None:
    """SkillContext must validate with all required fields."""
    ctx = SkillContext(
        session_id="test-session",
        skill_name="ci-watch",
        invocation_id=str(uuid4()),
        working_directory="/tmp/test",
    )
    assert ctx.session_id == "test-session"
    assert ctx.skill_name == "ci-watch"
    assert ctx.ticket_id is None
    assert ctx.worktree_path is None


@pytest.mark.unit
def test_skill_context_with_optional_fields() -> None:
    """SkillContext must accept optional fields."""
    ctx = SkillContext(
        session_id="test-session",
        skill_name="ci-watch",
        invocation_id=str(uuid4()),
        working_directory="/tmp/test",
        ticket_id="OMN-1234",
        worktree_path="/tmp/worktree",
    )
    assert ctx.ticket_id == "OMN-1234"
    assert ctx.worktree_path == "/tmp/worktree"


@pytest.mark.unit
def test_skill_result_success() -> None:
    """SkillResult must validate for a successful invocation."""
    result = SkillResult(
        success=True,
        skill_name="ci-watch",
        invocation_id=str(uuid4()),
        output={"checks_passed": True},
        handler_used="HandlerGitHub",
        duration_ms=150,
    )
    assert result.success is True
    assert result.error is None
    assert result.error_type is None
    assert result.output == {"checks_passed": True}
    assert result.runtime_mode == "skill-bootstrapper"


@pytest.mark.unit
def test_skill_result_failure() -> None:
    """SkillResult must validate for a failed invocation."""
    result = SkillResult(
        success=False,
        skill_name="ci-watch",
        invocation_id=str(uuid4()),
        error="Skill not found",
        error_type="SkillNotFoundError",
    )
    assert result.success is False
    assert result.error == "Skill not found"
    assert result.output == {}
