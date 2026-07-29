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


# ---------------------------------------------------------------------------
# Non-src path triggers (OMN-15393)
#
# Before these existed, EVERY path outside src/omniclaude/ and tests/unit/
# resolved to nothing and fell through to the conservative ["tests/unit/"]
# fallback. Consequence: a guard living outside tests/unit/ could not be
# selected on the everyday dev path by ANY change shape -- not even by editing
# the guard itself. The workflow-only fan-out that PRODUCES the OMN-15393
# defect class selected tests/unit/ and the workflow guards stayed silent; the
# only backstop was the dev->main promotion full suite, i.e. after the broken
# workflow was already on dev. Per rule 5, detection not wired as a gate on the
# path that produces the defect is advisory.
# ---------------------------------------------------------------------------


def test_workflow_only_change_selects_workflow_guards() -> None:
    """The exact shape that produces the defect class must run the guards.

    Executed pre-fix behaviour on this same input (omniclaude @ dev 347e0e15):
    ``{"selected_paths":["tests/unit/"],"is_full_suite":false}`` -- the guard
    could not run on the class it guards, which is why the OMN-15393 fix landed
    green with a detector nothing selected (CLAUDE.md rule 5).
    """
    sel = compute_selection(
        changed_files=[".github/workflows/call-occ-companion-effect.yml"],
        adjacency_path=ADJACENCY,
        ref_name="jonah/omn-9999-test",
    )
    assert not sel.is_full_suite
    assert "tests/workflows/" in sel.selected_paths, (
        f"a workflow-only change must select the workflow guards; "
        f"got {sel.selected_paths}"
    )
    assert "tests/ci/" in sel.selected_paths


def test_workflow_trigger_is_additive_and_does_not_narrow() -> None:
    """Wiring a guard in must not un-wire anything else.

    Before path_triggers existed, EVERY trigger-matching path fell through to
    the conservative ``["tests/unit/"]`` fallback. Each trigger therefore has to
    keep ``tests/unit/`` in its selection, otherwise this PR would simultaneously
    add a guard and delete 5162 tests from that change class -- a narrowing
    CLAUDE.md rule 4 requires the governed selector to refuse unless it can prove
    narrowing is safe. "No unit test reads .github/workflows/ today" is a fact
    about today's tree, not a proof that survives someone writing one.
    """
    for changed in (
        ".github/workflows/call-occ-companion-effect.yml",
        "scripts/ci/occ_manual_replay_precheck.py",
        "plugins/onex/scripts/validate-all-agents.sh",
        "tests/workflows/test_workflow_run_script_paths_exist.py",
        "tests/ci/test_ci_summary_gate.py",
    ):
        sel = compute_selection(
            changed_files=[changed],
            adjacency_path=ADJACENCY,
            ref_name="jonah/omn-9999-test",
        )
        assert "tests/unit/" in sel.selected_paths, (
            f"{changed} previously fell through to the tests/unit/ fallback; "
            f"its trigger must be ADDITIVE, not a replacement. "
            f"got {sel.selected_paths}"
        )


def test_nested_plugin_script_change_selects_the_guard() -> None:
    """The guard also covers this repo's nested script roots under plugins/;
    deleting one of those is the identical OMN-15393 failure and the edit lands
    under plugins/, not scripts/ or .github/workflows/."""
    sel = compute_selection(
        changed_files=["plugins/onex/hooks/scripts/grep_guard_no_polymorphic_agent.sh"],
        adjacency_path=ADJACENCY,
        ref_name="jonah/omn-9999-test",
    )
    assert "tests/workflows/" in sel.selected_paths, (
        f"a nested plugin script change must reach the run:-script-path guard; "
        f"got {sel.selected_paths}"
    )


def test_ci_script_change_selects_workflow_guards_and_keeps_unit() -> None:
    """A scripts/** change must reach the run:-script-path guard AND keep the
    tests/unit/ coverage it already had -- tests/unit/scripts/ and this very
    module genuinely cover scripts/, so dropping it would NARROW coverage."""
    sel = compute_selection(
        changed_files=["scripts/ci/occ_manual_replay_precheck.py"],
        adjacency_path=ADJACENCY,
        ref_name="jonah/omn-9999-test",
    )
    assert not sel.is_full_suite
    assert "tests/workflows/" in sel.selected_paths
    assert "tests/unit/" in sel.selected_paths, (
        f"scripts/ changes must retain tests/unit/ coverage; got {sel.selected_paths}"
    )


def test_deleting_a_workflow_referenced_script_selects_the_guard() -> None:
    """The failure the guard exists to catch is a script going MISSING, and
    that edit lands under scripts/, not .github/workflows/."""
    sel = compute_selection(
        changed_files=["scripts/check-unresolved-threads.sh"],
        adjacency_path=ADJACENCY,
        ref_name="jonah/omn-9999-test",
    )
    assert "tests/workflows/" in sel.selected_paths


def test_workflow_guard_modules_can_select_themselves() -> None:
    """Without a self-trigger, editing a guard could not run that guard."""
    for changed, expected in (
        ("tests/workflows/test_workflow_run_script_paths_exist.py", "tests/workflows/"),
        ("tests/ci/test_validate_no_required_check_skip_vectors.py", "tests/ci/"),
    ):
        sel = compute_selection(
            changed_files=[changed],
            adjacency_path=ADJACENCY,
            ref_name="jonah/omn-9999-test",
        )
        assert expected in sel.selected_paths, (
            f"{changed} must select {expected}; got {sel.selected_paths}"
        )


def test_src_only_change_does_not_gain_workflow_guards() -> None:
    """Triggers must not over-select: a pure src change is unrelated to the
    workflow guards and must not start dragging them in."""
    sel = compute_selection(
        changed_files=["src/omniclaude/routing/engine.py"],
        adjacency_path=ADJACENCY,
        ref_name="jonah/omn-9999-test",
    )
    assert "tests/workflows/" not in sel.selected_paths
    assert "tests/ci/" not in sel.selected_paths


def test_unmapped_path_still_falls_back_to_unit() -> None:
    """The conservative fallback must survive for genuinely unmapped paths."""
    sel = compute_selection(
        changed_files=["README.md"],
        adjacency_path=ADJACENCY,
        ref_name="jonah/omn-9999-test",
    )
    assert sel.selected_paths == ["tests/unit/"]


def test_path_trigger_targets_exist_on_disk() -> None:
    """A trigger pointing at a directory that does not exist would make pytest
    exit 4 (usage error) in CI, or silently collect nothing."""
    from scripts.ci.test_selection_loader import load_adjacency_map

    repo_root = Path(__file__).resolve().parents[2]
    config = load_adjacency_map(ADJACENCY)
    assert config.path_triggers, "path_triggers must not be empty"
    for trigger in config.path_triggers:
        for test_path in trigger.test_paths:
            assert (repo_root / test_path).is_dir(), (
                f"path_trigger '{trigger.path_prefix}' selects '{test_path}', "
                f"which is not a directory in this tree"
            )


def test_selector_machinery_change_escalates_to_full_suite() -> None:
    """The selection machinery decides what runs, so it must never be
    validated by the selection it is editing. A PR that narrows selection is
    proven against the FULL suite before it can narrow anything."""
    for changed in (
        "scripts/ci/detect_test_paths.py",
        "scripts/ci/test_selection_adjacency.yaml",
        "scripts/ci/test_selection_loader.py",
        "scripts/ci/test_selection_models.py",
    ):
        sel = compute_selection(
            changed_files=[changed],
            adjacency_path=ADJACENCY,
            ref_name="jonah/omn-9999-test",
        )
        assert sel.is_full_suite, f"{changed} must escalate to the full suite"
        assert sel.full_suite_reason == EnumFullSuiteReason.TEST_INFRASTRUCTURE
