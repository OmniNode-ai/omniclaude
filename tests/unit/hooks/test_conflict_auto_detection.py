# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for file conflict auto-detection in coordination signals (OMN-6861).

Verifies should_emit_conflict_signal() pure function behavior:
- Detects file overlap between tasks
- Returns empty list when no overlap
- Produces deterministic signal_id via uuid5 (Doctrine D6 idempotency)
- Skips self-comparison
- Handles edge cases (empty files, multiple overlaps, multiple other tasks)
"""

from __future__ import annotations

import pytest

from omniclaude.hooks.coordination import (
    ModelFileConflict,
    should_emit_conflict_signal,
)

pytestmark = pytest.mark.unit


class TestShouldEmitConflictSignal:
    """Test file overlap detection between tasks."""

    def test_detects_file_overlap(self) -> None:
        current_task: dict[str, object] = {
            "task_id": "OMN-1234",
            "files_touched": ["src/foo.py", "src/bar.py"],
        }
        other_tasks: list[dict[str, object]] = [
            {"task_id": "OMN-5678", "files_touched": ["src/foo.py", "src/baz.py"]},
        ]
        conflicts = should_emit_conflict_signal(current_task, other_tasks)
        assert len(conflicts) == 1
        assert conflicts[0].other_task_id == "OMN-5678"
        assert "src/foo.py" in conflicts[0].shared_files

    def test_no_overlap_no_signal(self) -> None:
        current_task: dict[str, object] = {
            "task_id": "OMN-1234",
            "files_touched": ["src/foo.py"],
        }
        other_tasks: list[dict[str, object]] = [
            {"task_id": "OMN-5678", "files_touched": ["src/bar.py"]},
        ]
        conflicts = should_emit_conflict_signal(current_task, other_tasks)
        assert conflicts == []

    def test_multiple_shared_files(self) -> None:
        current_task: dict[str, object] = {
            "task_id": "OMN-1234",
            "files_touched": ["src/a.py", "src/b.py", "src/c.py"],
        }
        other_tasks: list[dict[str, object]] = [
            {"task_id": "OMN-5678", "files_touched": ["src/a.py", "src/c.py"]},
        ]
        conflicts = should_emit_conflict_signal(current_task, other_tasks)
        assert len(conflicts) == 1
        assert conflicts[0].shared_files == ["src/a.py", "src/c.py"]

    def test_multiple_conflicting_tasks(self) -> None:
        current_task: dict[str, object] = {
            "task_id": "OMN-1234",
            "files_touched": ["src/foo.py", "src/bar.py"],
        }
        other_tasks: list[dict[str, object]] = [
            {"task_id": "OMN-5678", "files_touched": ["src/foo.py"]},
            {"task_id": "OMN-9999", "files_touched": ["src/bar.py"]},
        ]
        conflicts = should_emit_conflict_signal(current_task, other_tasks)
        assert len(conflicts) == 2
        conflict_ids = {c.other_task_id for c in conflicts}
        assert conflict_ids == {"OMN-5678", "OMN-9999"}

    def test_skips_self_comparison(self) -> None:
        current_task: dict[str, object] = {
            "task_id": "OMN-1234",
            "files_touched": ["src/foo.py"],
        }
        other_tasks: list[dict[str, object]] = [
            {"task_id": "OMN-1234", "files_touched": ["src/foo.py"]},
        ]
        conflicts = should_emit_conflict_signal(current_task, other_tasks)
        assert conflicts == []

    def test_empty_current_files_no_signal(self) -> None:
        current_task: dict[str, object] = {
            "task_id": "OMN-1234",
            "files_touched": [],
        }
        other_tasks: list[dict[str, object]] = [
            {"task_id": "OMN-5678", "files_touched": ["src/foo.py"]},
        ]
        conflicts = should_emit_conflict_signal(current_task, other_tasks)
        assert conflicts == []

    def test_empty_other_tasks(self) -> None:
        current_task: dict[str, object] = {
            "task_id": "OMN-1234",
            "files_touched": ["src/foo.py"],
        }
        conflicts = should_emit_conflict_signal(current_task, [])
        assert conflicts == []

    def test_missing_files_touched_key(self) -> None:
        current_task: dict[str, object] = {"task_id": "OMN-1234"}
        other_tasks: list[dict[str, object]] = [
            {"task_id": "OMN-5678", "files_touched": ["src/foo.py"]},
        ]
        conflicts = should_emit_conflict_signal(current_task, other_tasks)
        assert conflicts == []

    def test_returns_model_file_conflict_instances(self) -> None:
        current_task: dict[str, object] = {
            "task_id": "OMN-1234",
            "files_touched": ["src/foo.py"],
        }
        other_tasks: list[dict[str, object]] = [
            {"task_id": "OMN-5678", "files_touched": ["src/foo.py"]},
        ]
        conflicts = should_emit_conflict_signal(current_task, other_tasks)
        assert len(conflicts) == 1
        assert isinstance(conflicts[0], ModelFileConflict)

    def test_shared_files_are_sorted(self) -> None:
        current_task: dict[str, object] = {
            "task_id": "OMN-1234",
            "files_touched": ["src/z.py", "src/a.py", "src/m.py"],
        }
        other_tasks: list[dict[str, object]] = [
            {"task_id": "OMN-5678", "files_touched": ["src/m.py", "src/a.py"]},
        ]
        conflicts = should_emit_conflict_signal(current_task, other_tasks)
        assert conflicts[0].shared_files == ["src/a.py", "src/m.py"]


class TestConflictSignalIdempotency:
    """Test deterministic signal_id generation (Doctrine D6)."""

    def test_same_conflict_same_signal_id(self) -> None:
        """Identical conflict should produce identical signal_id."""
        current_task: dict[str, object] = {
            "task_id": "OMN-1234",
            "files_touched": ["src/foo.py"],
        }
        other_tasks: list[dict[str, object]] = [
            {"task_id": "OMN-5678", "files_touched": ["src/foo.py"]},
        ]
        conflicts_a = should_emit_conflict_signal(current_task, other_tasks)
        conflicts_b = should_emit_conflict_signal(current_task, other_tasks)
        assert conflicts_a[0].signal_id == conflicts_b[0].signal_id

    def test_reversed_task_order_same_signal_id(self) -> None:
        """A conflicts with B should produce same signal_id as B conflicts with A."""
        task_a: dict[str, object] = {
            "task_id": "OMN-1234",
            "files_touched": ["src/foo.py"],
        }
        task_b: dict[str, object] = {
            "task_id": "OMN-5678",
            "files_touched": ["src/foo.py"],
        }
        conflicts_ab = should_emit_conflict_signal(task_a, [task_b])
        conflicts_ba = should_emit_conflict_signal(task_b, [task_a])
        assert conflicts_ab[0].signal_id == conflicts_ba[0].signal_id

    def test_different_files_different_signal_id(self) -> None:
        """Different shared files should produce different signal_id."""
        current_task: dict[str, object] = {
            "task_id": "OMN-1234",
            "files_touched": ["src/foo.py", "src/bar.py"],
        }
        other_task_foo: list[dict[str, object]] = [
            {"task_id": "OMN-5678", "files_touched": ["src/foo.py"]},
        ]
        other_task_bar: list[dict[str, object]] = [
            {"task_id": "OMN-5678", "files_touched": ["src/bar.py"]},
        ]
        conflicts_foo = should_emit_conflict_signal(current_task, other_task_foo)
        conflicts_bar = should_emit_conflict_signal(current_task, other_task_bar)
        assert conflicts_foo[0].signal_id != conflicts_bar[0].signal_id

    def test_different_other_task_different_signal_id(self) -> None:
        """Different conflicting task should produce different signal_id."""
        current_task: dict[str, object] = {
            "task_id": "OMN-1234",
            "files_touched": ["src/foo.py"],
        }
        other_a: list[dict[str, object]] = [
            {"task_id": "OMN-5678", "files_touched": ["src/foo.py"]},
        ]
        other_b: list[dict[str, object]] = [
            {"task_id": "OMN-9999", "files_touched": ["src/foo.py"]},
        ]
        conflicts_a = should_emit_conflict_signal(current_task, other_a)
        conflicts_b = should_emit_conflict_signal(current_task, other_b)
        assert conflicts_a[0].signal_id != conflicts_b[0].signal_id


class TestModelFileConflict:
    """Test the ModelFileConflict Pydantic model."""

    def test_frozen(self) -> None:
        from uuid import uuid4

        conflict = ModelFileConflict(
            other_task_id="OMN-5678",
            shared_files=["src/foo.py"],
            signal_id=uuid4(),
        )
        with pytest.raises(Exception):
            conflict.other_task_id = "other"  # type: ignore[misc]

    def test_extra_fields_forbidden(self) -> None:
        from uuid import uuid4

        with pytest.raises(Exception):
            ModelFileConflict(
                other_task_id="OMN-5678",
                shared_files=["src/foo.py"],
                signal_id=uuid4(),
                unknown="nope",  # type: ignore[call-arg]
            )
