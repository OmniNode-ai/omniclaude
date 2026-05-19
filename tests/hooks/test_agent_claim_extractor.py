# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for agent_claim_extractor.

Extracts structured claims from Agent turn output so a PostToolUse hook can
later verify them against ground truth through node_claim_resolver.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

from plugins.onex.hooks.lib.agent_claim_extractor import (  # noqa: E402
    ModelAgentClaim,
    extract_claims,
)


class TestPrMergedClaims:
    """Extract `PR #N merged` claims."""

    def test_extract_pr_merged_with_repo_hint(self) -> None:
        body = "Everything done. PR #1336 merged at 07:56Z. Moving on."
        claims = extract_claims(body, repo_hint="omniclaude")
        assert any(c.kind == "pr_merged" and c.ref == "omniclaude#1336" for c in claims)

    def test_extract_pr_merged_without_repo_hint(self) -> None:
        body = "PR #42 merged. Nice."
        claims = extract_claims(body, repo_hint=None)
        assert any(c.kind == "pr_merged" and c.ref == "#42" for c in claims)


class TestPrOpenedClaims:
    """Extract PR creation claims."""

    def test_extract_pr_opened(self) -> None:
        body = "Opened PR #56 for OMN-9107."
        claims = extract_claims(body, repo_hint="omniclaude")
        assert any(c.kind == "pr_opened" and c.ref == "omniclaude#56" for c in claims)


class TestCiPassingClaims:
    """Extract CI/checks passing claims."""

    def test_extract_ci_passing(self) -> None:
        body = "CI passing for PR #56."
        claims = extract_claims(body, repo_hint="omniclaude")
        assert any(
            c.kind == "ci_passing"
            and c.ref == "omniclaude#56"
            and c.expected == "passing"
            for c in claims
        )


class TestCommitShaClaims:
    """Extract commit SHA claims."""

    def test_extract_commit_sha(self) -> None:
        body = "Committed commit abc1234 for the resolver tests."
        claims = extract_claims(body, repo_hint=None)
        assert any(c.kind == "commit_sha" and c.ref == "abc1234" for c in claims)


class TestFileCommittedClaims:
    """Extract committed file claims."""

    def test_extract_file_committed(self) -> None:
        body = "Committed file plugins/onex/hooks/lib/agent_claim_extractor.py."
        claims = extract_claims(body, repo_hint=None)
        assert any(
            c.kind == "file_committed"
            and c.ref == "plugins/onex/hooks/lib/agent_claim_extractor.py"
            for c in claims
        )


class TestBlockerClaims:
    """Extract blocker claims and their quoted evidence."""

    def test_extract_blocker_on_x_with_quoted_gh_evidence(self) -> None:
        body = (
            "Blocker on OMN-9107: "
            "`gh pr view 56 --repo OmniNode-ai/omniclaude --json state,number`."
        )
        claims = extract_claims(body, repo_hint=None)
        blocker = next(c for c in claims if c.kind == "blocker_on_X")
        assert blocker.ref == "OMN-9107"
        assert blocker.evidence == (
            "gh pr view 56 --repo OmniNode-ai/omniclaude --json state,number",
        )


class TestThreadResolvedClaims:
    """Extract `thread <graphql-id> resolved` claims."""

    def test_extract_thread_resolved_with_reply(self) -> None:
        body = (
            "Resolved CR thread PRRT_kwDOP_NzS857mezy with reply + resolve. "
            '{"isResolved": true}'
        )
        claims = extract_claims(body, repo_hint="omniclaude")
        assert any(
            c.kind == "thread_resolved"
            and c.ref == "PRRT_kwDOP_NzS857mezy"
            and c.evidence == ('{"isResolved": true}',)
            for c in claims
        )


class TestLinearStateClaims:
    """Extract `OMN-N moved to <State>` claims."""

    def test_extract_linear_state(self) -> None:
        body = 'OMN-9032 moved to Done. {"state": "Done"}'
        claims = extract_claims(body, repo_hint=None)
        assert any(
            c.kind == "linear_state"
            and c.ref == "OMN-9032"
            and c.expected == "Done"
            and c.evidence == ('{"state": "Done"}',)
            for c in claims
        )


class TestNegativePaths:
    """No claims produced from plain prose or unrelated text."""

    def test_no_claims_in_plain_prose(self) -> None:
        body = "I reviewed the code and thought about the approach."
        claims = extract_claims(body, repo_hint="omniclaude")
        assert claims == []

    def test_no_claims_in_empty_body(self) -> None:
        assert extract_claims("", repo_hint="omniclaude") == []


class TestModelContract:
    """ModelAgentClaim is frozen with extra=forbid."""

    def test_model_is_frozen(self) -> None:
        claim = ModelAgentClaim(kind="pr_merged", ref="omniclaude#1")
        with pytest.raises((TypeError, ValueError)):
            claim.ref = "mutated"  # type: ignore[misc]

    def test_model_rejects_extra_fields(self) -> None:
        with pytest.raises(ValueError):
            ModelAgentClaim(
                kind="pr_merged",
                ref="omniclaude#1",
                rogue_field="x",  # type: ignore[call-arg]
            )
