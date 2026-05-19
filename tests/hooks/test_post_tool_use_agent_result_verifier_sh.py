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


class TestRunnerBlocksOnFabricatedClaims:
    """Runner returns exit code 2 when resolver reports mismatches."""

    def test_fabricated_pr_returns_2(self, capsys: pytest.CaptureFixture[str]) -> None:
        from plugins.onex.hooks.lib.agent_result_verifier_runner import run

        body = "All done. PR #99999999 merged at 07:56Z."

        def resolver(payload: dict[str, object]) -> dict[str, object]:
            return {
                "results": [],
                "mismatches": [
                    {
                        "claim": payload["claims"][0],  # type: ignore[index]
                        "status": "failed",
                        "reason": "PR omniclaude#99999999 not found on GitHub",
                    }
                ],
            }

        rc = run(body, repo_hint="omniclaude", resolver=resolver)
        assert rc == 2
        out = capsys.readouterr().out
        payload = json.loads(out)
        assert len(payload["mismatches"]) == 1
        mismatch = payload["mismatches"][0]
        assert mismatch["claim"]["ref"] == "omniclaude#99999999"
        assert "not found" in mismatch["reason"].lower()

    def test_multi_claim_mismatches_return_structured_diff(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from plugins.onex.hooks.lib.agent_result_verifier_runner import run

        body = (
            "PR #123 merged. CI passing for PR #123. "
            "Committed file plugins/onex/hooks/lib/agent_claim_extractor.py. "
            "Blocker on OMN-9107 without evidence."
        )

        def resolver(payload: dict[str, object]) -> dict[str, object]:
            claims = payload["claims"]
            assert isinstance(claims, list)
            return {
                "results": [],
                "mismatches": [
                    {
                        "claim": claims[0],
                        "status": "failed",
                        "reason": "PR omniclaude#123 state mismatch",
                        "expected": "MERGED",
                        "actual": "OPEN",
                    },
                    {
                        "claim": claims[-1],
                        "status": "failed",
                        "reason": "blocker claim lacks quoted gh pr view --json evidence",
                        "expected": "quoted gh pr view --json evidence",
                        "actual": "absent",
                    },
                ],
            }

        rc = run(body, repo_hint="omniclaude", resolver=resolver)
        assert rc == 2
        payload = json.loads(capsys.readouterr().out)
        assert payload["claim_count"] == 4
        assert len(payload["mismatches"]) == 2
        assert payload["mismatches"][0]["actual"] == "OPEN"
        assert "gh pr view --json" in payload["mismatches"][1]["reason"]


class TestRunnerPasses:
    """Runner returns 0 on verified claims, no claims, or resolver unreachable."""

    def test_verified_merged_pr_returns_0(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from plugins.onex.hooks.lib.agent_result_verifier_runner import run

        rc = run(
            "PR #1 merged.",
            repo_hint="omniclaude",
            resolver=lambda payload: {"results": [], "mismatches": []},
        )
        assert rc == 0
        assert capsys.readouterr().out == ""

    def test_no_claims_returns_0(self, capsys: pytest.CaptureFixture[str]) -> None:
        from plugins.onex.hooks.lib.agent_result_verifier_runner import run

        rc = run("Just prose, nothing to verify.", repo_hint="omniclaude")
        assert rc == 0
        assert capsys.readouterr().out == ""

    def test_resolver_unavailable_fails_open(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from plugins.onex.hooks.lib.agent_result_verifier_runner import run

        with mock.patch(
            "plugins.onex.hooks.lib.agent_result_verifier_runner.subprocess.run",
            side_effect=FileNotFoundError("resolver not found"),
        ):
            rc = run("PR #1 merged.", repo_hint="omniclaude")
        assert rc == 0  # fail-open

    def test_thread_resolved_is_sent_to_resolver(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from plugins.onex.hooks.lib.agent_result_verifier_runner import run

        body = "Resolved CR thread PRRT_kwDOP_NzS857mezy with reply + resolve."

        observed: dict[str, object] = {}

        def resolver(payload: dict[str, object]) -> dict[str, object]:
            observed.update(payload)
            return {"results": [], "mismatches": []}

        rc = run(body, repo_hint="omniclaude", resolver=resolver)
        assert rc == 0
        claims = observed["claims"]
        assert isinstance(claims, list)
        assert claims[0]["kind"] == "thread_resolved"


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
