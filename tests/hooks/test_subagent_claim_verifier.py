# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for SubagentStop agent-claim verifier [OMN-9086].

Covers all five mini-epic sub-phases of plan Task 2
(``docs/plans/2026-04-17-unused-hooks-applications.md``):

* 2a — schema fallback (local ``ModelWorkerReport`` parses representative reports)
* 2b — report extraction (present/absent/multi-fence/malformed)
* 2c — GitHub verification (MERGED match, fabricated PR, rate-limit fail-open)
* 2d — Linear verification (state match, state mismatch, unreachable fail-open)
* 2e — top-level ``verify_stop`` verdict aggregation

Plan acceptance criteria require exactly 6 unit tests covering: missing block,
valid PR merged, fabricated PR, malformed JSON, Linear match, Linear mismatch.
Those six are included below plus sub-phase-level coverage for 2a/2b/2c/2d
gating per mini-epic discipline.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import pytest

_LIB_DIR = (
    pathlib.Path(__file__).parent.parent.parent / "plugins" / "onex" / "hooks" / "lib"
)
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from subagent_claim_verifier import (  # noqa: E402
    EnumVerdict,
    EnumWorkerReportKind,
    ModelWorkerReport,
    extract_report,
    verify_linear_claim,
    verify_pr_claim,
    verify_schema_only,
    verify_stop,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# gh runner test doubles
# ---------------------------------------------------------------------------


def _gh_ok(state: str = "MERGED"):
    payload = json.dumps({"state": state, "mergedAt": "2026-04-17T12:00:00Z"})

    def _runner(_args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=_args, returncode=0, stdout=payload, stderr=""
        )

    return _runner


def _gh_not_found() -> object:
    def _runner(_args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=_args,
            returncode=1,
            stdout="",
            stderr="GraphQL: Could not resolve to a PullRequest with the number of 99999999",
        )

    return _runner


def _gh_rate_limit() -> object:
    def _runner(_args: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=_args,
            returncode=1,
            stdout="",
            stderr="API rate limit exceeded",
        )

    return _runner


# ---------------------------------------------------------------------------
# Required acceptance-criteria tests (6 from the plan)
# ---------------------------------------------------------------------------


def test_missing_report_block_blocks() -> None:
    """Plan test 1: missing json-report fence → decision=block."""
    body = "Done. Moved OMN-1 to Linear."
    verdict = verify_stop(body)
    assert verdict.decision == EnumVerdict.BLOCK
    assert verdict.reason == "missing_json_report_block"


def test_valid_report_with_verified_pr_allows() -> None:
    """Plan test 2: verified MERGED PR → decision=allow."""
    body = (
        "All done.\n\n```json-report\n"
        + json.dumps(
            {
                "kind": "pr_ship",
                "ticket": "OMN-1",
                "pr": {"number": 42, "state": "MERGED"},
            }
        )
        + "\n```\n"
    )
    verdict = verify_stop(body, gh_runner=_gh_ok("MERGED"))
    assert verdict.decision == EnumVerdict.ALLOW
    assert verdict.reason == "verified"


def test_fabricated_pr_blocks() -> None:
    """Plan test 3: PR number not found on GitHub → decision=block."""
    body = (
        "```json-report\n"
        + json.dumps(
            {
                "kind": "pr_ship",
                "ticket": "OMN-1",
                "pr": {"number": 99999999, "state": "MERGED"},
            }
        )
        + "\n```"
    )
    verdict = verify_stop(body, gh_runner=_gh_not_found())
    assert verdict.decision == EnumVerdict.BLOCK
    assert "pr_not_found" in verdict.reason


def test_malformed_json_blocks() -> None:
    """Plan test 4: json-report fence with invalid JSON → decision=block."""
    body = "```json-report\n{ kind: not-json, ticket: OMN-1 \n```"
    verdict = verify_stop(body)
    assert verdict.decision == EnumVerdict.BLOCK
    assert verdict.reason.startswith("malformed_report:")


def test_linear_state_match_allows() -> None:
    """Plan test 5: Linear claim matches API → decision=allow."""
    body = (
        "```json-report\n"
        + json.dumps(
            {
                "kind": "ticket_update",
                "ticket": "OMN-1",
                "linear": {"ticket_state": "Done"},
            }
        )
        + "\n```"
    )

    def linear_runner(_ticket: str) -> dict[str, str]:
        return {"state": "Done"}

    verdict = verify_stop(body, linear_runner=linear_runner)
    assert verdict.decision == EnumVerdict.ALLOW


def test_linear_state_mismatch_blocks() -> None:
    """Plan test 6: Linear claim conflicts with API → decision=block + diff."""
    body = (
        "```json-report\n"
        + json.dumps(
            {
                "kind": "ticket_update",
                "ticket": "OMN-1",
                "linear": {"ticket_state": "Done"},
            }
        )
        + "\n```"
    )

    def linear_runner(_ticket: str) -> dict[str, str]:
        return {"state": "In Progress"}

    verdict = verify_stop(body, linear_runner=linear_runner)
    assert verdict.decision == EnumVerdict.BLOCK
    assert "state_mismatch" in verdict.reason
    assert verdict.diff["linear"]["claimed"] == "Done"
    assert verdict.diff["linear"]["actual"] == "In Progress"


# ---------------------------------------------------------------------------
# Sub-phase 2a — schema fallback
# ---------------------------------------------------------------------------


def test_2a_schema_parses_representative_reports() -> None:
    """2a gate: local ModelWorkerReport parses both pr_ship + ticket_update shapes."""
    report = ModelWorkerReport.model_validate(
        {
            "kind": "pr_ship",
            "ticket": "OMN-1",
            "pr": {"number": 42, "state": "MERGED", "repo": "OmniNode-ai/omniclaude"},
        }
    )
    assert report.kind is EnumWorkerReportKind.PR_SHIP
    assert report.pr is not None and report.pr.number == 42

    report2 = ModelWorkerReport.model_validate(
        {"kind": "ticket_update", "ticket": "OMN-2", "linear": {"ticket_state": "Done"}}
    )
    assert report2.kind is EnumWorkerReportKind.TICKET_UPDATE
    assert report2.linear == {"ticket_state": "Done"}

    # extra keys tolerated per OMN-9063 schema-evolution expectation
    tolerant = ModelWorkerReport.model_validate(
        {"kind": "research", "ticket": "OMN-3", "findings_ref": "docs/research/x.md"}
    )
    assert tolerant.kind is EnumWorkerReportKind.RESEARCH


# ---------------------------------------------------------------------------
# Sub-phase 2b — report extraction (all four shapes)
# ---------------------------------------------------------------------------


def test_2b_extraction_handles_all_shapes() -> None:
    # Shape 1: absent
    absent = extract_report("no fences here")
    assert absent.found is False
    assert absent.parsed is None
    assert absent.error is None

    # Shape 2: present, valid
    present = extract_report(
        '```json-report\n{"kind":"diagnosis","ticket":"OMN-9"}\n```'
    )
    assert present.found is True
    assert present.parsed is not None
    assert present.parsed.ticket == "OMN-9"

    # Shape 3: multiple fences — last wins (agent retry scenario)
    multi = extract_report(
        '```json-report\n{"kind":"diagnosis","ticket":"OMN-A"}\n```\n'
        "later...\n"
        '```json-report\n{"kind":"diagnosis","ticket":"OMN-B"}\n```\n'
    )
    assert multi.found is True
    assert multi.parsed is not None
    assert multi.parsed.ticket == "OMN-B"

    # Shape 4: malformed JSON
    malformed = extract_report("```json-report\n{ not json \n```")
    assert malformed.found is True
    assert malformed.parsed is None
    assert malformed.error is not None and malformed.error.startswith("json_decode:")


def test_verify_schema_only_matches_extract_report() -> None:
    """Task 7 shares 2a+2b via verify_schema_only() — must be identical."""
    msg = '```json-report\n{"kind":"pr_ship","ticket":"OMN-1","pr":{"number":1,"state":"OPEN"}}\n```'
    assert verify_schema_only(msg) == extract_report(msg)


def test_2b_extraction_accepts_crlf_line_endings() -> None:
    """CR feedback: Windows/CRLF-serialized fences must parse identically to LF.

    A real agent report pasted through a CRLF transport (e.g. Windows clipboard,
    email relay) would previously be treated as ``found=False``; verifier must
    accept both line-ending conventions.
    """

    crlf = '```json-report\r\n{"kind":"diagnosis","ticket":"OMN-C"}\r\n```'
    result = extract_report(crlf)
    assert result.found is True
    assert result.parsed is not None
    assert result.parsed.ticket == "OMN-C"


def test_verify_stop_propagates_fail_open_reason() -> None:
    """CR feedback: ALLOW verdict must surface fail-open reasons, not hide them.

    A rate-limited gh probe or auth-failed Linear probe produces an allow
    decision (fail-open) but the degraded state must reach
    ``hookSpecificOutput.additionalContext`` via ``reason``.
    """

    body = (
        "```json-report\n"
        + json.dumps(
            {
                "kind": "pr_ship",
                "ticket": "OMN-1",
                "pr": {"number": 1, "state": "MERGED"},
            }
        )
        + "\n```"
    )
    verdict = verify_stop(body, gh_runner=_gh_rate_limit())
    assert verdict.decision == EnumVerdict.ALLOW
    assert verdict.reason.startswith("verified_fail_open:")
    assert "github:rate_limited" in verdict.reason


# ---------------------------------------------------------------------------
# Sub-phase 2c — GitHub verification edges
# ---------------------------------------------------------------------------


def test_2c_rate_limit_fails_open() -> None:
    """2c gate: rate-limit from gh → ok=True (fail-open) with reason."""
    report = ModelWorkerReport.model_validate(
        {"kind": "pr_ship", "ticket": "OMN-1", "pr": {"number": 1, "state": "MERGED"}}
    )
    result = verify_pr_claim(report, gh_runner=_gh_rate_limit())
    assert result.ok is True
    assert result.reason == "rate_limited"


def test_2c_non_pr_ship_skips_github() -> None:
    """Reports that aren't pr_ship must not invoke gh."""
    report = ModelWorkerReport.model_validate({"kind": "research", "ticket": "OMN-9"})

    def exploder(_args: list[str]) -> subprocess.CompletedProcess[str]:
        raise AssertionError("gh must not be called for non-pr_ship reports")

    result = verify_pr_claim(report, gh_runner=exploder)
    assert result.ok is True
    assert result.reason == "not_pr_ship"


# ---------------------------------------------------------------------------
# Sub-phase 2d — Linear verification edges
# ---------------------------------------------------------------------------


def test_2d_linear_auth_failure_fails_open() -> None:
    """2d gate: auth/unreachable → ok=True per Task 8 fail-open semantics."""
    report = ModelWorkerReport.model_validate(
        {
            "kind": "ticket_update",
            "ticket": "OMN-1",
            "linear": {"ticket_state": "Done"},
        }
    )

    def linear_runner(_ticket: str) -> dict[str, str]:
        raise PermissionError("no valid session token")

    result = verify_linear_claim(report, linear_runner=linear_runner)
    assert result.ok is True
    assert "linear_auth_failed" in result.reason


def test_2d_no_linear_claim_skips_check() -> None:
    """A report without a linear claim block must not fail open-or-closed."""
    report = ModelWorkerReport.model_validate({"kind": "diagnosis", "ticket": "OMN-7"})

    def exploder(_t: str) -> dict[str, str]:
        raise AssertionError("linear must not be called without a claim")

    result = verify_linear_claim(report, linear_runner=exploder)
    assert result.ok is True
    assert result.reason == "no_linear_claim"
