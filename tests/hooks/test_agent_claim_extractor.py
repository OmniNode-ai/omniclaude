# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for agent_claim_extractor (OMN-9055 Task 4 scaffold).

Extracts structured claims from Agent turn output so a PostToolUse hook can
later verify them against ground truth. Scaffold scope — 3 claim kinds:
pr_merged, thread_resolved, linear_state.
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


class TestThreadResolvedClaims:
    """Extract `thread <graphql-id> resolved` claims."""

    def test_extract_thread_resolved_with_reply(self) -> None:
        body = "Resolved CR thread PRRT_kwDOP_NzS857mezy with reply + resolve."
        claims = extract_claims(body, repo_hint="omniclaude")
        assert any(
            c.kind == "thread_resolved" and c.ref == "PRRT_kwDOP_NzS857mezy"
            for c in claims
        )


class TestLinearStateClaims:
    """Extract `OMN-N moved to <State>` claims."""

    def test_extract_linear_state(self) -> None:
        body = "OMN-9032 moved to Done."
        claims = extract_claims(body, repo_hint=None)
        assert any(
            c.kind == "linear_state" and c.ref == "OMN-9032" and c.expected == "Done"
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
