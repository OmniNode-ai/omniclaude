# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for change-aware test selection (OMN-10760)."""

from __future__ import annotations

from pathlib import Path

from scripts.ci.detect_test_paths import FULL_SUITE_SPLITS, compute_selection
from scripts.ci.test_selection_models import EnumFullSuiteReason

ADJACENCY = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "ci"
    / "test_selection_adjacency.yaml"
)


# ---------------------------------------------------------------------------
# Full-suite escalation
# ---------------------------------------------------------------------------


def test_feature_flag_off_returns_full_suite() -> None:
    sel = compute_selection(
        changed_files=["src/omniclaude/quirks/foo.py"],
        adjacency_path=ADJACENCY,
        ref_name="jonah/omn-9999-test",
        feature_flag_enabled=False,
    )
    assert sel.is_full_suite
    assert sel.full_suite_reason == EnumFullSuiteReason.FEATURE_FLAG_OFF
    assert sel.split_count == FULL_SUITE_SPLITS
    assert sel.matrix == list(range(1, FULL_SUITE_SPLITS + 1))


def test_main_branch_returns_full_suite() -> None:
    sel = compute_selection(
        changed_files=["src/omniclaude/quirks/foo.py"],
        adjacency_path=ADJACENCY,
        ref_name="main",
    )
    assert sel.is_full_suite
    assert sel.full_suite_reason == EnumFullSuiteReason.MAIN_BRANCH


def test_merge_group_returns_full_suite() -> None:
    sel = compute_selection(
        changed_files=["src/omniclaude/quirks/foo.py"],
        adjacency_path=ADJACENCY,
        ref_name="jonah/omn-9999-test",
        event_name="merge_group",
    )
    assert sel.is_full_suite
    assert sel.full_suite_reason == EnumFullSuiteReason.MERGE_GROUP


def test_scheduled_returns_full_suite() -> None:
    sel = compute_selection(
        changed_files=[],
        adjacency_path=ADJACENCY,
        ref_name="jonah/omn-9999-test",
        event_name="schedule",
    )
    assert sel.is_full_suite
    assert sel.full_suite_reason == EnumFullSuiteReason.SCHEDULED


def test_shared_module_hooks_escalates() -> None:
    sel = compute_selection(
        changed_files=["src/omniclaude/hooks/schemas.py"],
        adjacency_path=ADJACENCY,
        ref_name="jonah/omn-9999-test",
    )
    assert sel.is_full_suite
    assert sel.full_suite_reason == EnumFullSuiteReason.SHARED_MODULE


def test_test_infrastructure_change_escalates() -> None:
    sel = compute_selection(
        changed_files=["tests/conftest.py"],
        adjacency_path=ADJACENCY,
        ref_name="jonah/omn-9999-test",
    )
    assert sel.is_full_suite
    assert sel.full_suite_reason == EnumFullSuiteReason.TEST_INFRASTRUCTURE


def test_pyproject_toml_escalates() -> None:
    sel = compute_selection(
        changed_files=["pyproject.toml"],
        adjacency_path=ADJACENCY,
        ref_name="jonah/omn-9999-test",
    )
    assert sel.is_full_suite
    assert sel.full_suite_reason == EnumFullSuiteReason.TEST_INFRASTRUCTURE


# ---------------------------------------------------------------------------
# Smart selection — leaf module changes
# ---------------------------------------------------------------------------


def test_quirks_change_selects_only_quirks_and_hooks() -> None:
    sel = compute_selection(
        changed_files=["src/omniclaude/quirks/some_handler.py"],
        adjacency_path=ADJACENCY,
        ref_name="jonah/omn-9999-test",
    )
    assert not sel.is_full_suite
    assert sel.full_suite_reason is None
    # quirks reverse_dep is hooks → hooks is shared_module → should NOT expand to full suite
    # (shared module check is for *changed* modules, not expanded reverse deps)
    assert "tests/unit/quirks/" in sel.selected_paths
    assert sel.split_count >= 1
    assert len(sel.matrix) == sel.split_count


def test_unit_test_change_includes_that_directory() -> None:
    sel = compute_selection(
        changed_files=["tests/unit/delegation/test_something.py"],
        adjacency_path=ADJACENCY,
        ref_name="jonah/omn-9999-test",
    )
    assert not sel.is_full_suite
    assert "tests/unit/delegation/" in sel.selected_paths


def test_doc_only_change_falls_back_to_unit_root() -> None:
    sel = compute_selection(
        changed_files=["docs/plans/some-plan.md"],
        adjacency_path=ADJACENCY,
        ref_name="jonah/omn-9999-test",
    )
    assert not sel.is_full_suite
    assert sel.selected_paths == ["tests/unit/"]
    assert sel.split_count == 1


def test_no_changed_files_falls_back_to_unit_root() -> None:
    sel = compute_selection(
        changed_files=[],
        adjacency_path=ADJACENCY,
        ref_name="jonah/omn-9999-test",
    )
    assert not sel.is_full_suite
    assert sel.selected_paths == ["tests/unit/"]


def test_adjacency_expansion_works() -> None:
    """routing_models change should pull in routing and hooks via adjacency."""
    sel = compute_selection(
        changed_files=["src/omniclaude/routing_models/model_route.py"],
        adjacency_path=ADJACENCY,
        ref_name="jonah/omn-9999-test",
    )
    assert not sel.is_full_suite
    # routing_models → reverse_deps: routing, hooks, delegation
    # BUT hooks is shared_module — only *changed* modules are checked for shared_module
    # routing_models is NOT a shared_module, so no escalation
    assert "tests/unit/routing_models/" in sel.selected_paths
    # routing should be included via expansion
    assert "tests/unit/routing/" in sel.selected_paths


def test_matrix_length_equals_split_count() -> None:
    sel = compute_selection(
        changed_files=["src/omniclaude/aggregators/session.py"],
        adjacency_path=ADJACENCY,
        ref_name="jonah/omn-9999-test",
    )
    assert len(sel.matrix) == sel.split_count
    assert sel.matrix == list(range(1, sel.split_count + 1))


def test_adjacency_yaml_is_self_consistent() -> None:
    """The adjacency YAML must load without validation errors."""
    from scripts.ci.test_selection_loader import load_adjacency_map

    config = load_adjacency_map(ADJACENCY)
    # All shared_modules must appear in adjacency
    for module in config.shared_modules:
        assert module in config.adjacency
    # All reverse_dep references must be valid module names
    for module, entry in config.adjacency.items():
        for dep in entry.reverse_deps:
            assert dep in config.adjacency, (
                f"{module}.reverse_deps references unknown '{dep}'"
            )
