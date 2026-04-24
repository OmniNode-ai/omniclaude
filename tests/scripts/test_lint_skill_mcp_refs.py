# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for scripts/lint_skill_mcp_refs.py — OMN-8776.

Verifies the lint gate rejects hardcoded ``mcp__linear-server__*`` references
inside ``plugins/onex/skills/**/*.md`` and passes on clean inputs.
"""

from __future__ import annotations

import io
import os
import pathlib
import sys
import textwrap
from collections.abc import Iterator
from unittest.mock import patch

import pytest

_SCRIPT_DIR = pathlib.Path(__file__).parent.parent.parent / "scripts"
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import lint_skill_mcp_refs as gate  # noqa: E402

pytestmark = pytest.mark.unit


def _write_skill(
    tmp_path: pathlib.Path, slug: str, name: str, body: str
) -> pathlib.Path:
    skill_dir = tmp_path / "plugins" / "onex" / "skills" / slug
    skill_dir.mkdir(parents=True, exist_ok=True)
    path = skill_dir / name
    path.write_text(textwrap.dedent(body).lstrip("\n"))
    return path


@pytest.fixture
def run_in(tmp_path: pathlib.Path) -> Iterator[pathlib.Path]:
    prev = pathlib.Path.cwd()
    os.chdir(tmp_path)
    try:
        yield tmp_path
    finally:
        os.chdir(prev)


def _run(argv_tail: list[str]) -> tuple[int, str]:
    argv = ["lint_skill_mcp_refs.py", *argv_tail]
    captured = io.StringIO()
    with patch("sys.stderr", captured):
        exit_code = gate.main(argv)
    return exit_code, captured.getvalue()


def test_clean_skill_passes(run_in: pathlib.Path) -> None:
    path = _write_skill(
        run_in,
        "ticket_pipeline",
        "prompt.md",
        """
        # Ticket Pipeline

        Use `uv run onex run node_save_issue` to update Linear tickets via
        ProtocolProjectTracker dispatch.
        """,
    )
    code, stderr = _run([str(path)])
    assert code == 0, stderr
    assert stderr == ""


def test_violation_in_prompt_md_blocks(run_in: pathlib.Path) -> None:
    path = _write_skill(
        run_in,
        "ticket_pipeline",
        "prompt.md",
        """
        # Ticket Pipeline

        Call `mcp__linear-server__save_issue` to update the Linear ticket.
        """,
    )
    code, stderr = _run([str(path)])
    assert code == 1
    assert "mcp__linear-server__save_issue" in stderr
    assert "ProtocolProjectTracker" in stderr
    assert "OMN-8776" in stderr


def test_violation_in_skill_md_blocks(run_in: pathlib.Path) -> None:
    path = _write_skill(
        run_in,
        "linear_triage",
        "SKILL.md",
        """
        # Linear Triage

        Requires tool: mcp__linear-server__list_issues
        """,
    )
    code, stderr = _run([str(path)])
    assert code == 1
    assert "mcp__linear-server__list_issues" in stderr


def test_ci_mode_scans_full_tree(run_in: pathlib.Path) -> None:
    _write_skill(
        run_in,
        "clean_skill",
        "prompt.md",
        "# Clean\n\nRoute via `uv run onex run node_list_issues`.\n",
    )
    _write_skill(
        run_in,
        "dirty_skill",
        "prompt.md",
        "# Dirty\n\nCall mcp__linear-server__get_issue directly.\n",
    )
    code, stderr = _run([])
    assert code == 1
    assert "dirty_skill" in stderr
    assert "clean_skill" not in stderr


def test_ci_mode_passes_on_clean_tree(run_in: pathlib.Path) -> None:
    _write_skill(
        run_in,
        "clean_a",
        "prompt.md",
        "# A\n\nUse node dispatch.\n",
    )
    _write_skill(
        run_in,
        "clean_b",
        "SKILL.md",
        "# B\n\nUse node dispatch.\n",
    )
    code, stderr = _run([])
    assert code == 0, stderr


def test_non_markdown_argument_ignored(run_in: pathlib.Path) -> None:
    skill_dir = run_in / "plugins" / "onex" / "skills" / "ticket_pipeline"
    skill_dir.mkdir(parents=True, exist_ok=True)
    py_path = skill_dir / "handler.py"
    py_path.write_text("# mcp__linear-server__save_issue in Python is allowed\n")
    code, stderr = _run([str(py_path)])
    assert code == 0, stderr


def test_path_outside_skills_ignored(run_in: pathlib.Path) -> None:
    docs = run_in / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    path = docs / "research.md"
    path.write_text("References to mcp__linear-server__save_issue are fine in docs.\n")
    code, stderr = _run([str(path)])
    assert code == 0, stderr


def test_multiple_violations_reported(run_in: pathlib.Path) -> None:
    path = _write_skill(
        run_in,
        "ticket_pipeline",
        "prompt.md",
        """
        - mcp__linear-server__save_issue
        - mcp__linear-server__list_issues
        - mcp__linear-server__get_issue
        """,
    )
    code, stderr = _run([str(path)])
    assert code == 1
    assert stderr.count("mcp__linear-server__") >= 3
    assert "3 hardcoded" in stderr


def test_missing_file_is_silent(run_in: pathlib.Path) -> None:
    ghost = run_in / "plugins" / "onex" / "skills" / "ghost" / "prompt.md"
    code, stderr = _run([str(ghost)])
    assert code == 0
    assert stderr == ""


def test_empty_argv_with_missing_tree_passes(tmp_path: pathlib.Path) -> None:
    prev = pathlib.Path.cwd()
    os.chdir(tmp_path)
    try:
        code, stderr = _run([])
        assert code == 0, stderr
    finally:
        os.chdir(prev)


def test_non_utf8_file_fails_closed(run_in: pathlib.Path) -> None:
    skill_dir = run_in / "plugins" / "onex" / "skills" / "ticket_pipeline"
    skill_dir.mkdir(parents=True, exist_ok=True)
    path = skill_dir / "prompt.md"
    path.write_bytes(b"\xff\xfe\x00\x00 not valid utf-8 \xc3\x28\n")
    code, stderr = _run([str(path)])
    assert code == 1, stderr
    assert "decode error" in stderr
    assert "ticket_pipeline" in stderr
