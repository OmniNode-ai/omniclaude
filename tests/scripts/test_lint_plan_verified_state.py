# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for scripts/lint_plan_verified_state.py — OMN-13336.

Verifies the plan-verified-state gate FAILs when a plan_to_tickets plan under
``docs/plans/`` or ``docs/tracking/`` lacks a fresh ``Current Verified State``
section, and passes on compliant inputs. All cases pin ``--today`` for
determinism.
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

import lint_plan_verified_state as gate  # noqa: E402

pytestmark = pytest.mark.unit

_TODAY = "2026-06-19"


def _write_plan(root: pathlib.Path, subdir: str, name: str, body: str) -> pathlib.Path:
    plan_dir = root / "docs" / subdir
    plan_dir.mkdir(parents=True, exist_ok=True)
    path = plan_dir / name
    path.write_text(textwrap.dedent(body).lstrip("\n"))
    return path


def _run(root: pathlib.Path, argv_tail: list[str]) -> tuple[int, str]:
    argv = [
        "lint_plan_verified_state.py",
        "--repo-root",
        str(root),
        "--today",
        _TODAY,
        *argv_tail,
    ]
    captured = io.StringIO()
    with patch("sys.stderr", captured):
        exit_code = gate.main(argv)
    return exit_code, captured.getvalue()


_FRESH_SECTION = """
## Current Verified State

verified: 2026-06-19 via gh pr checks 1781 --repo OmniNode-ai/omniclaude

The dev branch protection lists `verify / verify` as a required check.
"""


def test_compliant_plan_passes(tmp_path: pathlib.Path) -> None:
    path = _write_plan(
        tmp_path,
        "plans",
        "2026-06-19-new-plan.md",
        "# New Plan\n" + _FRESH_SECTION + "\n## Phase 1\n- do a thing\n",
    )
    code, stderr = _run(tmp_path, [str(path)])
    assert code == 0, stderr
    assert stderr == ""


def test_compliant_plan_in_tracking_passes(tmp_path: pathlib.Path) -> None:
    path = _write_plan(
        tmp_path,
        "tracking",
        "2026-06-19-tracking.md",
        "# Tracking\n" + _FRESH_SECTION,
    )
    code, stderr = _run(tmp_path, [str(path)])
    assert code == 0, stderr


def test_missing_section_blocks(tmp_path: pathlib.Path) -> None:
    path = _write_plan(
        tmp_path,
        "plans",
        "2026-06-19-no-section.md",
        "# Plan\n\n## Phase 1\n- ticketize me\n",
    )
    code, stderr = _run(tmp_path, [str(path)])
    assert code == 1
    assert "missing required '## Current Verified State' section" in stderr
    assert "OMN-13336" in stderr


def test_section_without_verified_line_blocks(tmp_path: pathlib.Path) -> None:
    path = _write_plan(
        tmp_path,
        "plans",
        "2026-06-19-empty-section.md",
        """
        # Plan

        ## Current Verified State

        The runtime is wired and healthy.
        """,
    )
    code, stderr = _run(tmp_path, [str(path)])
    assert code == 1
    assert "no 'verified: <date> via <command>' line" in stderr


def test_stale_verified_line_blocks(tmp_path: pathlib.Path) -> None:
    # 2026-05-01 is > 14 days before 2026-06-19.
    path = _write_plan(
        tmp_path,
        "plans",
        "2026-06-19-stale.md",
        """
        # Plan

        ## Current Verified State

        verified: 2026-05-01 via gh pr checks 1234 --repo OmniNode-ai/omniclaude
        """,
    )
    code, stderr = _run(tmp_path, [str(path)])
    assert code == 1
    assert "within 14 days" in stderr


def test_boundary_exactly_max_age_passes(tmp_path: pathlib.Path) -> None:
    # 2026-06-05 is exactly 14 days before 2026-06-19 → still fresh.
    path = _write_plan(
        tmp_path,
        "plans",
        "2026-06-19-boundary.md",
        """
        # Plan

        ## Current Verified State

        verified: 2026-06-05 via rpk topic list -X brokers=...:39092
        """,
    )
    code, stderr = _run(tmp_path, [str(path)])
    assert code == 0, stderr


def test_malformed_verified_line_blocks(tmp_path: pathlib.Path) -> None:
    path = _write_plan(
        tmp_path,
        "plans",
        "2026-06-19-malformed.md",
        """
        # Plan

        ## Current Verified State

        verified: yesterday via some command
        """,
    )
    code, stderr = _run(tmp_path, [str(path)])
    assert code == 1
    assert "malformed verified line" in stderr


def test_verified_line_missing_command_blocks(tmp_path: pathlib.Path) -> None:
    path = _write_plan(
        tmp_path,
        "plans",
        "2026-06-19-nocommand.md",
        """
        # Plan

        ## Current Verified State

        verified: 2026-06-19 via
        """,
    )
    code, stderr = _run(tmp_path, [str(path)])
    assert code == 1
    assert "malformed verified line" in stderr


def test_future_dated_verified_line_blocks(tmp_path: pathlib.Path) -> None:
    path = _write_plan(
        tmp_path,
        "plans",
        "2026-06-19-future.md",
        """
        # Plan

        ## Current Verified State

        verified: 2026-12-31 via gh pr checks 1 --repo OmniNode-ai/omniclaude
        """,
    )
    code, stderr = _run(tmp_path, [str(path)])
    assert code == 1
    assert "future date not allowed" in stderr


def test_case_insensitive_section_and_key(tmp_path: pathlib.Path) -> None:
    path = _write_plan(
        tmp_path,
        "plans",
        "2026-06-19-case.md",
        """
        # Plan

        ### current VERIFIED state

        VERIFIED: 2026-06-18 via gh api repos/OmniNode-ai/omniclaude
        """,
    )
    code, stderr = _run(tmp_path, [str(path)])
    assert code == 0, stderr


def test_path_outside_plan_roots_ignored(tmp_path: pathlib.Path) -> None:
    docs = tmp_path / "docs" / "research"
    docs.mkdir(parents=True, exist_ok=True)
    path = docs / "notes.md"
    path.write_text("# Notes\n\nNo verified-state section needed here.\n")
    code, stderr = _run(tmp_path, [str(path)])
    assert code == 0, stderr


def test_non_markdown_argument_ignored(tmp_path: pathlib.Path) -> None:
    plan_dir = tmp_path / "docs" / "plans"
    plan_dir.mkdir(parents=True, exist_ok=True)
    py_path = plan_dir / "helper.py"
    py_path.write_text("# not a plan markdown\n")
    code, stderr = _run(tmp_path, [str(py_path)])
    assert code == 0, stderr


def test_allowlisted_plan_skipped(tmp_path: pathlib.Path) -> None:
    path = _write_plan(
        tmp_path,
        "plans",
        "legacy-plan.md",
        "# Legacy\n\nNo verified-state section, but grandfathered.\n",
    )
    ratchet_dir = tmp_path / ".onex_ratchets"
    ratchet_dir.mkdir(parents=True, exist_ok=True)
    (ratchet_dir / "plan_verified_state_allowlist.yaml").write_text(
        "allowed:\n  - docs/plans/legacy-plan.md\n"
    )
    code, stderr = _run(tmp_path, [str(path)])
    assert code == 0, stderr


def test_non_allowlisted_plan_still_blocks_with_allowlist_present(
    tmp_path: pathlib.Path,
) -> None:
    _write_plan(
        tmp_path,
        "plans",
        "legacy-plan.md",
        "# Legacy\n\nGrandfathered.\n",
    )
    bad = _write_plan(
        tmp_path,
        "plans",
        "2026-06-19-new.md",
        "# New\n\nNo section.\n",
    )
    ratchet_dir = tmp_path / ".onex_ratchets"
    ratchet_dir.mkdir(parents=True, exist_ok=True)
    (ratchet_dir / "plan_verified_state_allowlist.yaml").write_text(
        "allowed:\n  - docs/plans/legacy-plan.md\n"
    )
    code, stderr = _run(tmp_path, [str(bad)])
    assert code == 1
    assert "2026-06-19-new.md" in stderr


def test_ci_mode_scans_full_tree(tmp_path: pathlib.Path) -> None:
    _write_plan(
        tmp_path,
        "plans",
        "clean.md",
        "# Clean\n" + _FRESH_SECTION,
    )
    _write_plan(
        tmp_path,
        "tracking",
        "dirty.md",
        "# Dirty\n\nNo section here.\n",
    )
    code, stderr = _run(tmp_path, [])
    assert code == 1
    assert "dirty.md" in stderr
    assert "clean.md" not in stderr


def test_ci_mode_passes_on_clean_tree(tmp_path: pathlib.Path) -> None:
    _write_plan(tmp_path, "plans", "a.md", "# A\n" + _FRESH_SECTION)
    _write_plan(tmp_path, "tracking", "b.md", "# B\n" + _FRESH_SECTION)
    code, stderr = _run(tmp_path, [])
    assert code == 0, stderr


def test_empty_tree_passes(tmp_path: pathlib.Path) -> None:
    code, stderr = _run(tmp_path, [])
    assert code == 0, stderr


def test_missing_file_argument_silent(tmp_path: pathlib.Path) -> None:
    ghost = tmp_path / "docs" / "plans" / "ghost.md"
    code, stderr = _run(tmp_path, [str(ghost)])
    assert code == 0
    assert stderr == ""


def test_non_utf8_plan_fails_closed(tmp_path: pathlib.Path) -> None:
    plan_dir = tmp_path / "docs" / "plans"
    plan_dir.mkdir(parents=True, exist_ok=True)
    path = plan_dir / "binary.md"
    path.write_bytes(b"\xff\xfe\x00\x00 not valid utf-8 \xc3\x28\n")
    code, stderr = _run(tmp_path, [str(path)])
    assert code == 1, stderr
    assert "decode error" in stderr


def test_custom_max_age_days_respected(tmp_path: pathlib.Path) -> None:
    path = _write_plan(
        tmp_path,
        "plans",
        "2026-06-19-window.md",
        """
        # Plan

        ## Current Verified State

        verified: 2026-06-16 via gh pr checks 1 --repo OmniNode-ai/omniclaude
        """,
    )
    # 3 days old; passes with default 14 but fails with a 2-day window.
    code_ok, _ = _run(tmp_path, [str(path)])
    assert code_ok == 0
    code_bad, stderr = _run(tmp_path, ["--max-age-days", "2", str(path)])
    assert code_bad == 1
    assert "within 2 days" in stderr


def test_negative_max_age_days_is_usage_error(tmp_path: pathlib.Path) -> None:
    code, stderr = _run(tmp_path, ["--max-age-days", "-1"])
    assert code == 2
    assert "must be >= 0" in stderr
