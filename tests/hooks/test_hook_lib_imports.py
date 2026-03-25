# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Test that hook lib scripts can be imported as subprocesses.

Verifies OMN-6482 fix: hook lib __init__.py adds the repo root to
sys.path so that ``from plugins.onex.hooks.lib.X`` imports succeed
even when the module is loaded without the repo root on PYTHONPATH.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

HOOK_LIB_DIR = (
    Path(__file__).resolve().parents[2] / "plugins" / "onex" / "hooks" / "lib"
)


def _python_files() -> list[Path]:
    """Return all .py files in hook lib dir, excluding __init__ and private helpers."""
    return sorted(p for p in HOOK_LIB_DIR.glob("*.py") if not p.name.startswith("__"))


@pytest.mark.unit
@pytest.mark.parametrize("script", _python_files(), ids=lambda p: p.name)
def test_hook_lib_syntax_valid(script: Path) -> None:
    """Each hook lib script must be parseable (compile check, no execution)."""
    result = subprocess.run(
        [sys.executable, "-m", "py_compile", str(script)],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, f"{script.name} has syntax error:\n{result.stderr}"


@pytest.mark.unit
def test_hook_lib_init_adds_repo_root() -> None:
    """__init__.py must add the repo root to sys.path."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                f"sys.path.insert(0, {str(HOOK_LIB_DIR.parents[4])!r}); "
                "from plugins.onex.hooks.lib import _REPO_ROOT; "
                "assert _REPO_ROOT in sys.path, 'repo root not on sys.path'; "
                "print('OK')"
            ),
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
        env={"PATH": "/usr/bin:/usr/local/bin", "HOME": str(Path.home())},
    )
    assert result.returncode == 0, f"__init__.py guard failed:\n{result.stderr}"
    assert "OK" in result.stdout
