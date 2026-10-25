# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The PR-body stamp guard imports on an interpreter that has no omniclaude install (OMN-20266).

The hook resolves ``PLUGIN_PYTHON_BIN`` first, and on a lab host that is a bare
Homebrew python3.13 with no editable omniclaude install. The decision
core imports the shared shell tokenizer from ``omniclaude``, so on such a host it
died with ``ModuleNotFoundError: No module named 'omniclaude'`` and every
body-replacing ``gh`` edit was refused as an unevaluable command.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GUARD_PY = REPO_ROOT / "plugins" / "onex" / "hooks" / "lib" / "pr_body_stamp_guard.py"


@pytest.mark.parametrize("installed", [True, False])
def test_guard_imports_without_installed_omniclaude_via_registry(
    tmp_path: Path,
    installed: bool,
) -> None:
    # An installed plugin copy has no src/ beside it: the registry clone is the source.
    copy = tmp_path / "plugin" / "plugins" / "onex" / "hooks" / "lib"
    copy.mkdir(parents=True)
    (copy / "pr_body_stamp_guard.py").write_text(
        GUARD_PY.read_text(encoding="utf-8"), encoding="utf-8"
    )
    config = tmp_path / "plugin" / "plugins" / "onex" / "hooks" / "config"
    config.mkdir()
    for f in (GUARD_PY.parents[1] / "config").iterdir():
        (config / f.name).write_bytes(f.read_bytes())
    for f in GUARD_PY.parent.glob("*.py"):
        if f.name != GUARD_PY.name:
            (copy / f.name).write_bytes(f.read_bytes())
    home = tmp_path / "home"
    home.mkdir()
    (home / "omniclaude").symlink_to(REPO_ROOT)
    env = {k: v for k, v in os.environ.items() if k not in {"PYTHONPATH"}}
    if installed:
        env["OMNI_HOME"] = str(home)
    else:
        env.pop("OMNI_HOME", None)
    result = subprocess.run(
        [
            sys.executable,
            "-S",
            str(copy / "pr_body_stamp_guard.py" if installed else GUARD_PY),
        ],
        input=json.dumps(
            {"tool_name": "Bash", "tool_input": {"command": "ls"}, "cwd": "/tmp"}
        ),
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=60,
    )
    assert "ModuleNotFoundError" not in result.stderr, result.stderr
    assert result.returncode == 0, result.stderr
