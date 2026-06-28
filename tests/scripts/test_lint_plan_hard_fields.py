# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for scripts/lint_plan_hard_fields.py — OMN-13051 (retro D-5).

Covers:
  Rule 1 — P0/P1 items with runtime-dep keywords require a
            ``precondition-probe:`` annotation within five lines.
  Rule 2 — Plans with a deliverable section listing file paths must have an
            ``## Artifact Manifest`` section.
  Rule 3 — Each item in ``## Artifact Manifest`` must carry an explicit
            status marker.
"""

from __future__ import annotations

import io
import pathlib
import sys
import textwrap
from unittest.mock import patch

import pytest

_SCRIPT_DIR = pathlib.Path(__file__).parent.parent.parent / "scripts"
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import lint_plan_hard_fields as gate  # noqa: E402

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_plan(root: pathlib.Path, subdir: str, name: str, body: str) -> pathlib.Path:
    plan_dir = root / "docs" / subdir
    plan_dir.mkdir(parents=True, exist_ok=True)
    path = plan_dir / name
    path.write_text(textwrap.dedent(body).lstrip("\n"))
    return path


def _run(root: pathlib.Path, argv_tail: list[str]) -> tuple[int, str]:
    argv = ["lint_plan_hard_fields.py", "--repo-root", str(root), *argv_tail]
    captured = io.StringIO()
    with patch("sys.stderr", captured):
        exit_code = gate.main(argv)
    return exit_code, captured.getvalue()


# ---------------------------------------------------------------------------
# Baseline: clean plan passes all rules
# ---------------------------------------------------------------------------


def test_clean_plan_no_p0p1_passes(tmp_path: pathlib.Path) -> None:
    path = _write_plan(
        tmp_path,
        "plans",
        "clean.md",
        """
        # My Plan

        ## Phase 1

        - Do some work
        - Merge the PR when ready
        """,
    )
    code, stderr = _run(tmp_path, [str(path)])
    assert code == 0, stderr


def test_plan_not_in_plan_root_ignored(tmp_path: pathlib.Path) -> None:
    docs = tmp_path / "docs" / "research"
    docs.mkdir(parents=True, exist_ok=True)
    path = docs / "notes.md"
    path.write_text(
        "# Notes\n\n- P0: once merged rides the rebuild — no probe needed here\n"
    )
    code, stderr = _run(tmp_path, [str(path)])
    assert code == 0, stderr


def test_non_markdown_file_ignored(tmp_path: pathlib.Path) -> None:
    plan_dir = tmp_path / "docs" / "plans"
    plan_dir.mkdir(parents=True, exist_ok=True)
    py_path = plan_dir / "helper.py"
    py_path.write_text("# P0: once merged — no probe in Python file\n")
    code, stderr = _run(tmp_path, [str(py_path)])
    assert code == 0, stderr


def test_nonexistent_path_silently_skipped(tmp_path: pathlib.Path) -> None:
    ghost = tmp_path / "docs" / "plans" / "ghost.md"
    code, stderr = _run(tmp_path, [str(ghost)])
    assert code == 0
    assert stderr == ""


def test_empty_tree_passes(tmp_path: pathlib.Path) -> None:
    code, stderr = _run(tmp_path, [])
    assert code == 0, stderr


# ---------------------------------------------------------------------------
# Rule 1 — P0/P1 probe requirement
# ---------------------------------------------------------------------------


def test_p0_no_runtime_dep_passes(tmp_path: pathlib.Path) -> None:
    """P0 item without runtime-dep keywords does not need a probe."""
    path = _write_plan(
        tmp_path,
        "plans",
        "ok.md",
        """
        # Plan

        ## Tasks

        - P0: write the unit tests
        - P0: update the contract YAML
        """,
    )
    code, stderr = _run(tmp_path, [str(path)])
    assert code == 0, stderr


def test_p0_with_runtime_dep_no_probe_blocks(tmp_path: pathlib.Path) -> None:
    """P0 item containing 'once merged' without probe → BLOCKED."""
    path = _write_plan(
        tmp_path,
        "plans",
        "bad.md",
        """
        # Plan

        ## P0 Tasks

        - P0: ship the handler once merged into dev
        """,
    )
    code, stderr = _run(tmp_path, [str(path)])
    assert code == 1
    assert "precondition-probe" in stderr
    assert "OMN-13051" in stderr


def test_p0_with_probe_in_window_passes(tmp_path: pathlib.Path) -> None:
    """P0 item with runtime-dep keyword + probe annotation within 5 lines → PASS."""
    path = _write_plan(
        tmp_path,
        "plans",
        "ok.md",
        """
        # Plan

        ## Tasks

        - P0: the node is ready once merged
          precondition-probe: 2026-06-12T14:30Z stability/v1/health via curl http://localhost:18085/v1/health
        """,
    )
    code, stderr = _run(tmp_path, [str(path)])
    assert code == 0, stderr


def test_p1_with_rides_the_rebuild_no_probe_blocks(tmp_path: pathlib.Path) -> None:
    """P1 item with 'rides the rebuild' keyword without probe → BLOCKED."""
    path = _write_plan(
        tmp_path,
        "plans",
        "bad.md",
        """
        # Plan

        ## Tasks

        - P1: the schema update rides the rebuild
        """,
    )
    code, stderr = _run(tmp_path, [str(path)])
    assert code == 1
    assert "precondition-probe" in stderr


def test_p1_with_probe_five_lines_down_passes(tmp_path: pathlib.Path) -> None:
    """Probe annotation exactly 5 lines below P1 item → PASS."""
    path = _write_plan(
        tmp_path,
        "plans",
        "ok.md",
        """
        # Plan

        ## Tasks

        - P1: the config rides the deploy
          context: some details here
          more: details
          extra: info
          still: in block
          precondition-probe: 2026-06-13 dev/v1/health via curl http://localhost:8085/v1/health
        """,
    )
    code, stderr = _run(tmp_path, [str(path)])
    assert code == 0, stderr


def test_p0_with_probe_six_lines_down_blocks(tmp_path: pathlib.Path) -> None:
    """Probe exactly 6 lines below P0 item (outside window) → BLOCKED."""
    path = _write_plan(
        tmp_path,
        "plans",
        "bad.md",
        """
        # Plan

        - P0: gateway rides the rebuild
          detail1: a
          detail2: b
          detail3: c
          detail4: d
          detail5: e
          precondition-probe: 2026-06-13 dev/v1/health via curl http://localhost:8085/v1/health
        """,
    )
    code, stderr = _run(tmp_path, [str(path)])
    assert code == 1
    assert "precondition-probe" in stderr


def test_table_p0_with_runtime_dep_no_probe_blocks(tmp_path: pathlib.Path) -> None:
    """P0 in table cell with 'after deploy' + no probe → BLOCKED."""
    path = _write_plan(
        tmp_path,
        "plans",
        "bad.md",
        """
        # Plan

        | Priority | Task |
        |----------|------|
        | P0 | handler available after deploy |
        """,
    )
    code, stderr = _run(tmp_path, [str(path)])
    assert code == 1
    assert "precondition-probe" in stderr


def test_table_p0_with_probe_passes(tmp_path: pathlib.Path) -> None:
    """P0 table row with runtime-dep keyword + probe within window → PASS."""
    path = _write_plan(
        tmp_path,
        "plans",
        "ok.md",
        """
        # Plan

        | Priority | Task |
        |----------|------|
        | P0 | handler available after deploy |
        precondition-probe: 2026-06-14 dev/v1/health via curl http://localhost:8085/v1/health
        """,
    )
    code, stderr = _run(tmp_path, [str(path)])
    assert code == 0, stderr


def test_p0_rides_deploy_blocked(tmp_path: pathlib.Path) -> None:
    """'rides the deploy' keyword → BLOCKED."""
    path = _write_plan(
        tmp_path,
        "plans",
        "bad.md",
        "# Plan\n\n- P0: feature rides the deploy\n",
    )
    code, stderr = _run(tmp_path, [str(path)])
    assert code == 1


def test_p0_after_redeploy_blocked(tmp_path: pathlib.Path) -> None:
    """'after redeploy' keyword → BLOCKED."""
    path = _write_plan(
        tmp_path,
        "plans",
        "bad.md",
        "# Plan\n\n- P0: node wired after redeploy\n",
    )
    code, stderr = _run(tmp_path, [str(path)])
    assert code == 1


def test_p0_rebuild_picks_up_blocked(tmp_path: pathlib.Path) -> None:
    """'rebuild picks up' keyword → BLOCKED."""
    path = _write_plan(
        tmp_path,
        "plans",
        "bad.md",
        "# Plan\n\n- P0: schema rebuild picks up the change\n",
    )
    code, stderr = _run(tmp_path, [str(path)])
    assert code == 1


def test_p0_case_insensitive_keyword_blocked(tmp_path: pathlib.Path) -> None:
    """'ONCE MERGED' (uppercase) → BLOCKED."""
    path = _write_plan(
        tmp_path,
        "plans",
        "bad.md",
        "# Plan\n\n- P0: node available ONCE MERGED\n",
    )
    code, stderr = _run(tmp_path, [str(path)])
    assert code == 1


def test_non_p0p1_item_with_runtime_dep_passes(tmp_path: pathlib.Path) -> None:
    """Runtime-dep keyword on a non-P0/P1 item → PASS (rule only applies to P0/P1)."""
    path = _write_plan(
        tmp_path,
        "plans",
        "ok.md",
        "# Plan\n\n- Do the thing once merged — no probe needed\n",
    )
    code, stderr = _run(tmp_path, [str(path)])
    assert code == 0, stderr


def test_probe_annotation_date_only_passes(tmp_path: pathlib.Path) -> None:
    """Probe with date-only (no T<time>) is accepted."""
    path = _write_plan(
        tmp_path,
        "plans",
        "ok.md",
        """
        # Plan

        - P0: service available after merge
          precondition-probe: 2026-06-20 stability/v1/health via curl http://localhost:18085/v1/health
        """,
    )
    code, stderr = _run(tmp_path, [str(path)])
    assert code == 0, stderr


# ---------------------------------------------------------------------------
# Rule 2 — deliverable section → artifact manifest required
# ---------------------------------------------------------------------------


def test_deliverable_section_no_file_paths_passes(tmp_path: pathlib.Path) -> None:
    """Deliverable section with no file paths does not require a manifest."""
    path = _write_plan(
        tmp_path,
        "plans",
        "ok.md",
        """
        # Plan

        ## Deliverables

        - Ship the feature
        - Update the README
        """,
    )
    code, stderr = _run(tmp_path, [str(path)])
    assert code == 0, stderr


def test_deliverable_section_with_file_paths_no_manifest_blocks(
    tmp_path: pathlib.Path,
) -> None:
    """Deliverable section listing `src/foo/bar.py` without manifest → BLOCKED."""
    path = _write_plan(
        tmp_path,
        "plans",
        "bad.md",
        """
        # Plan

        ## Deliverables

        - `src/omniclaude/hooks/schemas.py` — new schema model
        - `tests/hooks/test_schemas.py` — unit tests
        """,
    )
    code, stderr = _run(tmp_path, [str(path)])
    assert code == 1
    assert "Artifact Manifest" in stderr
    assert "OMN-13051" in stderr


def test_deliverable_section_with_manifest_passes(tmp_path: pathlib.Path) -> None:
    """Deliverable section + Artifact Manifest section → PASS."""
    path = _write_plan(
        tmp_path,
        "plans",
        "ok.md",
        """
        # Plan

        ## Deliverables

        - `src/omniclaude/hooks/schemas.py` — new schema model

        ## Artifact Manifest

        - [x] `src/omniclaude/hooks/schemas.py`
        """,
    )
    code, stderr = _run(tmp_path, [str(path)])
    assert code == 0, stderr


def test_files_to_create_heading_triggers_rule2(tmp_path: pathlib.Path) -> None:
    """'## Files to Create' heading with file paths → requires manifest."""
    path = _write_plan(
        tmp_path,
        "plans",
        "bad.md",
        """
        # Plan

        ## Files to Create

        - `scripts/lint_plan_hard_fields.py`
        """,
    )
    code, stderr = _run(tmp_path, [str(path)])
    assert code == 1
    assert "Artifact Manifest" in stderr


def test_files_to_create_modify_heading_triggers_rule2(tmp_path: pathlib.Path) -> None:
    """'## Files to Create/Modify' heading with file paths → requires manifest."""
    path = _write_plan(
        tmp_path,
        "plans",
        "bad.md",
        """
        # Plan

        ## Files to Create/Modify

        | File | Action |
        |------|--------|
        | `src/omniclaude/schemas.py` | Modify |
        """,
    )
    code, stderr = _run(tmp_path, [str(path)])
    assert code == 1


def test_files_to_modify_heading_triggers_rule2(tmp_path: pathlib.Path) -> None:
    """'## Files to Modify' heading with file paths → requires manifest."""
    path = _write_plan(
        tmp_path,
        "plans",
        "bad.md",
        """
        # Plan

        ## Files to Modify

        - `scripts/cron-closeout.sh`
        """,
    )
    code, stderr = _run(tmp_path, [str(path)])
    assert code == 1


def test_output_files_heading_triggers_rule2(tmp_path: pathlib.Path) -> None:
    """'## Output Files' heading with file paths → requires manifest."""
    path = _write_plan(
        tmp_path,
        "plans",
        "bad.md",
        """
        # Plan

        ## Output Files

        - `docs/tracking/result.md`
        """,
    )
    code, stderr = _run(tmp_path, [str(path)])
    assert code == 1


def test_artifacts_heading_triggers_rule2(tmp_path: pathlib.Path) -> None:
    """'## Artifacts' heading with file paths → requires manifest."""
    path = _write_plan(
        tmp_path,
        "plans",
        "bad.md",
        """
        # Plan

        ## Artifacts

        - `src/foo/bar.py`
        """,
    )
    code, stderr = _run(tmp_path, [str(path)])
    assert code == 1


# ---------------------------------------------------------------------------
# Rule 3 — artifact manifest item status
# ---------------------------------------------------------------------------


def test_manifest_with_checked_items_passes(tmp_path: pathlib.Path) -> None:
    """Artifact manifest with [x] items → PASS."""
    path = _write_plan(
        tmp_path,
        "plans",
        "ok.md",
        """
        # Plan

        ## Artifact Manifest

        - [x] `src/omniclaude/hooks/schemas.py`
        - [x] `tests/hooks/test_schemas.py`
        """,
    )
    code, stderr = _run(tmp_path, [str(path)])
    assert code == 0, stderr


def test_manifest_item_no_status_blocks(tmp_path: pathlib.Path) -> None:
    """Artifact manifest item without status marker → BLOCKED."""
    path = _write_plan(
        tmp_path,
        "plans",
        "bad.md",
        """
        # Plan

        ## Artifact Manifest

        - [x] `src/omniclaude/hooks/schemas.py`
        - [ ] `tests/hooks/test_schemas.py`
        """,
    )
    code, stderr = _run(tmp_path, [str(path)])
    assert code == 1
    assert "Artifact Manifest item" in stderr
    assert "OMN-13051" in stderr


def test_manifest_skipped_item_passes(tmp_path: pathlib.Path) -> None:
    """Artifact manifest item with SKIPPED: reason → PASS."""
    path = _write_plan(
        tmp_path,
        "plans",
        "ok.md",
        """
        # Plan

        ## Artifact Manifest

        - [x] `src/omniclaude/hooks/schemas.py`
        - [ ] `tests/hooks/test_schemas.py` — SKIPPED: out of scope for this PR
        """,
    )
    code, stderr = _run(tmp_path, [str(path)])
    assert code == 0, stderr


def test_manifest_deferred_item_passes(tmp_path: pathlib.Path) -> None:
    """Artifact manifest item with DEFERRED: reason → PASS."""
    path = _write_plan(
        tmp_path,
        "plans",
        "ok.md",
        """
        # Plan

        ## Artifact Manifest

        - [ ] `src/omniclaude/hooks/schemas.py` — DEFERRED: waiting for OMN-99999
        """,
    )
    code, stderr = _run(tmp_path, [str(path)])
    assert code == 0, stderr


def test_manifest_blocked_on_item_passes(tmp_path: pathlib.Path) -> None:
    """Artifact manifest item with BLOCKED-ON: X → PASS."""
    path = _write_plan(
        tmp_path,
        "plans",
        "ok.md",
        """
        # Plan

        ## Artifact Manifest

        - [ ] `src/omniclaude/schemas.py` — BLOCKED-ON: OMN-13013 merge
        """,
    )
    code, stderr = _run(tmp_path, [str(path)])
    assert code == 0, stderr


def test_manifest_done_keyword_passes(tmp_path: pathlib.Path) -> None:
    """Artifact manifest item with DONE → PASS."""
    path = _write_plan(
        tmp_path,
        "plans",
        "ok.md",
        """
        # Plan

        ## Artifact Manifest

        - `src/omniclaude/schemas.py` DONE
        """,
    )
    code, stderr = _run(tmp_path, [str(path)])
    assert code == 0, stderr


def test_manifest_table_rows_with_status_pass(tmp_path: pathlib.Path) -> None:
    """Artifact manifest as a table with status column → PASS."""
    path = _write_plan(
        tmp_path,
        "plans",
        "ok.md",
        """
        # Plan

        ## Artifact Manifest

        | File | Status |
        |------|--------|
        | `src/foo.py` | DONE |
        | `tests/test_foo.py` | SKIPPED: deferred |
        """,
    )
    code, stderr = _run(tmp_path, [str(path)])
    assert code == 0, stderr


def test_manifest_table_separator_rows_exempt(tmp_path: pathlib.Path) -> None:
    """Table separator rows (|---|---|) are exempt from status requirement."""
    path = _write_plan(
        tmp_path,
        "plans",
        "ok.md",
        """
        # Plan

        ## Artifact Manifest

        | File | Status |
        |------|--------|
        | `src/foo.py` | [x] |
        """,
    )
    code, stderr = _run(tmp_path, [str(path)])
    assert code == 0, stderr


def test_manifest_table_row_no_status_blocks(tmp_path: pathlib.Path) -> None:
    """Table row in Artifact Manifest without status → BLOCKED."""
    path = _write_plan(
        tmp_path,
        "plans",
        "bad.md",
        """
        # Plan

        ## Artifact Manifest

        | File | Notes |
        |------|-------|
        | `src/foo.py` | some notes |
        """,
    )
    code, stderr = _run(tmp_path, [str(path)])
    assert code == 1
    assert "Artifact Manifest item" in stderr


def test_manifest_section_ends_at_next_heading(tmp_path: pathlib.Path) -> None:
    """Items after the next heading are NOT part of the manifest section."""
    path = _write_plan(
        tmp_path,
        "plans",
        "ok.md",
        """
        # Plan

        ## Artifact Manifest

        - [x] `src/foo.py`

        ## Other Section

        - [ ] some item without status (outside manifest)
        """,
    )
    code, stderr = _run(tmp_path, [str(path)])
    assert code == 0, stderr


def test_manifest_uppercase_done_passes(tmp_path: pathlib.Path) -> None:
    """DONE in uppercase → PASS (case-insensitive match)."""
    path = _write_plan(
        tmp_path,
        "plans",
        "ok.md",
        "# Plan\n\n## Artifact Manifest\n\n- `src/x.py` DONE\n",
    )
    code, stderr = _run(tmp_path, [str(path)])
    assert code == 0, stderr


def test_manifest_blocked_on_space_variant_passes(tmp_path: pathlib.Path) -> None:
    """'BLOCKED ON:' (space variant) → PASS."""
    path = _write_plan(
        tmp_path,
        "plans",
        "ok.md",
        "# Plan\n\n## Artifact Manifest\n\n- [ ] `src/x.py` — BLOCKED ON: OMN-99\n",
    )
    code, stderr = _run(tmp_path, [str(path)])
    assert code == 0, stderr


# ---------------------------------------------------------------------------
# CI mode (no path arguments)
# ---------------------------------------------------------------------------


def test_ci_mode_scans_full_tree(tmp_path: pathlib.Path) -> None:
    """CI mode (no args) scans both docs/plans and docs/tracking."""
    _write_plan(
        tmp_path,
        "plans",
        "clean.md",
        "# Clean plan\n\n- P0: unit tests pass\n",
    )
    _write_plan(
        tmp_path,
        "tracking",
        "dirty.md",
        "# Dirty\n\n- P0: feature rides the rebuild\n",
    )
    code, stderr = _run(tmp_path, [])
    assert code == 1
    assert "dirty.md" in stderr
    assert "clean.md" not in stderr


def test_ci_mode_passes_on_clean_tree(tmp_path: pathlib.Path) -> None:
    _write_plan(tmp_path, "plans", "a.md", "# A\n\n- P0: write tests\n")
    _write_plan(tmp_path, "tracking", "b.md", "# B\n\n- P1: review PR\n")
    code, stderr = _run(tmp_path, [])
    assert code == 0, stderr


# ---------------------------------------------------------------------------
# Multiple violations in one file
# ---------------------------------------------------------------------------


def test_multiple_violations_all_reported(tmp_path: pathlib.Path) -> None:
    """Multiple violations from different rules all surface in stderr."""
    path = _write_plan(
        tmp_path,
        "plans",
        "multi.md",
        """
        # Plan

        ## Deliverables

        - `src/foo.py` — deliverable file path

        ## Tasks

        - P0: feature available after deploy

        ## Artifact Manifest

        - [ ] `src/foo.py`
        """,
    )
    code, stderr = _run(tmp_path, [str(path)])
    assert code == 1
    # Rule 1 violation (P0 + after deploy + no probe)
    assert "precondition-probe" in stderr
    # Rule 3 violation ([ ] item without status)
    assert "Artifact Manifest item" in stderr


# ---------------------------------------------------------------------------
# Error handling — fails closed on unreadable files
# ---------------------------------------------------------------------------


def test_non_utf8_file_fails_closed(tmp_path: pathlib.Path) -> None:
    plan_dir = tmp_path / "docs" / "plans"
    plan_dir.mkdir(parents=True, exist_ok=True)
    path = plan_dir / "binary.md"
    path.write_bytes(b"\xff\xfe binary \xc3\x28\n")
    code, stderr = _run(tmp_path, [str(path)])
    assert code == 1
    assert "decode error" in stderr
