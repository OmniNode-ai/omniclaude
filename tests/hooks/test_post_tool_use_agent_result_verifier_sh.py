# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for post_tool_use_agent_result_verifier runner + shell wrapper.

The Python runner is exercised directly (OMN-9038 pattern) — it is the
unit that enforces block/pass semantics. The shell wrapper is tested at
the pass-through boundary only, because the repo-wide `error-guard.sh`
EXIT trap converts every non-zero hook exit to 0 by invariant. A hook
that wants to block must reach the user via stderr/stdout messaging;
exit-2 semantics live in the Python layer.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import unittest.mock as mock
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK_SCRIPT = (
    REPO_ROOT
    / "plugins"
    / "onex"
    / "hooks"
    / "scripts"
    / "post_tool_use_agent_result_verifier.sh"
)


# =============================================================================
# Python runner — the unit of enforcement
# =============================================================================


class TestRunnerBlocksOnFabricatedPr:
    """Runner returns exit code 2 when a pr_merged claim is fabricated."""

    def test_fabricated_pr_returns_2(self, capsys: pytest.CaptureFixture[str]) -> None:
        from plugins.onex.hooks.lib.agent_result_verifier_runner import run

        # Mock subprocess.run to simulate `gh pr view` failing (PR not found).
        fake_proc = mock.MagicMock(
            returncode=1, stdout="", stderr="HTTP 404: Not Found"
        )
        body = "All done. PR #99999999 merged at 07:56Z."
        with mock.patch(
            "plugins.onex.hooks.lib.agent_result_verifier_runner.subprocess.run",
            return_value=fake_proc,
        ):
            rc = run(body, repo_hint="omniclaude")
        assert rc == 2
        out = capsys.readouterr().out
        payload = json.loads(out)
        assert len(payload["mismatches"]) == 1
        mismatch = payload["mismatches"][0]
        assert mismatch["claim"]["ref"] == "omniclaude#99999999"
        assert "not found" in mismatch["reason"].lower()

    def test_open_pr_state_returns_2(self, capsys: pytest.CaptureFixture[str]) -> None:
        from plugins.onex.hooks.lib.agent_result_verifier_runner import run

        # gh returned success but state=OPEN — claim misstates the outcome.
        fake_proc = mock.MagicMock(
            returncode=0,
            stdout=json.dumps({"state": "OPEN", "number": 123}),
            stderr="",
        )
        body = "All done. PR #123 merged at 07:56Z."
        with mock.patch(
            "plugins.onex.hooks.lib.agent_result_verifier_runner.subprocess.run",
            return_value=fake_proc,
        ):
            rc = run(body, repo_hint="omniclaude")
        assert rc == 2
        payload = json.loads(capsys.readouterr().out)
        assert payload["mismatches"][0]["reason"].startswith("PR omniclaude#123 state")


class TestRunnerPasses:
    """Runner returns 0 on verified claims, no claims, or resolver unreachable."""

    def test_verified_merged_pr_returns_0(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from plugins.onex.hooks.lib.agent_result_verifier_runner import run

        fake_proc = mock.MagicMock(
            returncode=0,
            stdout=json.dumps({"state": "MERGED", "number": 1}),
            stderr="",
        )
        with mock.patch(
            "plugins.onex.hooks.lib.agent_result_verifier_runner.subprocess.run",
            return_value=fake_proc,
        ):
            rc = run("PR #1 merged.", repo_hint="omniclaude")
        assert rc == 0
        assert capsys.readouterr().out == ""

    def test_no_claims_returns_0(self, capsys: pytest.CaptureFixture[str]) -> None:
        from plugins.onex.hooks.lib.agent_result_verifier_runner import run

        rc = run("Just prose, nothing to verify.", repo_hint="omniclaude")
        assert rc == 0
        assert capsys.readouterr().out == ""

    def test_gh_unavailable_fails_open(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from plugins.onex.hooks.lib.agent_result_verifier_runner import run

        with mock.patch(
            "plugins.onex.hooks.lib.agent_result_verifier_runner.subprocess.run",
            side_effect=FileNotFoundError("gh not found"),
        ):
            rc = run("PR #1 merged.", repo_hint="omniclaude")
        assert rc == 0  # fail-open

    def test_thread_resolved_short_circuits_to_pass(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from plugins.onex.hooks.lib.agent_result_verifier_runner import run

        # Scaffold posture: thread_resolved claims don't hit the resolver.
        body = "Resolved CR thread PRRT_kwDOP_NzS857mezy with reply + resolve."
        with mock.patch(
            "plugins.onex.hooks.lib.agent_result_verifier_runner.subprocess.run"
        ) as mocked:
            rc = run(body, repo_hint="omniclaude")
            mocked.assert_not_called()
        assert rc == 0


class TestRunnerMainStdin:
    """`python -m agent_result_verifier_runner` reads stdin and REPO_HINT env."""

    def test_main_reads_stdin(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from plugins.onex.hooks.lib import agent_result_verifier_runner as runner

        monkeypatch.setattr("sys.stdin", io.StringIO("Plain prose, no claims."))
        monkeypatch.setenv("REPO_HINT", "omniclaude")
        assert runner.main() == 0


# =============================================================================
# Shell wrapper — pass-through boundary only
# =============================================================================


def _run_hook(
    payload: dict[str, object], tmp_path: Path
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["ONEX_STATE_DIR"] = str(tmp_path)
    env["OMN_9055_AGENT_VERIFIER_DISABLED"] = "0"
    env.pop("OMNICLAUDE_MODE", None)
    env.pop("CLAUDE_PLUGIN_ROOT", None)
    return subprocess.run(  # nosec: B603
        ["bash", str(HOOK_SCRIPT)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
        check=False,
    )


class TestShellWrapperPassThrough:
    """Shell wrapper must never raise or crash; error-guard swallows non-zero."""

    def test_non_agent_tool_passes_through(self, tmp_path: Path) -> None:
        payload = {
            "tool_name": "Bash",
            "tool_response": {"content": "PR #1 merged"},
        }
        result = _run_hook(payload, tmp_path)
        assert result.returncode == 0, result.stderr

    def test_empty_body_passes_through(self, tmp_path: Path) -> None:
        payload = {"tool_name": "Agent", "tool_response": {"content": ""}}
        result = _run_hook(payload, tmp_path)
        assert result.returncode == 0, result.stderr

    def test_script_is_executable(self) -> None:
        assert HOOK_SCRIPT.exists()
        assert os.access(HOOK_SCRIPT, os.X_OK)
