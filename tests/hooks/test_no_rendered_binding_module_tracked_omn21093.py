# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""No rendered Claude Code binding module is tracked in omniclaude (OMN-21093, T0.3 AC7)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from omnibase_core.validators.no_unguarded_git_subprocess import (
    scrub_git_location_env,
)

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[2]
# Split so this file does not carry the marker it searches for.
MARKER = "Rendered by " + "node_claude_code_binding_render_compute"
RENDERED_SUFFIXES = (".ts", ".tsx", ".js")


def _tracked_files() -> list[str]:
    return subprocess.run(
        ["git", "ls-files"],
        capture_output=True,
        text=True,
        cwd=REPO,
        check=True,
        env=scrub_git_location_env(os.environ),
    ).stdout.splitlines()


def _rendered(files: list[str], read) -> list[str]:
    return [f for f in files if f.endswith(RENDERED_SUFFIXES) and MARKER in read(f)]


def _read(rel: str) -> str:
    path = REPO / rel
    return path.read_text(errors="ignore") if path.is_file() else ""


def test_ac7_no_rendered_module_is_tracked_in_omniclaude() -> None:
    files = _tracked_files()
    assert files, "git ls-files returned nothing; the check would pass vacuously"
    assert _rendered(files, _read) == []


def test_ac7_positive_control_the_scan_finds_a_rendered_module() -> None:
    fake = {"mods/binding.js": f"// {MARKER} from client_bindings.claude_code.\n"}
    assert _rendered(["mods/binding.js", "README.md"], lambda f: fake.get(f, "")) == [
        "mods/binding.js"
    ]
