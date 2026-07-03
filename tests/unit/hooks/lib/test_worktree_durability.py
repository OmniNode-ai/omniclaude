# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for the worktree durability sweep helpers (OMN-13044).

Validates the pure, no-I/O detection functions and the durability flags model
that back the worktree skill's durability sweep:

- NO-TICKET detection (directory name carries no OMN-NNNN identifier)
- dirty-plan-file detection (unstaged changes to plan/handoff-referenced files)
- rescue-ref construction (rescue/<ticket>/<timestamp> tag, created on block)
- off-volume backup requirement (ticket attachment or docs-branch commit)
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from omniclaude.hooks.lib.worktree_health import (
    RESCUE_REF_PREFIX,
    ModelWorktreeDurabilityFlags,
    build_rescue_ref,
    extract_ticket_id,
    is_no_ticket_worktree,
    offvolume_backup_satisfied,
    plan_referenced_dirty_files,
)

pytestmark = pytest.mark.unit


# =============================================================================
# NO-TICKET detection
# =============================================================================


class TestExtractTicketId:
    def test_extracts_ticket_from_worktree_path(self) -> None:
        path = "/wt/omni_worktrees/OMN-13044/omniclaude"
        assert extract_ticket_id(path) == "OMN-13044"

    def test_extracts_lowercase_branch_style_id(self) -> None:
        # Linear branch names lowercase the ticket; detection is case-insensitive
        assert extract_ticket_id("omni_worktrees/omn-1234/omnibase_core") == "OMN-1234"

    def test_returns_none_when_no_ticket_in_path(self) -> None:
        assert extract_ticket_id("/tmp/omni_worktrees/scratch-fix/omniclaude") is None

    def test_returns_first_ticket_when_multiple(self) -> None:
        assert extract_ticket_id("OMN-1/nested/OMN-2") == "OMN-1"


class TestIsNoTicketWorktree:
    def test_true_when_no_ticket(self) -> None:
        assert is_no_ticket_worktree("omni_worktrees/scratch/omniclaude") is True

    def test_false_when_ticket_present(self) -> None:
        assert is_no_ticket_worktree("omni_worktrees/OMN-13044/omniclaude") is False


# =============================================================================
# dirty-plan-file detection
# =============================================================================


class TestPlanReferencedDirtyFiles:
    def test_returns_overlap_sorted(self) -> None:
        changed = ["src/b.py", "src/a.py", "README.md"]
        referenced = ["src/a.py", "src/b.py", "docs/x.md"]
        assert plan_referenced_dirty_files(changed, referenced) == (
            "src/a.py",
            "src/b.py",
        )

    def test_empty_when_no_overlap(self) -> None:
        assert plan_referenced_dirty_files(["src/a.py"], ["src/b.py"]) == ()

    def test_empty_when_nothing_changed(self) -> None:
        assert plan_referenced_dirty_files([], ["src/a.py"]) == ()

    def test_deduplicates(self) -> None:
        assert plan_referenced_dirty_files(["src/a.py", "src/a.py"], ["src/a.py"]) == (
            "src/a.py",
        )


# =============================================================================
# rescue-ref construction
# =============================================================================


class TestBuildRescueRef:
    def test_builds_namespaced_tag(self) -> None:
        ref = build_rescue_ref("OMN-13044", "20260628T120000Z")
        assert ref == "rescue/OMN-13044/20260628T120000Z"
        assert ref.startswith(f"{RESCUE_REF_PREFIX}/")

    def test_rejects_empty_ticket(self) -> None:
        with pytest.raises(ValueError, match="ticket"):
            build_rescue_ref("", "20260628T120000Z")

    def test_rejects_empty_timestamp(self) -> None:
        with pytest.raises(ValueError, match="timestamp"):
            build_rescue_ref("OMN-13044", "")


# =============================================================================
# off-volume backup requirement
# =============================================================================


class TestOffvolumeBackupSatisfied:
    def test_true_with_ticket_attachment(self) -> None:
        assert (
            offvolume_backup_satisfied(
                has_ticket_attachment=True, has_docs_branch_commit=False
            )
            is True
        )

    def test_true_with_docs_branch_commit(self) -> None:
        assert (
            offvolume_backup_satisfied(
                has_ticket_attachment=False, has_docs_branch_commit=True
            )
            is True
        )

    def test_false_when_only_local_state_backup(self) -> None:
        # A bare .onex_state backup with no off-volume copy does NOT count.
        assert (
            offvolume_backup_satisfied(
                has_ticket_attachment=False, has_docs_branch_commit=False
            )
            is False
        )


# =============================================================================
# ModelWorktreeDurabilityFlags
# =============================================================================


class TestModelWorktreeDurabilityFlags:
    def test_no_ticket_flag(self) -> None:
        flags = ModelWorktreeDurabilityFlags(
            path="/wt/scratch/omniclaude",
            ticket_id=None,
            is_no_ticket=True,
        )
        assert flags.is_no_ticket is True
        assert flags.ticket_id is None
        assert flags.is_dirty_plan_worktree is False

    def test_dirty_plan_worktree_property(self) -> None:
        flags = ModelWorktreeDurabilityFlags(
            path="/wt/OMN-13044/omniclaude",
            ticket_id="OMN-13044",
            dirty_plan_files=("docs/plans/x.md", "src/a.py"),
        )
        assert flags.is_dirty_plan_worktree is True

    def test_rescue_ref_and_backup_fields(self) -> None:
        flags = ModelWorktreeDurabilityFlags(
            path="/wt/OMN-13044/omniclaude",
            ticket_id="OMN-13044",
            rescue_ref="rescue/OMN-13044/20260628T120000Z",
            offvolume_backup_ok=True,
        )
        assert flags.rescue_ref == "rescue/OMN-13044/20260628T120000Z"
        assert flags.offvolume_backup_ok is True

    def test_frozen(self) -> None:
        flags = ModelWorktreeDurabilityFlags(path="/wt/OMN-1/omniclaude")
        with pytest.raises(ValidationError):
            flags.is_no_ticket = True  # type: ignore[misc]

    def test_rejects_extra_fields(self) -> None:
        with pytest.raises(ValidationError):
            ModelWorktreeDurabilityFlags(
                path="/wt/OMN-1/omniclaude",
                surprise="nope",  # type: ignore[call-arg]
            )

    def test_rejects_empty_path(self) -> None:
        with pytest.raises(ValidationError):
            ModelWorktreeDurabilityFlags(path="")
