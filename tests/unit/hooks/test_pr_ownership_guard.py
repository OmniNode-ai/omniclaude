# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for the OMN-16485 pre-mutation lane-ownership guard.

Covers the parser, lane-identity resolution, and the fail-closed verdict table
for both mutation classes, plus real end-to-end evaluation against an on-disk
claims directory.

Falsifier discipline: every ALLOW assertion is paired with a REFUSE assertion on
the same target, so deleting the ownership check turns tests RED rather than
leaving a vacuous green.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from plugins.onex.hooks.lib import pr_claim_registry
from plugins.onex.hooks.lib.pr_ownership_guard import (
    DISPATCH_KEY_PREFIX,
    RUN_KEY_PREFIX,
    Mutation,
    canonical_pr_key,
    decide,
    evaluate_command,
    parse_mutations,
    resolve_lane_id,
)

pytestmark = pytest.mark.unit

LANE_A = "lane-alpha"
LANE_B = "lane-beta"
PR_KEY = "omninode-ai/omniclaude#2019"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_claim(
    claims_dir: Path,
    target_key: str,
    *,
    lane_id: str | None,
    age_minutes: int = 0,
    raw: str | None = None,
) -> Path:
    claims_dir.mkdir(parents=True, exist_ok=True)
    path = claims_dir / f"{pr_claim_registry.filesystem_key(target_key)}.json"
    if raw is not None:
        path.write_text(raw)
        return path
    stamp = (datetime.now(UTC) - timedelta(minutes=age_minutes)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    path.write_text(
        json.dumps(
            {
                "pr_key": target_key,
                "claimed_by_run": "run-1",
                "claimed_by_host": "host-1",
                "claimed_by_instance_id": "inst-1",
                "claimed_at": stamp,
                "last_heartbeat_at": stamp,
                "action": "close",
                "lane_id": lane_id,
            }
        )
    )
    return path


def _ownership_mutation(target: str = PR_KEY) -> Mutation:
    return Mutation(
        verb="pr-close", mutation_class="ownership", target_key=target, detail=target
    )


def _exclusivity_mutation(target: str = f"{RUN_KEY_PREFIX}o/r#1") -> Mutation:
    return Mutation(
        verb="run-cancel",
        mutation_class="exclusivity",
        target_key=target,
        detail=target,
    )


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def test_parses_pr_close_with_repo_flag() -> None:
    mutations = parse_mutations("gh pr close 2019 --repo OmniNode-ai/omniclaude")
    assert len(mutations) == 1
    assert mutations[0].verb == "pr-close"
    assert mutations[0].mutation_class == "ownership"
    assert mutations[0].target_key == PR_KEY


def test_parses_pr_close_with_flag_before_number() -> None:
    """`--repo O/R 2019` must not read the repo as the positional PR number."""
    mutations = parse_mutations("gh pr close --repo OmniNode-ai/omniclaude 2019")
    assert mutations[0].target_key == PR_KEY


def test_parses_pr_close_from_url() -> None:
    mutations = parse_mutations(
        "gh pr close https://github.com/OmniNode-ai/omniclaude/pull/2019"
    )
    assert mutations[0].target_key == PR_KEY


def test_parses_pr_reopen() -> None:
    mutations = parse_mutations("gh pr reopen 2019 -R OmniNode-ai/omniclaude")
    assert mutations[0].verb == "pr-reopen"
    assert mutations[0].target_key == PR_KEY


def test_quoted_text_is_not_a_command() -> None:
    """A commit message mentioning the verb must not be parsed as a mutation."""
    assert parse_mutations('git commit -m "gh pr close 2019 was the incident"') == []


def test_read_only_verbs_are_untouched() -> None:
    for command in (
        "gh pr view 2019 --repo OmniNode-ai/omniclaude",
        "gh pr list --repo OmniNode-ai/omniclaude",
        "gh pr checks 2019 --watch",
        "gh run view 12345",
        "gh run list --limit 5",
        "gh pr merge 2019 --squash",
    ):
        assert parse_mutations(command) == [], command


def test_parses_multiple_segments() -> None:
    mutations = parse_mutations(
        "gh pr close 2019 --repo OmniNode-ai/omniclaude && "
        "gh run cancel 777 --repo OmniNode-ai/omniclaude"
    )
    assert [m.verb for m in mutations] == ["pr-close", "run-cancel"]


def test_parses_through_env_prefix() -> None:
    mutations = parse_mutations(
        "env FOO=1 gh pr close 2019 --repo OmniNode-ai/omniclaude"
    )
    assert mutations[0].target_key == PR_KEY


def test_parses_workflow_dispatch() -> None:
    mutations = parse_mutations(
        "gh workflow run build.yml --repo OmniNode-ai/omniclaude --ref dev"
    )
    assert mutations[0].verb == "workflow-dispatch"
    assert mutations[0].mutation_class == "exclusivity"
    assert mutations[0].target_key == (
        f"{DISPATCH_KEY_PREFIX}omninode-ai/omniclaude#build.yml@dev"
    )


def test_parses_api_state_closed() -> None:
    mutations = parse_mutations(
        "gh api -X PATCH repos/OmniNode-ai/omniclaude/pulls/2019 -f state=closed"
    )
    assert mutations[0].verb == "api-pr-close"
    assert mutations[0].target_key == PR_KEY


def test_api_patch_without_state_closed_is_ignored() -> None:
    """A label or body PATCH does not destroy a peer's work and is not guarded."""
    assert (
        parse_mutations(
            "gh api -X PATCH repos/OmniNode-ai/omniclaude/pulls/2019 -f body=hello"
        )
        == []
    )


def test_api_get_is_ignored() -> None:
    assert parse_mutations("gh api repos/OmniNode-ai/omniclaude/pulls/2019") == []


def test_unresolvable_repo_yields_unresolved_target() -> None:
    mutation = parse_mutations("gh pr close 2019")[0]
    assert mutation.target_key is None
    assert mutation.unresolved_reason is not None


def test_default_repo_fills_in_missing_flag() -> None:
    mutation = parse_mutations(
        "gh pr close 2019", default_repo="https://github.com/OmniNode-ai/omniclaude.git"
    )[0]
    assert mutation.target_key == PR_KEY


def test_canonical_pr_key_matches_registry_format() -> None:
    """The guard must key claims byte-identically to the registry that stores them."""
    assert canonical_pr_key("OmniNode-ai", "OmniClaude", 247) == (
        pr_claim_registry.canonical_pr_key("OmniNode-ai", "OmniClaude", 247)
    )


# ---------------------------------------------------------------------------
# Lane identity
# ---------------------------------------------------------------------------


def test_lane_id_prefers_explicit_env() -> None:
    assert resolve_lane_id(env={"ONEX_LANE_ID": LANE_A}, cwd="/tmp") == LANE_A


def test_lane_id_from_worktree_path() -> None:
    lane = resolve_lane_id(
        env={"OMNI_HOME": "/omni"},
        cwd="/omni/omni_worktrees/OMN-16485/omniclaude",
    )
    assert lane == "wt:OMN-16485/omniclaude"


def test_lane_id_distinguishes_two_worktrees() -> None:
    """Two lanes in different worktrees must not collapse to one identity."""
    first = resolve_lane_id(
        env={"OMNI_HOME": "/omni"}, cwd="/omni/omni_worktrees/OMN-1/omniclaude"
    )
    second = resolve_lane_id(
        env={"OMNI_HOME": "/omni"}, cwd="/omni/omni_worktrees/OMN-2/omniclaude"
    )
    assert first != second


def test_lane_id_unresolvable_returns_none() -> None:
    assert resolve_lane_id(env={}, cwd="/") is None


# ---------------------------------------------------------------------------
# Verdict table — ownership class (fail-closed)
# ---------------------------------------------------------------------------


def test_owner_may_close_its_own_pr() -> None:
    decision = decide(_ownership_mutation(), LANE_A, "active", LANE_A)
    assert decision.allowed is True
    assert decision.reason_code == "OWNED_BY_SELF"


def test_peer_lane_close_is_refused_and_names_the_owner() -> None:
    decision = decide(_ownership_mutation(), LANE_B, "active", LANE_A)
    assert decision.allowed is False
    assert decision.reason_code == "CROSS_LANE"
    assert LANE_A in decision.message


def test_unclaimed_close_fails_closed() -> None:
    """'Nobody claimed it' must never be read as 'therefore anyone may'."""
    decision = decide(_ownership_mutation(), LANE_A, "absent", None)
    assert decision.allowed is False
    assert decision.reason_code == "UNCLAIMED"
    assert "pr_claim_registry_cli.py claim" in decision.message


def test_expired_claim_still_requires_a_fresh_claim() -> None:
    decision = decide(_ownership_mutation(), LANE_A, "expired", LANE_A)
    assert decision.allowed is False
    assert decision.reason_code == "UNCLAIMED"


def test_unreadable_claim_fails_closed() -> None:
    decision = decide(_ownership_mutation(), LANE_A, "unreadable", None)
    assert decision.allowed is False
    assert decision.reason_code == "INDETERMINATE_CLAIM"


def test_laneless_claim_fails_closed() -> None:
    """A legacy claim with no lane proves someone holds it, not who."""
    decision = decide(_ownership_mutation(), LANE_A, "active", None)
    assert decision.allowed is False
    assert decision.reason_code == "INDETERMINATE_CLAIM"


def test_unresolvable_lane_fails_closed() -> None:
    decision = decide(_ownership_mutation(), None, "active", LANE_A)
    assert decision.allowed is False
    assert decision.reason_code == "INDETERMINATE_LANE"


def test_unresolvable_target_fails_closed() -> None:
    mutation = Mutation(
        verb="pr-close",
        mutation_class="ownership",
        target_key=None,
        detail="gh pr close",
        unresolved_reason="PR number could not be parsed from the command",
    )
    decision = decide(mutation, LANE_A, "absent", None)
    assert decision.allowed is False
    assert decision.reason_code == "INDETERMINATE_TARGET"


# ---------------------------------------------------------------------------
# Verdict table — exclusivity class (first-writer-wins)
# ---------------------------------------------------------------------------


def test_first_writer_is_allowed_and_records_a_claim() -> None:
    decision = decide(_exclusivity_mutation(), LANE_A, "absent", None)
    assert decision.allowed is True
    assert decision.reason_code == "FIRST_WRITER"
    assert decision.record_claim is True


def test_racing_peer_dispatch_is_refused() -> None:
    """The 2026-08-20T00:52Z duplicate concurrent workflow_dispatch case."""
    decision = decide(_exclusivity_mutation(), LANE_B, "active", LANE_A)
    assert decision.allowed is False
    assert decision.reason_code == "CROSS_LANE"


def test_same_lane_redispatch_is_allowed() -> None:
    decision = decide(_exclusivity_mutation(), LANE_A, "active", LANE_A)
    assert decision.allowed is True


def test_exclusivity_with_unresolvable_lane_fails_closed() -> None:
    decision = decide(_exclusivity_mutation(), None, "absent", None)
    assert decision.allowed is False
    assert decision.reason_code == "INDETERMINATE_LANE"


# ---------------------------------------------------------------------------
# End-to-end evaluation against a real claims directory
# ---------------------------------------------------------------------------


def test_evaluate_allows_owner_and_refuses_peer(tmp_path: Path) -> None:
    """One target, two lanes, opposite verdicts — the gate discriminates."""
    claims = tmp_path / "claims"
    _write_claim(claims, PR_KEY, lane_id=LANE_A)
    command = "gh pr close 2019 --repo OmniNode-ai/omniclaude"

    owner = evaluate_command(
        command, claims_dir=claims, env={"ONEX_LANE_ID": LANE_A}, cwd=tmp_path
    )
    peer = evaluate_command(
        command, claims_dir=claims, env={"ONEX_LANE_ID": LANE_B}, cwd=tmp_path
    )

    assert [d.allowed for d in owner] == [True]
    assert [d.allowed for d in peer] == [False]
    assert peer[0].reason_code == "CROSS_LANE"


def test_evaluate_ignores_unguarded_commands(tmp_path: Path) -> None:
    assert (
        evaluate_command(
            "gh pr view 2019 --repo OmniNode-ai/omniclaude",
            claims_dir=tmp_path,
            env={"ONEX_LANE_ID": LANE_A},
            cwd=tmp_path,
        )
        == []
    )


def test_evaluate_fails_closed_on_corrupt_claim_file(tmp_path: Path) -> None:
    """A malformed claim is INDETERMINATE, not absent — refuse, do not attempt."""
    claims = tmp_path / "claims"
    _write_claim(claims, PR_KEY, lane_id=None, raw="{ this is not json")

    decisions = evaluate_command(
        "gh pr close 2019 --repo OmniNode-ai/omniclaude",
        claims_dir=claims,
        env={"ONEX_LANE_ID": LANE_A},
        cwd=tmp_path,
    )
    assert decisions[0].allowed is False
    assert decisions[0].reason_code == "INDETERMINATE_CLAIM"


def test_evaluate_fails_closed_when_claims_dir_missing(tmp_path: Path) -> None:
    decisions = evaluate_command(
        "gh pr close 2019 --repo OmniNode-ai/omniclaude",
        claims_dir=tmp_path / "does-not-exist",
        env={"ONEX_LANE_ID": LANE_A},
        cwd=tmp_path,
    )
    assert decisions[0].allowed is False
    assert decisions[0].reason_code == "UNCLAIMED"


def test_expired_claim_does_not_strand_the_pr_forever(tmp_path: Path) -> None:
    """Both expiry conditions met -> the owning lane can re-claim and proceed."""
    claims = tmp_path / "claims"
    _write_claim(claims, PR_KEY, lane_id=LANE_A, age_minutes=200)

    stale = evaluate_command(
        "gh pr close 2019 --repo OmniNode-ai/omniclaude",
        claims_dir=claims,
        env={"ONEX_LANE_ID": LANE_B},
        cwd=tmp_path,
    )
    assert stale[0].reason_code == "UNCLAIMED"

    _write_claim(claims, PR_KEY, lane_id=LANE_B)
    fresh = evaluate_command(
        "gh pr close 2019 --repo OmniNode-ai/omniclaude",
        claims_dir=claims,
        env={"ONEX_LANE_ID": LANE_B},
        cwd=tmp_path,
    )
    assert fresh[0].allowed is True


def test_the_observed_incident_is_refused(tmp_path: Path) -> None:
    """Regression: omniclaude#2019, closed 2026-08-23 by a lane that did not own it."""
    claims = tmp_path / "claims"
    _write_claim(claims, PR_KEY, lane_id="lane-that-opened-2019")

    decisions = evaluate_command(
        "gh pr close 2019 --repo OmniNode-ai/omniclaude",
        claims_dir=claims,
        env={"ONEX_LANE_ID": "unrelated-sweep-lane"},
        cwd=tmp_path,
    )
    assert decisions[0].allowed is False
    assert "lane-that-opened-2019" in decisions[0].message


# ---------------------------------------------------------------------------
# Registry lane_id round-trip (the registry previously had no test coverage)
# ---------------------------------------------------------------------------


def test_registry_persists_lane_id(tmp_path: Path) -> None:
    registry = pr_claim_registry.ClaimRegistry(claims_dir=tmp_path)
    assert (
        registry.acquire(PR_KEY, run_id="run-1", action="close", lane_id=LANE_A) is True
    )

    claim = registry.get_claim(PR_KEY)
    assert claim is not None
    assert claim["lane_id"] == LANE_A


def test_registry_refuses_second_lane_while_claim_is_active(tmp_path: Path) -> None:
    registry = pr_claim_registry.ClaimRegistry(claims_dir=tmp_path)
    assert (
        registry.acquire(PR_KEY, run_id="run-1", action="close", lane_id=LANE_A) is True
    )
    assert (
        registry.acquire(PR_KEY, run_id="run-2", action="close", lane_id=LANE_B)
        is False
    )


def test_registry_release_is_scoped_to_the_holding_run(tmp_path: Path) -> None:
    registry = pr_claim_registry.ClaimRegistry(claims_dir=tmp_path)
    registry.acquire(PR_KEY, run_id="run-1", action="close", lane_id=LANE_A)

    registry.release(PR_KEY, run_id="run-2")
    assert registry.get_claim(PR_KEY) is not None, "a peer run must not release a claim"

    registry.release(PR_KEY, run_id="run-1")
    assert registry.get_claim(PR_KEY) is None
