# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for CorrelationRegistry task hierarchy (OMN-5235).

Validates:
- task_stack and task_dispatches persisted state
- push_task / pop_task lifecycle semantics
- current_task_id and parent_task_id properties
- Duplicate push rejection with DuplicateTaskError
- Event emission ordering (emit before state mutation)
- TTL cleanup of expired dispatch records
- Crash recovery scenario (push without pop)
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from plugins.onex.hooks.lib.correlation_manager import (
    CorrelationRegistry,
    DuplicateTaskError,
)

# All tests in this module are unit tests
pytestmark = pytest.mark.unit


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def state_dir(tmp_path: Path) -> Path:
    """Provide a temporary state directory."""
    d = tmp_path / "state"
    d.mkdir()
    return d


@pytest.fixture
def mock_emit() -> MagicMock:
    """Provide a mock emit function."""
    return MagicMock(return_value=True)


@pytest.fixture
def registry(state_dir: Path, mock_emit: MagicMock) -> CorrelationRegistry:
    """Create a CorrelationRegistry with a temp state dir and mock emit."""
    return CorrelationRegistry(state_dir=state_dir, emit_fn=mock_emit)


@pytest.fixture
def registry_no_emit(state_dir: Path) -> CorrelationRegistry:
    """Create a CorrelationRegistry without an emit function."""
    return CorrelationRegistry(state_dir=state_dir)


# =============================================================================
# State Initialization
# =============================================================================


class TestStateInitialization:
    """Verify task hierarchy fields exist in persisted state."""

    def test_fresh_registry_has_empty_stack(
        self, registry: CorrelationRegistry
    ) -> None:
        """A fresh registry has an empty task stack."""
        assert registry.task_stack == []

    def test_fresh_registry_has_empty_dispatches(
        self, registry: CorrelationRegistry
    ) -> None:
        """A fresh registry has no dispatch metadata."""
        assert registry.task_dispatches == {}

    def test_current_task_id_none_when_empty(
        self, registry: CorrelationRegistry
    ) -> None:
        """current_task_id is None when no tasks pushed."""
        assert registry.current_task_id is None

    def test_parent_task_id_none_when_empty(
        self, registry: CorrelationRegistry
    ) -> None:
        """parent_task_id is None when no tasks pushed."""
        assert registry.parent_task_id is None

    def test_set_correlation_preserves_task_fields(
        self, registry: CorrelationRegistry
    ) -> None:
        """set_correlation_id initializes task_stack and task_dispatches."""
        registry.set_correlation_id("corr-1", agent_name="test-agent")
        ctx = registry.get_correlation_context()
        assert ctx is not None
        assert ctx["task_stack"] == []
        assert ctx["task_dispatches"] == {}


# =============================================================================
# Push Task
# =============================================================================


class TestPushTask:
    """Tests for push_task lifecycle."""

    def test_push_single_task(self, registry: CorrelationRegistry) -> None:
        """Pushing a single task puts it on the stack."""
        registry.push_task("task-001", "contract-a")
        assert registry.current_task_id == "task-001"
        assert registry.parent_task_id is None
        assert registry.task_stack == ["task-001"]

    def test_push_records_dispatch_metadata(
        self, registry: CorrelationRegistry
    ) -> None:
        """push_task records dispatch metadata with expected fields."""
        registry.push_task(
            "task-001", "contract-a", scopes={"tool_scope": ["Bash", "Read"]}
        )
        dispatches = registry.task_dispatches
        assert "task-001" in dispatches
        meta = dispatches["task-001"]
        assert meta["task_id"] == "task-001"
        assert meta["contract_id"] == "contract-a"
        assert meta["parent_task_id"] is None
        assert meta["scopes"] == {"tool_scope": ["Bash", "Read"]}
        assert meta["pushed_at"] is not None
        assert meta["completed_at"] is None

    def test_push_nested_tasks(self, registry: CorrelationRegistry) -> None:
        """Pushing multiple tasks creates a proper parent-child chain."""
        registry.push_task("task-001", "contract-a")
        registry.push_task("task-002", "contract-b")

        assert registry.current_task_id == "task-002"
        assert registry.parent_task_id == "task-001"
        assert registry.task_stack == ["task-001", "task-002"]

        # Child dispatch should reference parent
        dispatches = registry.task_dispatches
        assert dispatches["task-002"]["parent_task_id"] == "task-001"

    def test_push_three_levels(self, registry: CorrelationRegistry) -> None:
        """Three-level nesting is supported."""
        registry.push_task("root", "c-root")
        registry.push_task("child", "c-child")
        registry.push_task("grandchild", "c-gc")

        assert registry.task_stack == ["root", "child", "grandchild"]
        assert registry.current_task_id == "grandchild"
        assert registry.parent_task_id == "child"

    def test_push_with_default_scopes(self, registry: CorrelationRegistry) -> None:
        """Scopes default to empty dict when not provided."""
        registry.push_task("task-001", "contract-a")
        assert registry.task_dispatches["task-001"]["scopes"] == {}


# =============================================================================
# Pop Task
# =============================================================================


class TestPopTask:
    """Tests for pop_task lifecycle."""

    def test_pop_returns_task_id(self, registry: CorrelationRegistry) -> None:
        """pop_task returns the popped task_id."""
        registry.push_task("task-001", "contract-a")
        result = registry.pop_task()
        assert result == "task-001"

    def test_pop_removes_from_stack(self, registry: CorrelationRegistry) -> None:
        """pop_task removes the task from the stack."""
        registry.push_task("task-001", "contract-a")
        registry.pop_task()
        assert registry.task_stack == []
        assert registry.current_task_id is None

    def test_pop_sets_completed_at(self, registry: CorrelationRegistry) -> None:
        """pop_task sets completed_at in dispatch metadata."""
        registry.push_task("task-001", "contract-a")
        registry.pop_task()

        # Metadata stays (until TTL)
        dispatches = registry.task_dispatches
        assert "task-001" in dispatches
        assert dispatches["task-001"]["completed_at"] is not None

    def test_pop_empty_stack_returns_none(self, registry: CorrelationRegistry) -> None:
        """pop_task on empty stack returns None."""
        assert registry.pop_task() is None

    def test_pop_nested_reveals_parent(self, registry: CorrelationRegistry) -> None:
        """Popping child task reveals parent as current."""
        registry.push_task("task-001", "contract-a")
        registry.push_task("task-002", "contract-b")

        registry.pop_task()  # pops task-002
        assert registry.current_task_id == "task-001"
        assert registry.parent_task_id is None

    def test_pop_preserves_dispatch_metadata(
        self, registry: CorrelationRegistry
    ) -> None:
        """Dispatch metadata for popped task stays until TTL."""
        registry.push_task("task-001", "contract-a")
        registry.push_task("task-002", "contract-b")
        registry.pop_task()

        # Both dispatch records remain
        dispatches = registry.task_dispatches
        assert "task-001" in dispatches
        assert "task-002" in dispatches


# =============================================================================
# Duplicate Push Rejection
# =============================================================================


class TestDuplicatePush:
    """Tests for duplicate task push rejection."""

    def test_duplicate_push_raises(self, registry: CorrelationRegistry) -> None:
        """Pushing the same task_id twice raises DuplicateTaskError."""
        registry.push_task("task-001", "contract-a")
        with pytest.raises(DuplicateTaskError, match="task-001"):
            registry.push_task("task-001", "contract-b")

    def test_duplicate_push_emits_violation_event(
        self, registry: CorrelationRegistry, mock_emit: MagicMock
    ) -> None:
        """Duplicate push emits audit.scope.violation event."""
        registry.push_task("task-001", "contract-a")
        mock_emit.reset_mock()

        with pytest.raises(DuplicateTaskError):
            registry.push_task("task-001", "contract-b")

        # Should have emitted a violation event
        mock_emit.assert_called_once()
        call_args = mock_emit.call_args
        assert call_args[0][0] == "audit.scope.violation"
        payload = call_args[0][1]
        assert payload["task_id"] == "task-001"
        assert payload["violation"] == "duplicate_push"

    def test_duplicate_push_does_not_modify_stack(
        self, registry: CorrelationRegistry
    ) -> None:
        """Stack remains unchanged after a duplicate push attempt."""
        registry.push_task("task-001", "contract-a")

        with pytest.raises(DuplicateTaskError):
            registry.push_task("task-001", "contract-b")

        assert registry.task_stack == ["task-001"]


# =============================================================================
# Event Emission
# =============================================================================


class TestEventEmission:
    """Tests for event emission during task lifecycle."""

    def test_push_emits_dispatch_validated(
        self, registry: CorrelationRegistry, mock_emit: MagicMock
    ) -> None:
        """push_task emits audit.dispatch.validated event."""
        registry.push_task("task-001", "contract-a", scopes={"tool_scope": ["Bash"]})

        mock_emit.assert_called_once()
        call_args = mock_emit.call_args
        assert call_args[0][0] == "audit.dispatch.validated"
        payload = call_args[0][1]
        assert payload["task_id"] == "task-001"
        assert payload["contract_id"] == "contract-a"
        assert payload["scopes"] == {"tool_scope": ["Bash"]}
        assert payload["parent_task_id"] is None

    def test_push_child_emits_with_parent(
        self, registry: CorrelationRegistry, mock_emit: MagicMock
    ) -> None:
        """Child push includes parent_task_id in event."""
        registry.push_task("task-001", "contract-a")
        mock_emit.reset_mock()

        registry.push_task("task-002", "contract-b")
        payload = mock_emit.call_args[0][1]
        assert payload["parent_task_id"] == "task-001"

    def test_emit_before_state_mutation(self, state_dir: Path) -> None:
        """Event is emitted BEFORE the state file is updated.

        This verifies the durability-first invariant: if the process
        crashes after emit but before file write, the event survives.
        """
        call_order: list[str] = []
        correlation_file = state_dir / "correlation_id.json"

        def tracking_emit(event_type: str, payload: dict[str, Any]) -> bool:
            # Read the file at the time of emit to see if stack was already mutated
            if correlation_file.exists():
                with open(correlation_file, encoding="utf-8") as f:
                    state = json.load(f)
                stack = state.get("task_stack", [])
                if "task-001" in stack:
                    call_order.append("emit_after_mutation")
                else:
                    call_order.append("emit_before_mutation")
            else:
                call_order.append("emit_before_mutation")
            return True

        reg = CorrelationRegistry(state_dir=state_dir, emit_fn=tracking_emit)
        reg.push_task("task-001", "contract-a")

        assert call_order == ["emit_before_mutation"]

    def test_no_emit_fn_does_not_raise(
        self, registry_no_emit: CorrelationRegistry
    ) -> None:
        """push_task works without an emit function (events silently dropped)."""
        registry_no_emit.push_task("task-001", "contract-a")
        assert registry_no_emit.current_task_id == "task-001"

    def test_emit_failure_does_not_block_push(self, state_dir: Path) -> None:
        """If emit raises, push_task still succeeds."""
        failing_emit = MagicMock(side_effect=RuntimeError("daemon crash"))
        reg = CorrelationRegistry(state_dir=state_dir, emit_fn=failing_emit)

        reg.push_task("task-001", "contract-a")
        assert reg.current_task_id == "task-001"


# =============================================================================
# TTL Cleanup
# =============================================================================


class TestTTLCleanup:
    """Tests for TTL-based cleanup of task dispatch records."""

    def test_expired_dispatches_cleaned_on_push(
        self, state_dir: Path, mock_emit: MagicMock
    ) -> None:
        """Expired dispatch records are removed when push_task runs."""
        reg = CorrelationRegistry(state_dir=state_dir, emit_fn=mock_emit)

        # Manually inject an expired dispatch
        state: dict[str, Any] = {
            "task_stack": [],
            "task_dispatches": {
                "old-task": {
                    "task_id": "old-task",
                    "pushed_at_epoch": time.time() - 7200,  # 2 hours ago
                    "completed_at": "2025-01-01T00:00:00+00:00",
                },
            },
        }
        with open(state_dir / "correlation_id.json", "w") as f:
            json.dump(state, f)

        # Push a new task -- should clean up expired
        reg.push_task("task-new", "contract-a")

        dispatches = reg.task_dispatches
        assert "old-task" not in dispatches
        assert "task-new" in dispatches

    def test_fresh_dispatches_not_cleaned(
        self, state_dir: Path, mock_emit: MagicMock
    ) -> None:
        """Non-expired dispatch records are preserved."""
        reg = CorrelationRegistry(state_dir=state_dir, emit_fn=mock_emit)

        # Inject a fresh dispatch
        state: dict[str, Any] = {
            "task_stack": ["recent-task"],
            "task_dispatches": {
                "recent-task": {
                    "task_id": "recent-task",
                    "pushed_at_epoch": time.time() - 60,  # 1 minute ago
                    "completed_at": None,
                },
            },
        }
        with open(state_dir / "correlation_id.json", "w") as f:
            json.dump(state, f)

        # Pop and push new
        reg2 = CorrelationRegistry(state_dir=state_dir, emit_fn=mock_emit)
        result = reg2.pop_task()
        assert result == "recent-task"
        reg2.push_task("task-new", "contract-a")

        dispatches = reg2.task_dispatches
        assert "recent-task" in dispatches
        assert "task-new" in dispatches


# =============================================================================
# Crash Recovery
# =============================================================================


class TestCrashRecovery:
    """Tests for crash recovery scenarios."""

    def test_push_without_pop_persists(
        self, state_dir: Path, mock_emit: MagicMock
    ) -> None:
        """If process crashes after push (no pop), state survives on disk."""
        reg1 = CorrelationRegistry(state_dir=state_dir, emit_fn=mock_emit)
        reg1.push_task("task-001", "contract-a")

        # Simulate crash: create a new registry instance from same state dir
        reg2 = CorrelationRegistry(state_dir=state_dir, emit_fn=mock_emit)
        assert reg2.current_task_id == "task-001"
        assert reg2.task_dispatches["task-001"]["completed_at"] is None

    def test_recovery_allows_pop(self, state_dir: Path, mock_emit: MagicMock) -> None:
        """After crash recovery, the orphaned task can still be popped."""
        reg1 = CorrelationRegistry(state_dir=state_dir, emit_fn=mock_emit)
        reg1.push_task("task-001", "contract-a")

        # New instance (simulating process restart)
        reg2 = CorrelationRegistry(state_dir=state_dir, emit_fn=mock_emit)
        result = reg2.pop_task()
        assert result == "task-001"
        assert reg2.current_task_id is None
        assert reg2.task_dispatches["task-001"]["completed_at"] is not None


# =============================================================================
# Interaction with Existing Correlation API
# =============================================================================


class TestCorrelationInteraction:
    """Tests verifying task hierarchy coexists with existing correlation state."""

    def test_set_correlation_preserves_existing_tasks(
        self, registry: CorrelationRegistry
    ) -> None:
        """set_correlation_id does not wipe task state."""
        registry.push_task("task-001", "contract-a")
        registry.set_correlation_id("corr-new", agent_name="new-agent")

        assert registry.current_task_id == "task-001"
        assert registry.task_dispatches["task-001"]["contract_id"] == "contract-a"

    def test_clear_removes_task_state(self, registry: CorrelationRegistry) -> None:
        """clear() removes all state including task hierarchy."""
        registry.push_task("task-001", "contract-a")
        registry.clear()

        assert registry.current_task_id is None
        assert registry.task_stack == []
        assert registry.task_dispatches == {}

    def test_get_context_includes_task_fields(
        self, registry: CorrelationRegistry
    ) -> None:
        """get_correlation_context returns task_stack and task_dispatches."""
        registry.set_correlation_id("corr-1")
        registry.push_task("task-001", "contract-a")

        ctx = registry.get_correlation_context()
        assert ctx is not None
        assert "task_stack" in ctx
        assert "task_dispatches" in ctx
        assert ctx["task_stack"] == ["task-001"]
