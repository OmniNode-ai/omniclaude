# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for scripts/check_self_gating_workflows.py — OMN-9039.

Verifies the pre-commit gate blocks cross-repo `@main` refs in
`.github/workflows/*.y{a,}ml` files, which would cause the 2026-04-17
chicken-egg CI wedge (retro §4.8).
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

import check_self_gating_workflows as gate  # noqa: E402

pytestmark = pytest.mark.unit


def _write_workflow(tmp_path: pathlib.Path, body: str) -> pathlib.Path:
    workflow_dir = tmp_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True, exist_ok=True)
    path = workflow_dir / "example.yml"
    path.write_text(textwrap.dedent(body).lstrip("\n"))
    return path


def _run_on(paths: list[pathlib.Path]) -> tuple[int, str]:
    argv = ["check_self_gating_workflows.py", *[str(p) for p in paths]]
    captured = io.StringIO()
    with patch("sys.stderr", captured):
        exit_code = gate.main(argv)
    return exit_code, captured.getvalue()


def test_cross_repo_at_main_blocks(tmp_path: pathlib.Path) -> None:
    path = _write_workflow(
        tmp_path,
        """
        name: ci
        jobs:
          gate:
            uses: OmniNode-ai/omniclaude/.github/workflows/cr-thread-gate.yml@main
        """,
    )
    code, stderr = _run_on([path])
    assert code == 2
    assert "cross-repo @main ref" in stderr
    assert "cr-thread-gate.yml" in stderr
    assert "OMN-9039" in stderr


def test_local_path_allows(tmp_path: pathlib.Path) -> None:
    path = _write_workflow(
        tmp_path,
        """
        name: ci
        jobs:
          gate:
            uses: ./.github/workflows/cr-thread-gate.yml
        """,
    )
    code, stderr = _run_on([path])
    assert code == 0, stderr


def test_pinned_sha_allows(tmp_path: pathlib.Path) -> None:
    path = _write_workflow(
        tmp_path,
        """
        name: ci
        jobs:
          gate:
            uses: OmniNode-ai/omniclaude/.github/workflows/cr-thread-gate.yml@abcd1234abcd1234abcd1234abcd1234abcd1234
        """,
    )
    code, stderr = _run_on([path])
    assert code == 0, stderr


def test_tagged_version_allows(tmp_path: pathlib.Path) -> None:
    path = _write_workflow(
        tmp_path,
        """
        name: ci
        jobs:
          gate:
            uses: OmniNode-ai/omniclaude/.github/workflows/cr-thread-gate.yml@v1.0.0
        """,
    )
    code, stderr = _run_on([path])
    assert code == 0, stderr


def test_annotation_allows_with_reason(tmp_path: pathlib.Path) -> None:
    path = _write_workflow(
        tmp_path,
        """
        name: ci
        jobs:
          gate:
            # self-gating-ok: target is informational, not a required check
            uses: OmniNode-ai/omniclaude/.github/workflows/telemetry.yml@main
        """,
    )
    code, stderr = _run_on([path])
    assert code == 0, stderr


def test_annotation_without_reason_still_blocks(tmp_path: pathlib.Path) -> None:
    path = _write_workflow(
        tmp_path,
        """
        name: ci
        jobs:
          gate:
            # self-gating-ok:
            uses: OmniNode-ai/omniclaude/.github/workflows/cr-thread-gate.yml@main
        """,
    )
    code, stderr = _run_on([path])
    assert code == 2, stderr
    assert "cross-repo @main ref" in stderr


def test_annotation_too_far_still_blocks(tmp_path: pathlib.Path) -> None:
    # Annotation must be on the line immediately preceding the uses: line
    # (or separated only by blank/comment lines within 3 lines). This fixture
    # has an intervening job_key line that resets the state.
    path = _write_workflow(
        tmp_path,
        """
        name: ci
        jobs:
          # self-gating-ok: not applicable here
          other:
            name: other_job
          gate:
            uses: OmniNode-ai/omniclaude/.github/workflows/cr-thread-gate.yml@main
        """,
    )
    code, stderr = _run_on([path])
    assert code == 2, stderr


def test_multiple_violations_reported(tmp_path: pathlib.Path) -> None:
    path = _write_workflow(
        tmp_path,
        """
        name: ci
        jobs:
          gate1:
            uses: OmniNode-ai/omniclaude/.github/workflows/a.yml@main
          gate2:
            uses: OmniNode-ai/omnibase_infra/.github/workflows/b.yml@main
        """,
    )
    code, stderr = _run_on([path])
    assert code == 2, stderr
    assert "2 violation(s)" in stderr
    assert "a.yml" in stderr
    assert "b.yml" in stderr


def test_no_workflow_refs_allows(tmp_path: pathlib.Path) -> None:
    path = _write_workflow(
        tmp_path,
        """
        name: ci
        on: push
        jobs:
          build:
            runs-on: ubuntu-latest
            steps:
              - uses: actions/checkout@v4
              - run: echo hello
        """,
    )
    code, stderr = _run_on([path])
    assert code == 0, stderr


def test_empty_argv_exits_zero(tmp_path: pathlib.Path) -> None:
    code, stderr = _run_on([])
    assert code == 0


def test_nonexistent_file_is_silent(tmp_path: pathlib.Path) -> None:
    ghost = tmp_path / ".github" / "workflows" / "gone.yml"
    code, stderr = _run_on([ghost])
    assert code == 0
