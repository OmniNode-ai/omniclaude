# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Regression tests for hook repo-guard scoping.

Verifies that the following hooks short-circuit cleanly (exit 0, no block,
no noisy stdout reminder) when invoked in a non-OmniNode project:

* plugins/onex/hooks/post-tool-use-ci-reminder.sh
* plugins/onex/hooks/scripts/pre_tool_use_sweep_preflight.sh
* plugins/onex/hooks/scripts/pre_tool_use_prepush_validator.sh
* plugins/onex/hooks/scripts/post-tool-use-test-reminder.sh

Regression ticket: hook-scoping hotfix (external tester reports).
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import tempfile

import pytest

_TESTS_DIR = pathlib.Path(__file__).resolve().parent
_REPO_ROOT = _TESTS_DIR.parent.parent
_HOOKS_DIR = _REPO_ROOT / "plugins" / "onex" / "hooks"


def _make_external_project() -> str:
    """Create a tmpdir that looks like an unrelated third-party project."""
    tmp = tempfile.mkdtemp(prefix="external_project_")
    (pathlib.Path(tmp) / "README.md").write_text("# not omninode\n")
    # Stub a generic pyproject.toml that does NOT reference omnibase.
    (pathlib.Path(tmp) / "pyproject.toml").write_text(
        '[project]\nname = "third-party-lib"\n'
    )
    return tmp


def _run_hook(
    script_path: pathlib.Path, stdin_payload: dict, project_dir: str
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = project_dir
    env["HOME"] = project_dir
    env["LOG_FILE"] = os.path.join(project_dir, "hooks.log")
    return subprocess.run(
        ["bash", str(script_path)],
        input=json.dumps(stdin_payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
        cwd=project_dir,
        check=False,
    )


@pytest.mark.unit
class TestCiReminderScoping:
    def test_noop_in_external_repo(self):
        tmp = _make_external_project()
        try:
            stdin = {
                "tool_name": "Bash",
                "tool_input": {"command": "git commit -m test"},
                "tool_response": {"output": ""},
            }
            hook = _HOOKS_DIR / "post-tool-use-ci-reminder.sh"
            res = _run_hook(hook, stdin, tmp)
            assert res.returncode == 0, res.stderr
            # Must NOT inject "[CI Reminder]" into the stream for non-omninode.
            assert "[CI Reminder]" not in res.stdout
            assert "[CI Reminder]" not in res.stderr
        finally:
            import shutil

            shutil.rmtree(tmp, ignore_errors=True)


@pytest.mark.unit
class TestSweepPreflightScoping:
    def test_no_block_in_external_repo(self):
        tmp = _make_external_project()
        try:
            stdin = {
                "tool_name": "Bash",
                "tool_input": {"command": "gh pr list"},
            }
            hook = _HOOKS_DIR / "scripts" / "pre_tool_use_sweep_preflight.sh"
            res = _run_hook(hook, stdin, tmp)
            # The guard MUST short-circuit to exit 0 with no block decision.
            assert res.returncode == 0, (
                f"expected exit 0 in external repo, got {res.returncode}: "
                f"stderr={res.stderr!r}"
            )
            assert '"decision":"block"' not in res.stderr
            assert "gh CLI not found" not in res.stderr
        finally:
            import shutil

            shutil.rmtree(tmp, ignore_errors=True)


@pytest.mark.unit
class TestPrepushValidatorScoping:
    def test_noop_in_external_repo(self):
        tmp = _make_external_project()
        try:
            stdin = {
                "tool_name": "Bash",
                "tool_input": {"command": "git push origin main"},
            }
            hook = _HOOKS_DIR / "scripts" / "pre_tool_use_prepush_validator.sh"
            res = _run_hook(hook, stdin, tmp)
            assert res.returncode == 0, res.stderr
            assert '"decision":"block"' not in res.stderr
        finally:
            import shutil

            shutil.rmtree(tmp, ignore_errors=True)


@pytest.mark.unit
class TestTestReminderScoping:
    def test_noop_in_external_repo(self):
        tmp = _make_external_project()
        try:
            # Write a fake test file inside the external project so the
            # matcher pattern would otherwise fire.
            (pathlib.Path(tmp) / "tests").mkdir()
            target = pathlib.Path(tmp) / "tests" / "test_foo.py"
            target.write_text("def test_foo():\n    pass\n")
            stdin = {
                "tool_name": "Edit",
                "tool_input": {"file_path": str(target)},
                "tool_response": {"success": True},
            }
            hook = _HOOKS_DIR / "scripts" / "post-tool-use-test-reminder.sh"
            res = _run_hook(hook, stdin, tmp)
            assert res.returncode == 0, res.stderr
            # Must NOT inject "[Test Reminder]" for non-omninode project.
            assert "[Test Reminder]" not in res.stdout
        finally:
            import shutil

            shutil.rmtree(tmp, ignore_errors=True)
