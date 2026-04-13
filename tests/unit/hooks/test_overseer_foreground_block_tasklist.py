# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for overseer_foreground_block TaskList fallback (insights Task 1).

Verifies the secondary detection path:
  * When flag absent + no CLAUDE_AGENT_ID → no warning.
  * When flag absent + CLAUDE_AGENT_ID set + foreign in-progress task updated
    within 15 min → block fires in 'block' mode, warn emitted in 'warn' mode.
  * When flag absent + all tasks self-owned → no warning.
  * When flag absent + foreign task is stale (>15 min) → no warning.
  * When flag absent + TaskList subprocess fails → no warning (fail open).
"""

from __future__ import annotations

import io
import json
import pathlib
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

_LIB_DIR = (
    pathlib.Path(__file__).parent.parent.parent.parent
    / "plugins"
    / "onex"
    / "hooks"
    / "lib"
)
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

import overseer_foreground_block as ofb  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(
    payload: dict[str, Any],
    *,
    agent_id: str = "",
    enforcement_mode: str = "block",
    tasklist_output: list[dict] | None = None,
    tasklist_returncode: int = 0,
    tasklist_raises: type[Exception] | None = None,
) -> tuple[str, int]:
    """Run main() with patched environment and subprocess."""
    raw = json.dumps(payload)
    captured = io.StringIO()
    env_patch: dict[str, str] = {"ENFORCEMENT_MODE": enforcement_mode}
    if agent_id:
        env_patch["CLAUDE_AGENT_ID"] = agent_id

    def _fake_run(*args: Any, **kwargs: Any) -> MagicMock:
        if tasklist_raises is not None:
            raise tasklist_raises()
        result = MagicMock()
        result.returncode = tasklist_returncode
        result.stdout = json.dumps(tasklist_output or [])
        return result

    with (
        patch("sys.stdin", io.StringIO(raw)),
        patch("sys.stdout", captured),
        patch.dict("os.environ", env_patch, clear=False),
        patch.object(ofb, "subprocess", wraps=subprocess) as mock_sub,
    ):
        mock_sub.run.side_effect = _fake_run
        mock_sub.TimeoutExpired = subprocess.TimeoutExpired
        exit_code = ofb.main()
    return captured.getvalue().strip(), exit_code


def _fresh_task(owner: str, age_seconds: int = 60) -> dict[str, Any]:
    updated = datetime.now(tz=UTC) - timedelta(seconds=age_seconds)
    return {
        "status": "in_progress",
        "owner": owner,
        "updated_at": updated.isoformat(),
    }


def _stale_task(owner: str) -> dict[str, Any]:
    """Task updated 20 minutes ago — beyond the 15-minute recency window."""
    return _fresh_task(owner, age_seconds=20 * 60)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def omni_home(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> pathlib.Path:
    root = tmp_path / "omni_home"
    root.mkdir()
    monkeypatch.setenv("OMNI_HOME", str(root))
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    monkeypatch.setenv("ONEX_STATE_DIR", str(state_dir))
    return root


# ---------------------------------------------------------------------------
# TaskList fallback — flag absent
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTaskListFallback:
    def test_no_agent_id_skips_tasklist(self, omni_home: pathlib.Path) -> None:
        """Without CLAUDE_AGENT_ID the guard must not invoke TaskList."""
        target = omni_home / "repo" / "f.py"
        target.parent.mkdir(parents=True)
        out, code = _run(
            {"tool_name": "Edit", "tool_input": {"file_path": str(target)}},
            agent_id="",
        )
        assert code == 0
        assert out == "{}"

    def test_foreign_task_recent_blocks_in_block_mode(
        self, omni_home: pathlib.Path
    ) -> None:
        """Foreign in-progress task within 15 min → block when ENFORCEMENT_MODE=block."""
        target = omni_home / "repo" / "f.py"
        target.parent.mkdir(parents=True)
        out, code = _run(
            {"tool_name": "Edit", "tool_input": {"file_path": str(target)}},
            agent_id="agent-lead",
            enforcement_mode="block",
            tasklist_output=[_fresh_task("agent-overseer")],
        )
        assert code == 2
        payload = json.loads(out)
        assert payload["decision"] == "block"
        assert "delegation guard" in payload["reason"].lower()

    def test_foreign_task_recent_warns_in_warn_mode(
        self, omni_home: pathlib.Path
    ) -> None:
        """Foreign in-progress task within 15 min → warn (exit 0) in warn mode."""
        target = omni_home / "repo" / "f.py"
        target.parent.mkdir(parents=True)
        out, code = _run(
            {"tool_name": "Edit", "tool_input": {"file_path": str(target)}},
            agent_id="agent-lead",
            enforcement_mode="warn",
            tasklist_output=[_fresh_task("agent-overseer")],
        )
        assert code == 0
        payload = json.loads(out)
        assert payload["decision"] == "warn"

    def test_foreign_task_recent_silent_mode_allows(
        self, omni_home: pathlib.Path
    ) -> None:
        """Silent mode emits nothing and allows the tool."""
        target = omni_home / "repo" / "f.py"
        target.parent.mkdir(parents=True)
        out, code = _run(
            {"tool_name": "Edit", "tool_input": {"file_path": str(target)}},
            agent_id="agent-lead",
            enforcement_mode="silent",
            tasklist_output=[_fresh_task("agent-overseer")],
        )
        assert code == 0
        assert out == "{}"

    def test_self_owned_task_no_block(self, omni_home: pathlib.Path) -> None:
        """All in-progress tasks owned by self → no warning."""
        target = omni_home / "repo" / "f.py"
        target.parent.mkdir(parents=True)
        out, code = _run(
            {"tool_name": "Edit", "tool_input": {"file_path": str(target)}},
            agent_id="agent-lead",
            enforcement_mode="block",
            tasklist_output=[_fresh_task("agent-lead")],
        )
        assert code == 0
        assert out == "{}"

    def test_stale_foreign_task_no_block(self, omni_home: pathlib.Path) -> None:
        """Foreign task updated >15 min ago → no warning."""
        target = omni_home / "repo" / "f.py"
        target.parent.mkdir(parents=True)
        out, code = _run(
            {"tool_name": "Edit", "tool_input": {"file_path": str(target)}},
            agent_id="agent-lead",
            enforcement_mode="block",
            tasklist_output=[_stale_task("agent-overseer")],
        )
        assert code == 0
        assert out == "{}"

    def test_empty_tasklist_no_block(self, omni_home: pathlib.Path) -> None:
        """Empty TaskList → no warning."""
        target = omni_home / "repo" / "f.py"
        target.parent.mkdir(parents=True)
        out, code = _run(
            {"tool_name": "Edit", "tool_input": {"file_path": str(target)}},
            agent_id="agent-lead",
            enforcement_mode="block",
            tasklist_output=[],
        )
        assert code == 0
        assert out == "{}"

    def test_tasklist_subprocess_failure_fails_open(
        self, omni_home: pathlib.Path
    ) -> None:
        """subprocess.run raising FileNotFoundError must fail open (no block)."""
        target = omni_home / "repo" / "f.py"
        target.parent.mkdir(parents=True)
        out, code = _run(
            {"tool_name": "Edit", "tool_input": {"file_path": str(target)}},
            agent_id="agent-lead",
            enforcement_mode="block",
            tasklist_raises=FileNotFoundError,
        )
        assert code == 0
        assert out == "{}"

    def test_tasklist_nonzero_returncode_fails_open(
        self, omni_home: pathlib.Path
    ) -> None:
        """Non-zero exit from claude task list → fail open."""
        target = omni_home / "repo" / "f.py"
        target.parent.mkdir(parents=True)
        out, code = _run(
            {"tool_name": "Edit", "tool_input": {"file_path": str(target)}},
            agent_id="agent-lead",
            enforcement_mode="block",
            tasklist_output=[_fresh_task("agent-overseer")],
            tasklist_returncode=1,
        )
        assert code == 0
        assert out == "{}"

    def test_tool_outside_omni_home_not_blocked(
        self, omni_home: pathlib.Path, tmp_path: pathlib.Path
    ) -> None:
        """Foreign task present but tool targets path outside OMNI_HOME → no block."""
        other = tmp_path / "elsewhere" / "f.py"
        other.parent.mkdir(parents=True)
        out, code = _run(
            {"tool_name": "Edit", "tool_input": {"file_path": str(other)}},
            agent_id="agent-lead",
            enforcement_mode="block",
            tasklist_output=[_fresh_task("agent-overseer")],
        )
        assert code == 0
        assert out == "{}"
