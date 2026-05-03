# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for task_boundary_tests hook — test discovery and execution.

Coverage:
    - Trigger condition matching (git commit / gh pr create)
    - Non-trigger commands pass through
    - Debounce logic (skip if <60s)
    - Test discovery heuristics (file path → test file mapping)
    - Skip when no tests found
    - Skip when no staged Python files
    - Timeout handling (failing open)
    - Full main() integration with mocked subprocess/git
"""

from __future__ import annotations

import io
import json
import os
import pathlib
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

_LIB_DIR = (
    pathlib.Path(__file__).parent.parent.parent / "plugins" / "onex" / "hooks" / "lib"
)
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

import task_boundary_tests as tbt  # noqa: E402


class TestTriggerConditions:
    def test_git_commit_triggers(self) -> None:
        assert tbt._is_trigger_command("git commit -m 'fix: thing'")

    def test_git_commit_with_ampersand(self) -> None:
        assert tbt._is_trigger_command("ruff check src/ && git commit -m 'x'")

    def test_git_commit_with_semicolon(self) -> None:
        assert tbt._is_trigger_command("echo hi; git commit -m 'x'")

    def test_git_commit_with_pipe(self) -> None:
        assert tbt._is_trigger_command("echo hi | git commit -m 'x'")

    def test_git_commit_with_or_pipe(self) -> None:
        assert tbt._is_trigger_command("echo hi || git commit -m 'x'")

    def test_gh_pr_create_triggers(self) -> None:
        assert tbt._is_trigger_command("gh pr create --title 'x'")

    def test_gh_pr_create_with_pipe(self) -> None:
        assert tbt._is_trigger_command("echo body | gh pr create --title 'x'")

    def test_gh_pr_create_with_or_pipe(self) -> None:
        assert tbt._is_trigger_command("echo body || gh pr create --title 'x'")

    def test_gh_pr_create_with_semicolon(self) -> None:
        assert tbt._is_trigger_command("echo hi; gh pr create --title 'x'")

    def test_git_push_does_not_trigger(self) -> None:
        assert not tbt._is_trigger_command("git push origin main")

    def test_ls_does_not_trigger(self) -> None:
        assert not tbt._is_trigger_command("ls -la")

    def test_git_status_does_not_trigger(self) -> None:
        assert not tbt._is_trigger_command("git status")

    def test_pytest_does_not_trigger(self) -> None:
        assert not tbt._is_trigger_command("pytest tests/ -v")

    def test_empty_command_does_not_trigger(self) -> None:
        assert not tbt._is_trigger_command("")


class TestDebounceLogic:
    def test_no_marker_file_means_no_skip(self, tmp_path: Path) -> None:
        key = str(tmp_path / "nonexistent")
        assert not tbt._should_skip_debounce(key)

    def test_recent_marker_means_skip(self, tmp_path: Path) -> None:
        marker = tmp_path / "last_run"
        marker.touch()
        key = str(marker)
        assert tbt._should_skip_debounce(key)

    def test_old_marker_means_no_skip(self, tmp_path: Path) -> None:
        marker = tmp_path / "last_run"
        marker.touch()
        old_time = time.time() - 120
        os.utime(str(marker), (old_time, old_time))
        key = str(marker)
        assert not tbt._should_skip_debounce(key)

    def test_debounce_key_deterministic(self) -> None:
        root = Path("/some/repo")
        k1 = tbt._debounce_key(root)
        k2 = tbt._debounce_key(root)
        assert k1 == k2

    def test_debounce_key_differs_per_repo(self) -> None:
        k1 = tbt._debounce_key(Path("/repo/a"))
        k2 = tbt._debounce_key(Path("/repo/b"))
        assert k1 != k2

    def test_touch_debounce_creates_file(self, tmp_path: Path) -> None:
        marker = tmp_path / "marker"
        tbt._touch_debounce(str(marker))
        assert marker.exists()


class TestDiscoverTests:
    def test_finds_matching_test_file(self, tmp_path: Path) -> None:
        tests = tmp_path / "tests"
        tests.mkdir()
        (tests / "test_foo.py").write_text("# test")
        result = tbt._discover_tests(tmp_path, ["foo.py"])
        assert len(result) == 1
        assert "test_foo.py" in result[0]

    def test_finds_nested_test_file(self, tmp_path: Path) -> None:
        tests = tmp_path / "tests" / "sub"
        tests.mkdir(parents=True)
        (tests / "test_bar.py").write_text("# test")
        result = tbt._discover_tests(tmp_path, ["sub/bar.py"])
        assert len(result) == 1
        assert "test_bar.py" in result[0]

    def test_finds_hooks_test_file(self, tmp_path: Path) -> None:
        tests = tmp_path / "tests" / "hooks"
        tests.mkdir(parents=True)
        (tests / "test_baz.py").write_text("# test")
        result = tbt._discover_tests(tmp_path, ["hooks/baz.py"])
        assert len(result) == 1
        assert "test_baz.py" in result[0]

    def test_no_tests_dir_returns_empty(self, tmp_path: Path) -> None:
        result = tbt._discover_tests(tmp_path, ["foo.py"])
        assert result == []

    def test_no_matching_test_returns_empty(self, tmp_path: Path) -> None:
        tests = tmp_path / "tests"
        tests.mkdir()
        result = tbt._discover_tests(tmp_path, ["nonexistent.py"])
        assert result == []

    def test_deduplication(self, tmp_path: Path) -> None:
        tests = tmp_path / "tests"
        tests.mkdir()
        (tests / "test_foo.py").write_text("# test")
        result = tbt._discover_tests(tmp_path, ["foo.py", "foo.py"])
        assert len(result) == 1


class TestStagedPythonFiles:
    def test_returns_empty_on_non_repo(self, tmp_path: Path) -> None:
        with patch("subprocess.run", side_effect=Exception("boom")):
            result = tbt._staged_python_files(tmp_path)
        assert result == []


class TestRunTests:
    def test_passing_tests(self, tmp_path: Path) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "1 passed"
        mock_result.stderr = ""
        with patch("subprocess.run", return_value=mock_result):
            ok, msg = tbt._run_tests(tmp_path, ["test_foo.py"])
        assert ok is True
        assert msg == ""

    def test_uses_subprocess_timeout_without_pytest_timeout_plugin(
        self, tmp_path: Path
    ) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "1 passed"
        mock_result.stderr = ""
        with patch("subprocess.run", return_value=mock_result) as run:
            ok, msg = tbt._run_tests(tmp_path, ["test_foo.py"])

        assert ok is True
        assert msg == ""
        args = run.call_args.args[0]
        assert "--timeout=120" not in args
        assert run.call_args.kwargs["timeout"] == tbt.TEST_TIMEOUT_SECONDS

    def test_failing_tests(self, tmp_path: Path) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = "FAILED test_foo.py::test_x - assert False"
        mock_result.stderr = ""
        with patch("subprocess.run", return_value=mock_result):
            ok, msg = tbt._run_tests(tmp_path, ["test_foo.py"])
        assert ok is False
        assert "FAILED" in msg

    def test_timeout_fails_open(self, tmp_path: Path) -> None:
        import subprocess

        with patch(
            "subprocess.run", side_effect=subprocess.TimeoutExpired("pytest", 120)
        ):
            ok, msg = tbt._run_tests(tmp_path, ["test_foo.py"])
        assert ok is True
        assert "timed out" in msg

    def test_missing_pytest_fails_open(self, tmp_path: Path) -> None:
        with patch("subprocess.run", side_effect=FileNotFoundError):
            ok, msg = tbt._run_tests(tmp_path, ["test_foo.py"])
        assert ok is True
        assert "pytest not found" in msg


class TestMainIntegration:
    @staticmethod
    def _run_main(hook_input: dict) -> tuple[str, int]:
        raw = json.dumps(hook_input)
        captured = io.StringIO()
        with patch("sys.stdin", io.StringIO(raw)):
            with patch("sys.stdout", captured):
                try:
                    tbt.main()
                    code = 0
                except SystemExit as exc:
                    code = exc.code if isinstance(exc.code, int) else 0
        return captured.getvalue(), code

    def test_non_bash_passes_through(self) -> None:
        out, code = self._run_main({"tool_name": "Read", "tool_input": {}})
        assert code == 0
        assert json.loads(out)["tool_name"] == "Read"

    def test_non_trigger_command_passes_through(self) -> None:
        out, code = self._run_main(
            {"tool_name": "Bash", "tool_input": {"command": "git push origin main"}}
        )
        assert code == 0
        assert json.loads(out)["tool_name"] == "Bash"

    def test_trigger_but_no_staged_files_passes(self) -> None:
        with patch.object(tbt, "_repo_root_for", return_value=Path("/fake")):
            with patch.object(tbt, "_staged_python_files", return_value=[]):
                out, code = self._run_main(
                    {
                        "tool_name": "Bash",
                        "tool_input": {"command": "git commit -m 'x'"},
                    }
                )
        assert code == 0

    def test_trigger_but_no_tests_found_passes(self) -> None:
        with patch.object(tbt, "_repo_root_for", return_value=Path("/fake")):
            with patch.object(tbt, "_staged_python_files", return_value=["foo.py"]):
                with patch.object(tbt, "_discover_tests", return_value=[]):
                    out, code = self._run_main(
                        {
                            "tool_name": "Bash",
                            "tool_input": {"command": "git commit -m 'x'"},
                        }
                    )
        assert code == 0

    def test_trigger_debounced_passes(self) -> None:
        with patch.object(tbt, "_repo_root_for", return_value=Path("/fake")):
            with patch.object(tbt, "_should_skip_debounce", return_value=True):
                out, code = self._run_main(
                    {
                        "tool_name": "Bash",
                        "tool_input": {"command": "git commit -m 'x'"},
                    }
                )
        assert code == 0

    def test_failing_tests_blocks(self) -> None:
        with patch.object(tbt, "_repo_root_for", return_value=Path("/fake")):
            with patch.object(tbt, "_staged_python_files", return_value=["foo.py"]):
                with patch.object(
                    tbt, "_discover_tests", return_value=["tests/test_foo.py"]
                ):
                    with patch.object(tbt, "_should_skip_debounce", return_value=False):
                        with patch.object(
                            tbt, "_run_tests", return_value=(False, "FAILED test_x")
                        ):
                            with patch.object(tbt, "_touch_debounce"):
                                out, code = self._run_main(
                                    {
                                        "tool_name": "Bash",
                                        "tool_input": {"command": "git commit -m 'x'"},
                                    }
                                )
        assert code == 2
        result = json.loads(out)
        assert result["decision"] == "block"
        assert "FAILED" in result["reason"]

    def test_passing_tests_allows(self) -> None:
        with patch.object(tbt, "_repo_root_for", return_value=Path("/fake")):
            with patch.object(tbt, "_staged_python_files", return_value=["foo.py"]):
                with patch.object(
                    tbt, "_discover_tests", return_value=["tests/test_foo.py"]
                ):
                    with patch.object(tbt, "_should_skip_debounce", return_value=False):
                        with patch.object(tbt, "_run_tests", return_value=(True, "")):
                            with patch.object(tbt, "_touch_debounce"):
                                out, code = self._run_main(
                                    {
                                        "tool_name": "Bash",
                                        "tool_input": {"command": "git commit -m 'x'"},
                                    }
                                )
        assert code == 0
        assert json.loads(out)["tool_name"] == "Bash"

    def test_debounce_marker_touched_only_after_success(self) -> None:
        with patch.object(tbt, "_repo_root_for", return_value=Path("/fake")):
            with patch.object(tbt, "_staged_python_files", return_value=["foo.py"]):
                with patch.object(
                    tbt, "_discover_tests", return_value=["tests/test_foo.py"]
                ):
                    with patch.object(tbt, "_should_skip_debounce", return_value=False):
                        with patch.object(
                            tbt, "_run_tests", return_value=(False, "FAILED test_x")
                        ):
                            with patch.object(tbt, "_touch_debounce") as touch:
                                out, code = self._run_main(
                                    {
                                        "tool_name": "Bash",
                                        "tool_input": {"command": "git commit -m 'x'"},
                                    }
                                )
        assert code == 2
        assert "FAILED" in json.loads(out)["reason"]
        touch.assert_not_called()


class TestRepoRootFor:
    def test_finds_git_dir(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        result = tbt._repo_root_for(str(tmp_path))
        assert result == tmp_path

    def test_finds_git_file(self, tmp_path: Path) -> None:
        (tmp_path / ".git").write_text("gitdir: something")
        result = tbt._repo_root_for(str(tmp_path))
        assert result == tmp_path

    def test_returns_none_when_no_git(self, tmp_path: Path) -> None:
        sub = tmp_path / "subdir"
        sub.mkdir()
        result = tbt._repo_root_for(str(sub))
        assert result is None


class TestShellHook:
    @staticmethod
    def _run_shell_hook(
        extra_env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess:
        repo_root = pathlib.Path(__file__).parent.parent.parent
        script = (
            repo_root
            / "plugins"
            / "onex"
            / "hooks"
            / "scripts"
            / "pre_tool_use_task_boundary_tests.sh"
        )
        payload = {
            "tool_name": "Bash",
            "tool_input": {"command": "git commit -m 'x'"},
        }
        env = os.environ.copy()
        env.update(
            {
                "CLAUDE_PLUGIN_ROOT": str(repo_root / "plugins" / "onex"),
                "CLAUDE_PROJECT_DIR": str(repo_root),
                "ONEX_HOOKS_MASK": "0",
                "ONEX_STATE_DIR": str(repo_root / ".onex_state_test"),
            }
        )
        if extra_env:
            env.update(extra_env)

        return subprocess.run(
            [str(script.resolve())],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            env=env,
            check=False,
            timeout=10,
        )

    def test_shell_hook_drains_input_when_gate_disabled(self) -> None:
        payload = {
            "tool_name": "Bash",
            "tool_input": {"command": "git commit -m 'x'"},
        }
        result = self._run_shell_hook({"ONEX_HOOKS_MASK": "0"})

        assert result.returncode == 0
        assert json.loads(result.stdout) == payload

    def test_shell_hook_is_disabled_without_explicit_mask(self) -> None:
        payload = {
            "tool_name": "Bash",
            "tool_input": {"command": "git commit -m 'x'"},
        }
        result = self._run_shell_hook({"ONEX_HOOKS_MASK": ""})

        assert result.returncode == 0
        assert json.loads(result.stdout) == payload

    def test_shell_hook_fails_open_when_common_script_missing(
        self, tmp_path: Path
    ) -> None:
        payload = {
            "tool_name": "Bash",
            "tool_input": {"command": "git commit -m 'x'"},
        }
        fake_plugin = tmp_path / "plugin"
        (fake_plugin / "hooks" / "lib").mkdir(parents=True)
        result = self._run_shell_hook(
            {
                "CLAUDE_PLUGIN_ROOT": str(fake_plugin),
                "ONEX_HOOKS_MASK": "0x400000000000000",
                "ONEX_STATE_DIR": str(tmp_path / "state"),
            }
        )

        assert result.returncode == 0
        assert json.loads(result.stdout) == payload

    def test_shell_hook_fails_open_when_hook_bits_source_fails(
        self, tmp_path: Path
    ) -> None:
        payload = {
            "tool_name": "Bash",
            "tool_input": {"command": "git commit -m 'x'"},
        }
        fake_plugin = tmp_path / "plugin"
        (fake_plugin / "hooks" / "lib").mkdir(parents=True)
        (fake_plugin / "hooks" / "lib" / "hook_bits.sh").write_text("return 1\n")
        result = self._run_shell_hook(
            {
                "CLAUDE_PLUGIN_ROOT": str(fake_plugin),
                "ONEX_HOOKS_MASK": "0x400000000000000",
                "ONEX_STATE_DIR": str(tmp_path / "state"),
            }
        )

        assert result.returncode == 0
        assert json.loads(result.stdout) == payload

    def test_shell_hook_fails_open_when_runner_missing(self, tmp_path: Path) -> None:
        payload = {
            "tool_name": "Bash",
            "tool_input": {"command": "git commit -m 'x'"},
        }
        fake_plugin = tmp_path / "plugin"
        (fake_plugin / "hooks" / "lib").mkdir(parents=True)
        (fake_plugin / "hooks" / "scripts").mkdir(parents=True)
        (fake_plugin / "hooks" / "lib" / "hook_bits.sh").write_text(
            "\n".join(
                [
                    "HOOK_BITS_DEFAULT_MASK=0x0",
                    "hook_bits_bit_for_name() { echo 0x400000000000000; }",
                    'hook_bits_parse_mask() { echo "$1"; }',
                    "hook_bits_is_enabled() { return 0; }",
                    "",
                ]
            )
        )
        (fake_plugin / "hooks" / "scripts" / "common.sh").write_text(
            "PYTHON_CMD=/usr/bin/python3\nexport PYTHON_CMD\n"
        )
        result = self._run_shell_hook(
            {
                "CLAUDE_PLUGIN_ROOT": str(fake_plugin),
                "ONEX_HOOKS_MASK": "0x400000000000000",
                "ONEX_STATE_DIR": str(tmp_path / "state"),
            }
        )

        assert result.returncode == 0
        assert json.loads(result.stdout) == payload
