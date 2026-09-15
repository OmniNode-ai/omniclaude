# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""SessionStart preflight hook (OMN-18368).

Covers the mechanical wiring of the preflight skill's runner into every
session start: the hook must never block regardless of the runner's own exit
status, must stay silent in lite mode, must stay silent when every declared
check passes (the falsifier this ticket asks for), and must surface exactly
one line per failing blocker when the overlay declares one.

Hermetic: each case supplies its own overlay file and never touches the
developer's real ``SESSION_PREFLIGHT_OVERLAY_PATH``, state directory, or
plugin data venv.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PLUGIN = _REPO_ROOT / "plugins" / "onex"
_SCRIPT = _PLUGIN / "hooks" / "scripts" / "session_start_preflight.sh"

_STDIN = '{"session_id":"sess-preflight-01","cwd":"/tmp"}'


def _base_env(tmp_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    # Never let the developer's own persistent mode/intent preference leak in.
    env.pop("OMNICLAUDE_MODE", None)
    env.pop("SESSION_PREFLIGHT_OVERLAY_PATH", None)
    env.pop("SESSION_PREFLIGHT_RECEIPT", None)
    env["HOME"] = str(tmp_path / "home")
    (tmp_path / "home").mkdir(exist_ok=True)
    env["CLAUDE_PLUGIN_ROOT"] = str(_PLUGIN)
    return env


def _run(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    assert _SCRIPT.exists(), f"hook script not found at {_SCRIPT}"
    return subprocess.run(
        ["bash", str(_SCRIPT)],
        input=_STDIN,
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
        check=False,
        timeout=30,
        env=env,
    )


def _write_overlay(tmp_path: Path, checks: str) -> Path:
    overlay = tmp_path / "overlay.yaml"
    overlay.write_text(f"preflight_version: '1.0.0'\nchecks:\n{checks}\n")
    return overlay


@pytest.mark.unit
def test_never_blocks_in_lite_mode() -> None:
    """Lite mode: an external contributor's session gets zero preflight output."""
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        tmp_path = Path(td)
        env = _base_env(tmp_path)
        env["OMNICLAUDE_MODE"] = "lite"
        result = _run(env)

    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""


@pytest.mark.unit
def test_never_blocks_with_no_overlay_declared() -> None:
    """No SESSION_PREFLIGHT_OVERLAY_PATH set: the hook still exits 0.

    The runner itself refuses with exit 2 in this state (verified separately
    against the live plugin venv). The hook must swallow that non-zero exit
    and still surface the REFUSED line so a person can act on it.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        tmp_path = Path(td)
        env = _base_env(tmp_path)
        env["OMNICLAUDE_MODE"] = "full"
        result = _run(env)

    assert result.returncode == 0, (
        f"hook must never block; got exit {result.returncode}\n{result.stderr}"
    )
    assert "[preflight]" in result.stdout
    assert "REFUSED" in result.stdout
    assert "SESSION_PREFLIGHT_OVERLAY_PATH" in result.stdout


@pytest.mark.unit
def test_silent_when_every_check_passes() -> None:
    """Quiet-mode silence when clean: the ticket's stated falsifier."""
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        tmp_path = Path(td)
        overlay = _write_overlay(
            tmp_path,
            "  - check_id: always_true\n"
            "    title: A check that always passes\n"
            "    kind: command\n"
            "    severity: blocker\n"
            "    fix: 'nothing to fix'\n"
            "    command: 'true'\n",
        )
        env = _base_env(tmp_path)
        env["OMNICLAUDE_MODE"] = "full"
        env["SESSION_PREFLIGHT_OVERLAY_PATH"] = str(overlay)
        result = _run(env)

    assert result.returncode == 0
    assert result.stdout == "", (
        f"expected zero bytes when clean, got: {result.stdout!r}"
    )
    assert result.stderr == ""


@pytest.mark.unit
def test_prints_one_line_per_failing_blocker_and_still_exits_zero() -> None:
    """A failing blocker prints its fix command; the hook itself never blocks."""
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        tmp_path = Path(td)
        overlay = _write_overlay(
            tmp_path,
            "  - check_id: always_false\n"
            "    title: A check that always fails\n"
            "    kind: command\n"
            "    severity: blocker\n"
            "    fix: 'run: fix-the-thing --now'\n"
            "    command: 'false'\n",
        )
        env = _base_env(tmp_path)
        env["OMNICLAUDE_MODE"] = "full"
        env["SESSION_PREFLIGHT_OVERLAY_PATH"] = str(overlay)
        result = _run(env)

    assert result.returncode == 0, (
        f"hook must never block even on a blocked verdict; got {result.returncode}"
    )
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(lines) == 1, f"expected exactly one line, got: {lines!r}"
    assert lines[0].startswith("[preflight]")
    assert "A check that always fails" in lines[0]
    assert "fix-the-thing --now" in lines[0]
