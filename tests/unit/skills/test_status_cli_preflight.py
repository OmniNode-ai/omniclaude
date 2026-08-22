# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Executable regression tests for the status snapshot CLI preflight (OMN-15545)."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


def _find_plugin_root() -> Path:
    """Resolve the bundled ONEX plugin independently of this test's depth."""
    for parent in Path(__file__).resolve().parents:
        plugin_root = parent / "plugins" / "onex"
        if (plugin_root / ".claude-plugin" / "plugin.json").is_file():
            return plugin_root
    raise RuntimeError("could not resolve plugins/onex from the test path")


PLUGIN_ROOT = _find_plugin_root()
SKILL_PATH = PLUGIN_ROOT / "skills" / "status" / "SKILL.md"
PLUGIN_MANIFEST_PATH = PLUGIN_ROOT / ".claude-plugin" / "plugin.json"

COMMAND_START = "<!-- status-snapshot-command:start -->"
COMMAND_END = "<!-- status-snapshot-command:end -->"


def _snapshot_script() -> str:
    """Return the executable one-shot command, including the legacy RED surface."""
    skill = SKILL_PATH.read_text(encoding="utf-8")
    marked = re.search(
        rf"{re.escape(COMMAND_START)}\s*```(?:sh|bash)\n(?P<script>.*?)\n```\s*"
        rf"{re.escape(COMMAND_END)}",
        skill,
        flags=re.DOTALL,
    )
    if marked:
        return marked.group("script")

    legacy = re.search(r"^1\. Run: (?P<script>.+)$", skill, flags=re.MULTILINE)
    assert legacy is not None, "status skill has no executable snapshot command"
    return legacy.group("script")


def _run_script(
    script: str, *, cwd: Path, bin_dir: Path
) -> subprocess.CompletedProcess[str]:
    """Execute the documented command with an intentionally minimal PATH."""
    if "uv run onex" in script:
        uv = shutil.which("uv")
        assert uv is not None, "RED baseline requires the current uv executable"
        (bin_dir / "uv").symlink_to(uv)

    env = os.environ.copy()
    env["PATH"] = str(bin_dir)
    return subprocess.run(
        ["/bin/sh", "-c", script],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


def test_missing_onex_from_arbitrary_cwd_uses_manifest_install_hint(
    tmp_path: Path,
) -> None:
    arbitrary_cwd = tmp_path / "outside-any-project"
    arbitrary_cwd.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    manifest = json.loads(PLUGIN_MANIFEST_PATH.read_text(encoding="utf-8"))
    install_hint = manifest["requires"]["onex_cli"]["install_hint"]

    result = _run_script(_snapshot_script(), cwd=arbitrary_cwd, bin_dir=bin_dir)

    assert not (arbitrary_cwd / "pyproject.toml").exists()
    assert not (arbitrary_cwd / "uv.lock").exists()
    assert result.returncode == 127
    assert result.stdout == ""
    assert result.stderr == (
        "ERROR: Required standalone ONEX CLI was not found on PATH. "
        f"Install it with: {install_hint}\n"
    )


def test_valid_onex_preserves_canonical_route_and_propagates_result(
    tmp_path: Path,
) -> None:
    arbitrary_cwd = tmp_path / "outside-any-project"
    arbitrary_cwd.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_onex = bin_dir / "onex"
    fake_onex.write_text(
        "#!/bin/sh\n"
        "printf 'arg:%s\\n' \"$@\"\n"
        "printf 'stdout-from-onex\\n'\n"
        "printf 'stderr-from-onex\\n' >&2\n"
        "exit 23\n",
        encoding="utf-8",
    )
    fake_onex.chmod(0o755)

    result = _run_script(_snapshot_script(), cwd=arbitrary_cwd, bin_dir=bin_dir)

    assert result.returncode == 23
    assert result.stdout.splitlines() == [
        "arg:run-node",
        "arg:node_pr_lifecycle_orchestrator",
        "arg:--input",
        'arg:{"dry_run": true, "inventory_only": true}',
        "stdout-from-onex",
    ]
    assert result.stderr == "stderr-from-onex\n"


def test_status_command_has_no_project_or_repo_local_fallback() -> None:
    script = _snapshot_script()

    assert "uv run onex" not in script
    assert "OMNI_HOME" not in script
    assert "OMNIMARKET_ROOT" not in script
    assert ".venv" not in script
    assert "gh " not in script
