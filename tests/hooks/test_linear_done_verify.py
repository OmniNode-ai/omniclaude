# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for the OMN-8415 Linear Done-state PR verification hook.

Covers the five required cases:
    a. All referenced PRs merged → allow
    b. One referenced PR BLOCKED → reject
    c. No PR references in DoD → allow
    d. `close-if-done` exempt → allow
    e. gh CLI timeout / failure → reject (fail-safe)
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

_LIB = (
    Path(__file__).resolve().parents[2]
    / "plugins"
    / "onex"
    / "hooks"
    / "lib"
    / "linear_done_verify.py"
)

_spec = importlib.util.spec_from_file_location("linear_done_verify", _LIB)
assert _spec and _spec.loader
linear_done_verify = importlib.util.module_from_spec(_spec)
sys.modules["linear_done_verify"] = linear_done_verify
_spec.loader.exec_module(linear_done_verify)

PRRef = linear_done_verify.PRRef
PRStatus = linear_done_verify.PRStatus
parse_pr_refs = linear_done_verify.parse_pr_refs
verify = linear_done_verify.verify


def _merged(ref: PRRef) -> PRStatus:
    return PRStatus(ref=ref, state="MERGED", merge_state="CLEAN")


def _blocked(ref: PRRef) -> PRStatus:
    return PRStatus(ref=ref, state="OPEN", merge_state="BLOCKED")


def _timeout(ref: PRRef) -> PRStatus:
    return PRStatus(
        ref=ref,
        state="UNKNOWN",
        merge_state="UNKNOWN",
        error=f"Timeout querying {ref.repo}#{ref.number}",
    )


class TestParsing:
    def test_extracts_bare_pr_number_with_default_repo(self) -> None:
        refs = parse_pr_refs(
            "fixed by #202 and also #15",
            default_repo="OmniNode-ai/omniclaude",
        )
        nums = sorted(r.number for r in refs)
        assert nums == [15, 202]
        assert all(r.repo == "OmniNode-ai/omniclaude" for r in refs)

    def test_extracts_full_github_url(self) -> None:
        refs = parse_pr_refs(
            "See https://github.com/OmniNode-ai/omnibase_core/pull/1227"
        )
        assert len(refs) == 1
        assert refs[0].repo == "OmniNode-ai/omnibase_core"
        assert refs[0].number == 1227

    def test_deduplicates_url_and_shorthand_same_number(self) -> None:
        refs = parse_pr_refs(
            "See https://github.com/OmniNode-ai/omniclaude/pull/202 — #202",
            default_repo="OmniNode-ai/omniclaude",
        )
        assert len(refs) == 1
        assert refs[0].number == 202


class TestVerify:
    def test_allows_when_all_prs_merged(self) -> None:
        result = verify(
            description="Done. Fixed in #202.",
            labels=[],
            default_repo="OmniNode-ai/omniclaude",
            fetcher=_merged,
        )
        assert result.allowed is True
        assert result.reason == "all_prs_merged"

    def test_rejects_when_pr_blocked(self) -> None:
        result = verify(
            description="Done. PR: #202",
            labels=[],
            default_repo="OmniNode-ai/omniclaude",
            fetcher=_blocked,
        )
        assert result.allowed is False
        assert "OmniNode-ai/omniclaude#202" in result.reason
        assert "BLOCKED" in result.reason

    def test_allows_when_no_pr_references(self) -> None:
        result = verify(
            description="All done — no tracked PR for this cleanup.",
            labels=[],
            default_repo=None,
            fetcher=_blocked,  # should never be called
        )
        assert result.allowed is True
        assert result.reason == "no_pr_references"

    def test_allows_when_exempt_via_label(self) -> None:
        result = verify(
            description="Done. #202 is still open in GitHub but merged on disk.",
            labels=["close-if-done"],
            default_repo="OmniNode-ai/omniclaude",
            fetcher=_blocked,
        )
        assert result.allowed is True
        assert result.reason == "exempt"

    def test_allows_when_exempt_via_frontmatter(self) -> None:
        result = verify(
            description="close-if-done: true\n\nDone. #202",
            labels=[],
            default_repo="OmniNode-ai/omniclaude",
            fetcher=_blocked,
        )
        assert result.allowed is True
        assert result.reason == "exempt"

    def test_rejects_on_gh_timeout(self) -> None:
        result = verify(
            description="Done. #202",
            labels=[],
            default_repo="OmniNode-ai/omniclaude",
            fetcher=_timeout,
        )
        assert result.allowed is False
        assert "Timeout" in result.reason

    def test_mixed_merged_and_blocked_is_rejected(self) -> None:
        def fetcher(ref: PRRef) -> PRStatus:
            return _merged(ref) if ref.number == 100 else _blocked(ref)

        result = verify(
            description="Done. #100 and #202 both needed.",
            labels=[],
            default_repo="OmniNode-ai/omniclaude",
            fetcher=fetcher,
        )
        assert result.allowed is False
        assert "#202" in result.reason
        assert "#100" not in result.reason  # merged one not listed as blocker


HOOK_SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "plugins"
    / "onex"
    / "hooks"
    / "scripts"
    / "pre_tool_use_linear_done_verify.sh"
)


def _run_hook(tool_input: dict[str, Any]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(HOOK_SCRIPT)],
        input=json.dumps(tool_input),
        capture_output=True,
        text=True,
        env={
            "PATH": "/usr/bin:/bin:/usr/local/bin",
            "CLAUDE_PLUGIN_ROOT": str(HOOK_SCRIPT.parents[2]),
            "OMNICLAUDE_MODE": "full",
            "PYTHON_CMD": sys.executable,
        },
        timeout=30,
        check=False,
    )


class TestShellWrapper:
    def test_allows_non_linear_tool(self) -> None:
        result = _run_hook({"tool_name": "Bash", "tool_input": {"command": "ls"}})
        assert result.returncode == 0

    def test_allows_non_done_state(self) -> None:
        result = _run_hook(
            {
                "tool_name": "mcp__linear-server__save_issue",
                "tool_input": {"id": "OMN-1", "state": "In Progress"},
            }
        )
        assert result.returncode == 0

    def test_allows_done_with_no_pr_references(self) -> None:
        result = _run_hook(
            {
                "tool_name": "mcp__linear-server__save_issue",
                "tool_input": {
                    "id": "OMN-1",
                    "state": "Done",
                    "description": "No PRs referenced here.",
                },
            }
        )
        assert result.returncode == 0

    def test_allows_done_with_exempt_label(self) -> None:
        result = _run_hook(
            {
                "tool_name": "mcp__linear-server__save_issue",
                "tool_input": {
                    "id": "OMN-1",
                    "state": "Done",
                    "description": "Fixed in #202",
                    "labels": ["close-if-done"],
                },
            }
        )
        assert result.returncode == 0


class TestClassification:
    def test_open_pr_classified_blocking(self) -> None:
        status = PRStatus(
            ref=PRRef(number=1, repo="a/b"), state="OPEN", merge_state="CLEAN"
        )
        assert linear_done_verify.classify_blocking(status) is True

    def test_closed_unmerged_classified_blocking(self) -> None:
        status = PRStatus(
            ref=PRRef(number=1, repo="a/b"), state="CLOSED", merge_state="UNKNOWN"
        )
        assert linear_done_verify.classify_blocking(status) is True

    def test_merged_classified_non_blocking(self) -> None:
        status = PRStatus(
            ref=PRRef(number=1, repo="a/b"), state="MERGED", merge_state="CLEAN"
        )
        assert linear_done_verify.classify_blocking(status) is False


@pytest.mark.parametrize(
    "merge_state",
    ["BLOCKED", "DIRTY", "BEHIND"],
)
def test_open_with_blocking_merge_state_rejected(merge_state: str) -> None:
    status = PRStatus(
        ref=PRRef(number=202, repo="OmniNode-ai/omniclaude"),
        state="OPEN",
        merge_state=merge_state,
    )
    assert linear_done_verify.classify_blocking(status) is True
