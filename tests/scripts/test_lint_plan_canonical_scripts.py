# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for scripts/lint_plan_canonical_scripts.py — OMN-14476.

Verifies the plan-canonical-scripts gate FAILs when a plan under ``docs/plans/``
or ``docs/tracking/`` proposes creating a new ``scripts/**`` file without a
``canonical-form:`` declaration, and passes on compliant / non-proposing inputs.
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

import lint_plan_canonical_scripts as gate  # noqa: E402

pytestmark = pytest.mark.unit


def _write_plan(root: pathlib.Path, subdir: str, name: str, body: str) -> pathlib.Path:
    plan_dir = root / "docs" / subdir
    plan_dir.mkdir(parents=True, exist_ok=True)
    path = plan_dir / name
    path.write_text(textwrap.dedent(body).lstrip("\n"))
    return path


def _run(root: pathlib.Path, argv_tail: list[str]) -> tuple[int, str]:
    argv = ["lint_plan_canonical_scripts.py", "--repo-root", str(root), *argv_tail]
    captured = io.StringIO()
    with patch("sys.stderr", captured):
        exit_code = gate.main(argv)
    return exit_code, captured.getvalue()


def test_plan_with_no_scripts_passes(tmp_path: pathlib.Path) -> None:
    path = _write_plan(
        tmp_path, "plans", "p.md", "# Plan\nBuild node_foo as a COMPUTE node.\n"
    )
    code, stderr = _run(tmp_path, [str(path)])
    assert code == 0, stderr
    assert stderr == ""


def test_proposes_new_py_script_without_declaration_fails(
    tmp_path: pathlib.Path,
) -> None:
    path = _write_plan(
        tmp_path,
        "plans",
        "p.md",
        "# Plan\nWe will create scripts/foo_helper.py to rank the drift.\n",
    )
    code, stderr = _run(tmp_path, [str(path)])
    assert code == 1
    assert "scripts/foo_helper.py" in stderr
    assert "canonical-form" in stderr


def test_proposes_new_sh_script_without_declaration_fails(
    tmp_path: pathlib.Path,
) -> None:
    path = _write_plan(
        tmp_path,
        "tracking",
        "t.md",
        "# Tracking\nAdd scripts/deploy/cut.sh to drive the lane bring-up.\n",
    )
    code, stderr = _run(tmp_path, [str(path)])
    assert code == 1
    assert "scripts/deploy/cut.sh" in stderr


def test_proposes_new_script_with_declaration_passes(tmp_path: pathlib.Path) -> None:
    path = _write_plan(
        tmp_path,
        "plans",
        "p.md",
        """
        # Plan
        We will create scripts/ci/publish_retry.py as CI-layer glue.
        canonical-form: justified-shim: uv publish wrapper, no runtime in CI
        """,
    )
    code, stderr = _run(tmp_path, [str(path)])
    assert code == 0, stderr


def test_node_backed_declaration_passes(tmp_path: pathlib.Path) -> None:
    path = _write_plan(
        tmp_path,
        "plans",
        "p.md",
        """
        # Plan
        Add scripts/run_foo.py as a thin dispatcher.
        canonical-form: node-backed
        """,
    )
    code, stderr = _run(tmp_path, [str(path)])
    assert code == 0, stderr


def test_mention_of_existing_script_not_flagged(tmp_path: pathlib.Path) -> None:
    """A mention of an existing script (no create verb) is not a proposal."""
    path = _write_plan(
        tmp_path,
        "plans",
        "p.md",
        "# Plan\nThe existing scripts/deploy-runtime.sh already handles bring-up.\n",
    )
    code, stderr = _run(tmp_path, [str(path)])
    assert code == 0, stderr


def test_grandfathered_plan_is_exempt(tmp_path: pathlib.Path) -> None:
    path = _write_plan(
        tmp_path,
        "plans",
        "legacy.md",
        "# Legacy\nWe will create scripts/old.py for the batch job.\n",
    )
    ratchet = tmp_path / ".onex_ratchets"
    ratchet.mkdir(parents=True, exist_ok=True)
    (ratchet / "plan_canonical_scripts_allowlist.yaml").write_text(
        "allowed:\n  - docs/plans/legacy.md\n"
    )
    code, stderr = _run(tmp_path, [str(path)])
    assert code == 0, stderr


def test_full_tree_scan_flags_bad_plan(tmp_path: pathlib.Path) -> None:
    _write_plan(tmp_path, "plans", "ok.md", "# OK\nBuild node_bar.\n")
    _write_plan(tmp_path, "plans", "bad.md", "# Bad\nWe will add scripts/x.py here.\n")
    code, stderr = _run(tmp_path, [])  # no paths → full-tree scan
    assert code == 1
    assert "scripts/x.py" in stderr


def test_unreadable_plan_fails_closed(tmp_path: pathlib.Path) -> None:
    path = _write_plan(tmp_path, "plans", "b.md", "# ok\n")
    path.write_bytes(b"\xff\xfe invalid utf8 \x80\x81")
    code, stderr = _run(tmp_path, [str(path)])
    assert code == 1
    assert "error" in stderr.lower()
