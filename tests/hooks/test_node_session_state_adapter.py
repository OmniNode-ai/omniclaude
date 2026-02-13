# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Tests for node_session_state_adapter.py

Verifies:
- init command: creates run doc, updates session index, returns run_id + state
- end command: transitions to run_ended, does NOT delete run doc
- set-active-run command: writes active_run_id to session.json
- Concurrent init calls create separate run docs
- Invalid transition: adapter returns {}, does not crash, exits 0
- Lock timeout: adapter returns {}, exits 0
- Empty/missing stdin: adapter returns {}, exits 0
- Invalid JSON stdin: adapter returns {}, exits 0

All tests use tmp_path fixture and CLAUDE_STATE_DIR env var override.

Related Tickets:
    - OMN-2119: Session State Orchestrator Shim + Adapter
"""

from __future__ import annotations

import json
import sys
import threading
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest

# Add hooks lib to path for imports
_HOOKS_LIB = Path(__file__).parent.parent.parent / "plugins" / "onex" / "hooks" / "lib"
if str(_HOOKS_LIB) not in sys.path:
    sys.path.insert(0, str(_HOOKS_LIB))

pytestmark = pytest.mark.unit


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(autouse=True)
def _state_dir(tmp_path, monkeypatch):
    """Configure CLAUDE_STATE_DIR to use tmp_path for all tests."""
    state_dir = str(tmp_path / "state")
    monkeypatch.setenv("CLAUDE_STATE_DIR", state_dir)
    return state_dir


def _run_adapter(command: str, stdin_data: dict | None = None) -> dict:
    """Helper: run the adapter with given command and stdin data.

    Mirrors the CLI fail-open behavior: catches all exceptions and returns {}.
    Returns the parsed JSON output.
    """
    from node_session_state_adapter import COMMANDS

    handler = COMMANDS.get(command)
    if handler is None:
        return {}

    data = stdin_data if stdin_data else {}
    try:
        return handler(data)
    except Exception:
        return {}


def _run_adapter_cli(command: str, stdin_data: dict | None = None) -> tuple[str, int]:
    """Helper: run the adapter via its main() CLI entry point.

    Returns (stdout_content, exit_code).
    """
    from node_session_state_adapter import main

    stdin_json = json.dumps(stdin_data) if stdin_data else ""
    stdout_capture = StringIO()

    with patch("sys.stdin", StringIO(stdin_json)), patch("sys.stdout", stdout_capture):
        exit_code = main([command])

    return stdout_capture.getvalue().strip(), exit_code


# =============================================================================
# Init Command Tests
# =============================================================================


class TestInitCommand:
    """Tests for the init command."""

    def test_init_creates_run_and_returns_state(self) -> None:
        """init command creates run doc and returns run_id + state=run_active."""
        result = _run_adapter("init", {"session_id": "sess-001"})
        assert "run_id" in result
        assert result["state"] == "run_active"
        assert len(result["run_id"]) > 0

    def test_init_creates_run_doc_on_disk(self) -> None:
        """init command writes a run context file to disk."""
        from node_session_state_effect import read_run_context

        result = _run_adapter("init", {"session_id": "sess-002"})
        run_id = result["run_id"]

        ctx = read_run_context(run_id)
        assert ctx is not None
        assert ctx.run_id == run_id
        assert ctx.session_id == "sess-002"
        assert ctx.state == "run_active"

    def test_init_updates_session_index(self) -> None:
        """init command updates session.json with the new run_id."""
        from node_session_state_effect import read_session_index

        result = _run_adapter("init", {"session_id": "sess-003"})
        run_id = result["run_id"]

        index = read_session_index()
        assert index.active_run_id == run_id
        assert run_id in index.recent_run_ids

    def test_init_without_session_id_returns_empty(self) -> None:
        """init command with missing session_id returns empty dict."""
        result = _run_adapter("init", {})
        assert result == {}

    def test_init_via_cli(self) -> None:
        """init command works via CLI entry point."""
        stdout, exit_code = _run_adapter_cli("init", {"session_id": "sess-cli"})
        assert exit_code == 0
        data = json.loads(stdout)
        assert "run_id" in data
        assert data["state"] == "run_active"


# =============================================================================
# End Command Tests
# =============================================================================


class TestEndCommand:
    """Tests for the end command."""

    def test_end_transitions_to_run_ended(self) -> None:
        """end command transitions an active run to run_ended."""
        init_result = _run_adapter("init", {"session_id": "sess-end-1"})
        run_id = init_result["run_id"]

        end_result = _run_adapter("end", {"run_id": run_id})
        assert end_result["run_id"] == run_id
        assert end_result["state"] == "run_ended"

    def test_end_does_not_delete_run_doc(self) -> None:
        """end command does NOT delete the run doc (GC handles cleanup)."""
        from node_session_state_effect import read_run_context

        init_result = _run_adapter("init", {"session_id": "sess-end-2"})
        run_id = init_result["run_id"]

        _run_adapter("end", {"run_id": run_id})

        ctx = read_run_context(run_id)
        assert ctx is not None
        assert ctx.state == "run_ended"

    def test_end_clears_active_run_id_when_active(self) -> None:
        """end command clears active_run_id in session.json when ended run is active."""
        from node_session_state_effect import read_session_index

        init_result = _run_adapter("init", {"session_id": "sess-end-active"})
        run_id = init_result["run_id"]

        # Verify the run is the active one
        index = read_session_index()
        assert index.active_run_id == run_id

        # End the run
        end_result = _run_adapter("end", {"run_id": run_id})
        assert end_result["state"] == "run_ended"

        # active_run_id should now be None
        index = read_session_index()
        assert index.active_run_id is None

    def test_end_preserves_active_run_id_when_different(self) -> None:
        """end command does not clear active_run_id if it references a different run."""
        from node_session_state_effect import read_session_index

        # Create two runs — the second becomes active
        init1 = _run_adapter("init", {"session_id": "sess-end-other"})
        run_id_1 = init1["run_id"]

        init2 = _run_adapter("init", {"session_id": "sess-end-other"})
        run_id_2 = init2["run_id"]

        # Verify run_id_2 is now active
        index = read_session_index()
        assert index.active_run_id == run_id_2

        # End run_id_1 (not the active run)
        end_result = _run_adapter("end", {"run_id": run_id_1})
        assert end_result["state"] == "run_ended"

        # active_run_id should still be run_id_2
        index = read_session_index()
        assert index.active_run_id == run_id_2

    def test_end_without_run_id_returns_empty(self) -> None:
        """end command with missing run_id returns empty dict."""
        result = _run_adapter("end", {})
        assert result == {}

    def test_end_nonexistent_run_returns_empty(self) -> None:
        """end command with unknown run_id returns empty dict."""
        result = _run_adapter("end", {"run_id": "nonexistent"})
        assert result == {}


# =============================================================================
# Set Active Run Command Tests
# =============================================================================


class TestSetActiveRunCommand:
    """Tests for the set-active-run command."""

    def test_set_active_run_updates_index(self) -> None:
        """set-active-run writes active_run_id to session.json."""
        from node_session_state_effect import read_session_index

        result = _run_adapter("set-active-run", {"run_id": "run-manual-1"})
        assert result["active_run_id"] == "run-manual-1"

        index = read_session_index()
        assert index.active_run_id == "run-manual-1"

    def test_set_active_run_without_run_id_returns_empty(self) -> None:
        """set-active-run with missing run_id returns empty dict."""
        result = _run_adapter("set-active-run", {})
        assert result == {}

    def test_set_active_run_via_cli(self) -> None:
        """set-active-run works via CLI entry point."""
        stdout, exit_code = _run_adapter_cli("set-active-run", {"run_id": "run-cli-1"})
        assert exit_code == 0
        data = json.loads(stdout)
        assert data["active_run_id"] == "run-cli-1"


# =============================================================================
# Concurrency Tests
# =============================================================================


class TestConcurrency:
    """Tests for concurrent access patterns."""

    def test_two_concurrent_inits_create_separate_runs(self, monkeypatch) -> None:
        """Two concurrent init calls create distinct run documents."""
        from node_session_state_effect import _runs_dir, _state_dir

        # Pre-create directories so threads don't race on mkdir
        _state_dir().mkdir(parents=True, exist_ok=True)
        _runs_dir().mkdir(parents=True, exist_ok=True)

        # Give threads enough time to acquire lock sequentially
        monkeypatch.setenv("CLAUDE_STATE_LOCK_TIMEOUT_MS", "2000")

        results: list[dict] = []
        errors: list[Exception] = []

        def do_init(session_id: str) -> None:
            try:
                r = _run_adapter("init", {"session_id": session_id})
                results.append(r)
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=do_init, args=("sess-t1",))
        t2 = threading.Thread(target=do_init, args=("sess-t2",))
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)

        assert not errors, f"Errors during concurrent init: {errors}"
        # Both should succeed (one waits for the other's lock)
        successful = [r for r in results if "run_id" in r]
        assert len(successful) == 2, (
            f"Expected 2 successful inits, got {len(successful)}: {results}"
        )

        run_ids = {r["run_id"] for r in successful}
        assert len(run_ids) == 2, "Both inits should create distinct run IDs"


# =============================================================================
# Error Handling Tests
# =============================================================================


class TestErrorHandling:
    """Tests for fail-open error handling."""

    def test_invalid_transition_returns_empty(self) -> None:
        """Invalid transition (e.g., end on an already-ended run) returns {}."""
        init_result = _run_adapter("init", {"session_id": "sess-err-1"})
        run_id = init_result["run_id"]

        # First end succeeds
        _run_adapter("end", {"run_id": run_id})

        # Second end should fail gracefully (run_ended + END_RUN is invalid)
        result = _run_adapter("end", {"run_id": run_id})
        assert result == {}

    def test_unknown_command_via_cli_returns_empty(self) -> None:
        """Unknown command via CLI returns {} and exits 0."""
        stdout, exit_code = _run_adapter_cli("nonexistent", {})
        assert exit_code == 0
        assert json.loads(stdout) == {}

    def test_empty_stdin_via_cli_returns_empty(self) -> None:
        """Empty stdin via CLI returns {} and exits 0."""
        from node_session_state_adapter import main

        stdout_capture = StringIO()
        with patch("sys.stdin", StringIO("")), patch("sys.stdout", stdout_capture):
            exit_code = main(["init"])

        assert exit_code == 0
        data = json.loads(stdout_capture.getvalue().strip())
        assert data == {}

    def test_invalid_json_stdin_via_cli_returns_empty(self) -> None:
        """Invalid JSON stdin via CLI returns {} and exits 0."""
        from node_session_state_adapter import main

        stdout_capture = StringIO()
        with (
            patch("sys.stdin", StringIO("not-json{")),
            patch("sys.stdout", stdout_capture),
        ):
            exit_code = main(["init"])

        assert exit_code == 0
        data = json.loads(stdout_capture.getvalue().strip())
        assert data == {}

    def test_no_command_via_cli_returns_empty(self) -> None:
        """No command via CLI returns {} and exits 0."""
        from node_session_state_adapter import main

        stdout_capture = StringIO()
        with patch("sys.stdin", StringIO("")), patch("sys.stdout", stdout_capture):
            exit_code = main([])

        assert exit_code == 0
        data = json.loads(stdout_capture.getvalue().strip())
        assert data == {}

    def test_lock_timeout_returns_empty(self, tmp_path, monkeypatch) -> None:
        """Lock timeout during init returns {} without crashing."""
        import fcntl
        import os

        from node_session_state_effect import _session_index_path

        # Ensure state dir and session.json exist
        path = _session_index_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}")

        # Hold the lock externally on the dedicated lock file
        lock_path = path.parent / "session.json.lock"
        fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

        try:
            monkeypatch.setenv("CLAUDE_STATE_LOCK_TIMEOUT_MS", "10")
            result = _run_adapter("init", {"session_id": "sess-lock"})
            # Should return {} due to lock timeout (fail-open)
            assert result == {}
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def test_lock_error_init_returns_empty(self, monkeypatch) -> None:
        """LockResult.ERROR during init returns {} without crashing."""
        from node_session_state_effect import LockResult

        monkeypatch.setattr(
            "node_session_state_effect.update_session_index",
            lambda _mutate_fn: LockResult.ERROR,
        )
        result = _run_adapter("init", {"session_id": "sess-lock-err"})
        assert result == {}

    def test_lock_error_init_cleans_orphan_run_doc(self, monkeypatch) -> None:
        """LockResult.ERROR during init cleans up the orphan run doc."""
        from node_session_state_effect import LockResult, _runs_dir

        monkeypatch.setattr(
            "node_session_state_effect.update_session_index",
            lambda _mutate_fn: LockResult.ERROR,
        )
        result = _run_adapter("init", {"session_id": "sess-orphan"})
        assert result == {}

        # Verify no run doc files remain (orphan was cleaned up)
        runs = _runs_dir()
        if runs.exists():
            json_files = list(runs.glob("*.json"))
            assert len(json_files) == 0, (
                f"Orphan run doc not cleaned up: {[f.name for f in json_files]}"
            )

    def test_cmd_end_succeeds_when_update_session_index_raises(
        self, monkeypatch
    ) -> None:
        """cmd_end still succeeds when update_session_index raises (best-effort)."""
        # First, create a run to end
        init_result = _run_adapter("init", {"session_id": "sess-end-lock"})
        assert "run_id" in init_result
        run_id = init_result["run_id"]

        # Patch update_session_index to raise during the end command's
        # best-effort active_run_id clearing
        def _raise(*args, **kwargs):
            raise OSError("simulated lock contention")

        monkeypatch.setattr("node_session_state_effect.update_session_index", _raise)

        # cmd_end should still succeed (the update_session_index call is
        # wrapped in try/except for best-effort behavior)
        result = _run_adapter("end", {"run_id": run_id})
        assert result["run_id"] == run_id
        assert result["state"] == "run_ended"

    def test_lock_error_set_active_run_returns_empty(self, monkeypatch) -> None:
        """LockResult.ERROR during set-active-run returns {} without crashing."""
        from node_session_state_effect import LockResult

        monkeypatch.setattr(
            "node_session_state_effect.update_session_index",
            lambda _mutate_fn: LockResult.ERROR,
        )
        result = _run_adapter("set-active-run", {"run_id": "run-lock-err"})
        assert result == {}


# =============================================================================
# Command Registry Tests
# =============================================================================


class TestCommandRegistry:
    """Tests for the COMMANDS registry."""

    def test_all_commands_registered(self) -> None:
        """All expected commands are in the registry."""
        from node_session_state_adapter import COMMANDS

        expected = {"init", "end", "set-active-run"}
        assert set(COMMANDS.keys()) == expected

    def test_all_commands_are_callable(self) -> None:
        """All registered commands are callable."""
        from node_session_state_adapter import COMMANDS

        for name, handler in COMMANDS.items():
            assert callable(handler), f"Command {name} is not callable"
