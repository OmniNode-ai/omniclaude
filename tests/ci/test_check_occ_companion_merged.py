# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Verdict tests for the occ-companion-merged STRICT gate (OMN-15214).

The gate makes the 2026-07-26 hygiene-sweep trigger state — an OPEN
onex_change_control companion whose product PR has already MERGED —
unreachable via the merge path: the product PR's required ``CI Summary``
context cannot go green until the cited companion is MERGED (or the cited
SHA is already an ancestor of an OCC durable branch).

These tests pin the fail-closed verdict table:

* companion MERGED            → PASS
* companion OPEN              → PENDING (poll; deadline converts to FAIL)
* companion CLOSED unmerged   → FAIL immediately (the incident state)
* SHA ancestor of dev/main    → PASS
* SHA not an ancestor         → FAIL (OMN-15216 strandable pre-merge pin)
* missing Evidence-Source     → PENDING (autobind mint may be in flight)
* missing Evidence-Source AND the producer reported ERROR on this head
                              → FAIL immediately, naming the reason (OMN-18069)
* malformed Evidence-Source   → FAIL
* dependency-bot author       → PASS (mirrors occ-preflight OMN-13762)
* non-PR event                → PASS (gate not applicable)
* unresolvable PR number      → FAIL (fail closed)
* API errors                  → PENDING (retryable), never PASS
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.ci.check_occ_companion_merged import (  # noqa: E402
    AUTOBIND_OUTCOME_CHECK_NAME,
    AUTOBIND_OUTCOME_MARKER_PREFIX,
    EXIT_FAIL,
    EXIT_PASS,
    EXIT_PENDING,
    evaluate_once,
    main,
    parse_evidence_source,
    read_autobind_outcome,
    resolve_pr_number,
)

pytestmark = pytest.mark.unit

PRODUCT_REPO = "OmniNode-ai/omniclaude"
OCC_REPO = "OmniNode-ai/onex_change_control"


class FakeFetcher:
    """Deterministic stand-in for GhFetcher."""

    def __init__(
        self,
        *,
        prs: dict[tuple[str, str], dict[str, object] | None] | None = None,
        compare: dict[tuple[str, str], str | None] | None = None,
        check_runs: dict[tuple[str, str], list[dict[str, object]] | None] | None = None,
    ) -> None:
        self._prs = prs or {}
        self._compare = compare or {}
        # OMN-18069. Default `[]` = "the producer posted no outcome", the
        # ordinary case; `None` = "the read itself failed", which must be a
        # distinct input because the gate may never treat one as the other.
        self._check_runs = check_runs or {}

    def pr_view(self, repo: str, number: str, fields: str) -> dict[str, object] | None:
        return self._prs.get((repo, str(number)))

    def compare_status(self, repo: str, base: str, head_sha: str) -> str | None:
        return self._compare.get((base, head_sha))

    def check_runs(self, repo: str, head_sha: str) -> list[dict[str, object]] | None:
        return self._check_runs.get((repo, head_sha), [])


def _product_pr(
    body: str,
    author: str = "jonahgabriel",
    head_sha: str = "615219ec46868e2ebf09f8b35a9e6cfc6d743dea",
) -> dict[str, object]:
    return {"body": body, "author": {"login": author}, "headRefOid": head_sha}


def _evaluate(fetcher: FakeFetcher, **kwargs: object):
    defaults: dict[str, object] = {
        "event_name": "pull_request",
        "repo": PRODUCT_REPO,
        "pr_number": "2500",
        "occ_repo": OCC_REPO,
    }
    defaults.update(kwargs)
    return evaluate_once(fetcher, **defaults)  # type: ignore[arg-type]


class TestEvidenceSourceParsing:
    def test_first_line_wins_and_is_case_insensitive(self) -> None:
        body = "intro\nevidence-source:  OCC#5032 \nEvidence-Source: OCC#9999\n"
        assert parse_evidence_source(body) == "OCC#5032"

    def test_absent_returns_none(self) -> None:
        assert parse_evidence_source("no evidence here") is None
        assert parse_evidence_source("") is None

    def test_indented_line_is_not_matched(self) -> None:
        # occ-preflight anchors at line start; mirror it.
        assert parse_evidence_source("  Evidence-Source: OCC#1") is None


class TestPrNumberResolution:
    def test_pull_request_number_passthrough(self) -> None:
        assert resolve_pr_number("pull_request", "123", "") == "123"

    def test_merge_group_head_ref_parse(self) -> None:
        ref = "refs/heads/gh-readonly-queue/dev/pr-456-0123abc"
        assert resolve_pr_number("merge_group", "", ref) == "456"

    def test_unresolvable_returns_empty(self) -> None:
        assert resolve_pr_number("merge_group", "", "refs/heads/whatever") == ""


class TestCompanionPrVerdicts:
    def _fetcher_with_companion(self, occ_state: dict[str, object]) -> FakeFetcher:
        return FakeFetcher(
            prs={
                (PRODUCT_REPO, "2500"): _product_pr("Evidence-Source: OCC#5032"),
                (OCC_REPO, "5032"): occ_state,
            }
        )

    def test_merged_companion_is_pass(self) -> None:
        fetcher = self._fetcher_with_companion(
            {"state": "MERGED", "mergeCommit": {"oid": "abc123"}}
        )
        verdict = _evaluate(fetcher)
        assert verdict.code == EXIT_PASS
        assert "abc123" in verdict.reason

    def test_open_companion_is_pending_not_fail(self) -> None:
        # OPEN may still auto-merge; the poll loop absorbs the latency and the
        # deadline converts PENDING to FAIL.
        fetcher = self._fetcher_with_companion({"state": "OPEN", "mergeCommit": None})
        verdict = _evaluate(fetcher)
        assert verdict.code == EXIT_PENDING
        assert "OPEN" in verdict.reason

    def test_closed_unmerged_companion_is_immediate_fail(self) -> None:
        # The 2026-07-26 incident state: hygiene sweep closed the companion
        # without merging. Evidence destroyed — terminal, never poll.
        fetcher = self._fetcher_with_companion({"state": "CLOSED", "mergeCommit": None})
        verdict = _evaluate(fetcher)
        assert verdict.code == EXIT_FAIL
        assert "CLOSED" in verdict.reason

    def test_companion_fetch_error_is_pending_never_pass(self) -> None:
        fetcher = FakeFetcher(
            prs={
                (PRODUCT_REPO, "2500"): _product_pr("Evidence-Source: OCC#5032"),
                (OCC_REPO, "5032"): None,
            }
        )
        assert _evaluate(fetcher).code == EXIT_PENDING


class TestShaVerdicts:
    SHA = "a" * 40

    def test_sha_ancestor_of_dev_is_pass(self) -> None:
        fetcher = FakeFetcher(
            prs={(PRODUCT_REPO, "2500"): _product_pr(f"Evidence-Source: {self.SHA}")},
            compare={("dev", self.SHA): "behind"},
        )
        assert _evaluate(fetcher).code == EXIT_PASS

    def test_sha_identical_to_main_is_pass(self) -> None:
        fetcher = FakeFetcher(
            prs={(PRODUCT_REPO, "2500"): _product_pr(f"Evidence-Source: {self.SHA}")},
            compare={("dev", self.SHA): "diverged", ("main", self.SHA): "identical"},
        )
        assert _evaluate(fetcher).code == EXIT_PASS

    def test_floating_sha_is_fail(self) -> None:
        # A feature-branch head SHA on squash-only OCC can never become an
        # ancestor of dev/main — terminal (OMN-15216).
        fetcher = FakeFetcher(
            prs={(PRODUCT_REPO, "2500"): _product_pr(f"Evidence-Source: {self.SHA}")},
            compare={("dev", self.SHA): "diverged", ("main", self.SHA): "ahead"},
        )
        verdict = _evaluate(fetcher)
        assert verdict.code == EXIT_FAIL
        assert "ancestor" in verdict.reason

    def test_compare_api_error_is_pending_never_fail(self) -> None:
        fetcher = FakeFetcher(
            prs={(PRODUCT_REPO, "2500"): _product_pr(f"Evidence-Source: {self.SHA}")},
            compare={("dev", self.SHA): None, ("main", self.SHA): None},
        )
        assert _evaluate(fetcher).code == EXIT_PENDING


class TestBodyAndScopeVerdicts:
    def test_missing_evidence_source_is_pending(self) -> None:
        fetcher = FakeFetcher(prs={(PRODUCT_REPO, "2500"): _product_pr("no line yet")})
        verdict = _evaluate(fetcher)
        assert verdict.code == EXIT_PENDING
        assert "Evidence-Source" in verdict.reason

    def test_malformed_evidence_source_is_fail(self) -> None:
        fetcher = FakeFetcher(
            prs={(PRODUCT_REPO, "2500"): _product_pr("Evidence-Source: not-a-ref!")}
        )
        assert _evaluate(fetcher).code == EXIT_FAIL

    def test_dependency_bot_author_is_exempt(self) -> None:
        fetcher = FakeFetcher(
            prs={(PRODUCT_REPO, "2500"): _product_pr("", author="dependabot[bot]")}
        )
        verdict = _evaluate(fetcher)
        assert verdict.code == EXIT_PASS
        assert "dependency-bot" in verdict.reason

    def test_non_pr_event_is_not_applicable_pass(self) -> None:
        verdict = _evaluate(FakeFetcher(), event_name="push")
        assert verdict.code == EXIT_PASS
        assert "not applicable" in verdict.reason

    def test_unresolvable_pr_number_fails_closed(self) -> None:
        verdict = _evaluate(FakeFetcher(), pr_number="")
        assert verdict.code == EXIT_FAIL

    def test_product_pr_fetch_error_is_pending(self) -> None:
        fetcher = FakeFetcher(prs={(PRODUCT_REPO, "2500"): None})
        assert _evaluate(fetcher).code == EXIT_PENDING

    def test_evidence_source_override_skips_body_fetch(self) -> None:
        fetcher = FakeFetcher(
            prs={(OCC_REPO, "5032"): {"state": "MERGED", "mergeCommit": {"oid": "x"}}}
        )
        verdict = _evaluate(fetcher, evidence_source_override="OCC#5032")
        assert verdict.code == EXIT_PASS


class TestMainEntrypoint:
    def test_once_mode_returns_pending_exit_code(self, monkeypatch) -> None:
        # --once with an OPEN companion must surface PENDING (2), not PASS.
        import scripts.ci.check_occ_companion_merged as mod

        fetcher = FakeFetcher(
            prs={
                (PRODUCT_REPO, "77"): _product_pr("Evidence-Source: OCC#5032"),
                (OCC_REPO, "5032"): {"state": "OPEN", "mergeCommit": None},
            }
        )
        monkeypatch.setattr(mod, "GhFetcher", lambda: fetcher)
        rc = main(
            [
                "--once",
                "--repo",
                PRODUCT_REPO,
                "--pr-number",
                "77",
                "--occ-repo",
                OCC_REPO,
            ]
        )
        assert rc == EXIT_PENDING

    def test_deadline_converts_pending_to_fail(self, monkeypatch) -> None:
        import scripts.ci.check_occ_companion_merged as mod

        fetcher = FakeFetcher(
            prs={
                (PRODUCT_REPO, "77"): _product_pr("Evidence-Source: OCC#5032"),
                (OCC_REPO, "5032"): {"state": "OPEN", "mergeCommit": None},
            }
        )
        monkeypatch.setattr(mod, "GhFetcher", lambda: fetcher)
        rc = main(
            [
                "--repo",
                PRODUCT_REPO,
                "--pr-number",
                "77",
                "--occ-repo",
                OCC_REPO,
                "--deadline-seconds",
                "0",
                "--poll-interval-seconds",
                "0",
            ]
        )
        assert rc == EXIT_FAIL


# --------------------------------------------------------------------------
# OMN-15615 AC6 — the second live site of the OMN-14682 defect.
#
# `EVIDENCE_SOURCE_RE` is `^...$` MULTILINE, so it anchors at column 0 — and a
# fenced example is written at column 0. A meta-PR that merely QUOTED the
# canonical stamp therefore had the quoted value resolved as a real
# declaration. The quoted example almost always names a companion that really
# did merge, for some OTHER product PR, so the failure direction on THIS gate
# is a false PASS: the durability gate passing on evidence that was never this
# PR's. OMN-14682 retired this on the Receipt Gate and was never propagated.
# --------------------------------------------------------------------------

_FENCED_QUOTE_BODY = """\
Closes OMN-15615.

The publisher's log line reads:

```
SKIP: OmniNode-ai/omniclaude#1969 body already carries the stamp
Evidence-Source: OCC#5032
```

This PR has no companion of its own yet.
"""


class TestQuotedStampIsNotEvidence:
    def test_fenced_stamp_does_not_parse_as_a_source(self) -> None:
        assert parse_evidence_source(_FENCED_QUOTE_BODY) is None

    def test_blockquoted_stamp_does_not_parse_as_a_source(self) -> None:
        assert parse_evidence_source("> Evidence-Source: OCC#5032\n") is None

    def test_unterminated_fence_blanks_to_end_of_body(self) -> None:
        """Fail-closed: a stamp after malformed markup is not trustworthy."""
        assert parse_evidence_source("```\nEvidence-Source: OCC#5032\n") is None

    def test_real_stamp_after_a_fenced_example_still_parses(self) -> None:
        body = _FENCED_QUOTE_BODY + "\nEvidence-Source: OCC#7777\n"
        assert parse_evidence_source(body) == "OCC#7777"

    def test_fenced_stamp_makes_the_gate_pending_not_a_false_pass(self) -> None:
        """The whole point: a quoted OCC#5032 that really did merge (for another
        PR) used to satisfy this gate. It must now read as 'no stamp yet' —
        PENDING, which the deadline converts to FAIL."""
        fetcher = FakeFetcher(
            prs={
                (PRODUCT_REPO, "2500"): _product_pr(_FENCED_QUOTE_BODY),
                (OCC_REPO, "5032"): {
                    "state": "MERGED",
                    "mergedAt": "2026-07-26T00:00:00Z",
                },
            }
        )
        verdict = _evaluate(fetcher)
        assert verdict.code == EXIT_PENDING, verdict.reason
        assert "Evidence-Source" in verdict.reason


class TestStripAgreesWithCanonicalHelper:
    """AC5/AC6 — pin the mirror against the canonical helper it copies.

    CI runs this file as bare ``python3 scripts/ci/check_occ_companion_merged.py``
    with no project venv on the path, so omnibase_core cannot be imported at
    runtime. The test env can import it, and does: that is what makes the copy
    a reuse of the canonical notion of "non-canonical region" rather than a
    fourth private one.
    """

    @pytest.mark.parametrize(
        "body",
        [
            "",
            "Closes OMN-15615",
            _FENCED_QUOTE_BODY,
            "> Evidence-Source: OCC#5032\n",
            "  > quoted with leading space\n",
            "```\nEvidence-Source: OCC#1\n```\nEvidence-Source: OCC#2\n",
            "~~~\nEvidence-Source: OCC#1\n~~~\n",
            "~~~\n```\nstill inside the tilde fence\n~~~\nout\n",
            "````\nfour backticks\n````\n",
            "```\nEvidence-Source: OCC#5032\n",
            "Evidence-Source: OCC#7\n",
            "text\r\nmore text\r\n",
        ],
    )
    def test_mirror_matches_core_helper(self, body: str) -> None:
        from omnibase_core.validation.validator_receipt_gate import (
            strip_noncanonical_regions as canonical,
        )

        from scripts.ci.check_occ_companion_merged import strip_noncanonical_regions

        assert strip_noncanonical_regions(body) == canonical(body), body

    def test_mirror_is_idempotent(self) -> None:
        from scripts.ci.check_occ_companion_merged import strip_noncanonical_regions

        once = strip_noncanonical_regions(_FENCED_QUOTE_BODY)
        assert strip_noncanonical_regions(once) == once

    def test_closing_fence_must_match_opening_delimiter_length(self) -> None:
        from scripts.ci.check_occ_companion_merged import parse_evidence_source

        body = "````\nEvidence-Source: OCC#5032\n```\nEvidence-Source: OCC#9999\n"
        assert parse_evidence_source(body) is None


class TestAutobindOutcomeShortCircuit:
    """OMN-18069 — the gate asks the producer instead of waiting it out.

    Fixtures are the REAL 2026-09-09 records: omninode_infra#1266 at head
    ``615219ec…`` (correlation ``d856d7ff-2044-4e3b-af1a-6d14ae892743``,
    published to ``onex.cmd.omnimarket.occ-autobind.v1`` partition 0 offset
    4508), whose autobind was consumed and then failed with
    ``Could not parse the provided public key.`` — one of 37 identical
    failures that each cost this gate its full 1500-second deadline.
    """

    HEAD = "615219ec46868e2ebf09f8b35a9e6cfc6d743dea"
    REASON = "failed: Could not parse the provided public key."

    def _outcome_run(
        self,
        outcome: str,
        *,
        name: str = AUTOBIND_OUTCOME_CHECK_NAME,
        completed_at: str = "2026-09-09T04:20:29Z",
        reason: str | None = None,
    ) -> dict[str, object]:
        summary = (
            f"{AUTOBIND_OUTCOME_MARKER_PREFIX} {outcome} "
            f"repo=OmniNode-ai/omninode_infra pr=1266 "
            f"correlation_id=d856d7ff-2044-4e3b-af1a-6d14ae892743 "
            f"reason={reason if reason is not None else self.REASON}\n\n"
            "prose a human reads\n"
        )
        return {
            "name": name,
            "status": "completed",
            "completed_at": completed_at,
            "output": {"title": f"{outcome}: x", "summary": summary},
        }

    def _fetcher(self, runs: list[dict[str, object]] | None) -> FakeFetcher:
        return FakeFetcher(
            prs={
                (PRODUCT_REPO, "2500"): _product_pr(
                    "no evidence yet", head_sha=self.HEAD
                )
            },
            check_runs={(PRODUCT_REPO, self.HEAD): runs},
        )

    def test_reported_error_fails_immediately_naming_the_reason(self) -> None:
        verdict = _evaluate(self._fetcher([self._outcome_run("ERROR")]))
        assert verdict.code == EXIT_FAIL
        assert "Could not parse the provided public key." in verdict.reason
        assert "will NOT appear" in verdict.reason

    def test_no_outcome_posted_still_polls(self) -> None:
        """The ordinary in-flight case is unchanged — this is additive."""
        assert _evaluate(self._fetcher([])).code == EXIT_PENDING

    def test_an_unreadable_check_run_list_never_fails_the_pr(self) -> None:
        """Fail-OPEN here on purpose: the evidence is written by another repo's
        runtime, and an outage there must not become an outage on this gate."""
        assert _evaluate(self._fetcher(None)).code == EXIT_PENDING

    def test_a_declined_outcome_still_polls(self) -> None:
        """A DECLINED outcome (lease held, suppression) may still resolve —
        another producer can be minting. Only ERROR is terminal."""
        assert _evaluate(self._fetcher([self._outcome_run("DECLINED")])).code == (
            EXIT_PENDING
        )

    def test_a_minted_outcome_still_polls_for_the_body_patch(self) -> None:
        assert _evaluate(self._fetcher([self._outcome_run("MINTED")])).code == (
            EXIT_PENDING
        )

    def test_a_check_run_with_another_name_is_ignored(self) -> None:
        runs = [self._outcome_run("ERROR", name="occ-autobind / mint status")]
        assert _evaluate(self._fetcher(runs)).code == EXIT_PENDING

    def test_the_newest_outcome_wins(self) -> None:
        """Offsets 4508 and 4510 are the same PR: two dispatches, two outcomes."""
        runs = [
            self._outcome_run("ERROR", completed_at="2026-09-09T04:20:29Z"),
            self._outcome_run(
                "MINTED",
                completed_at="2026-09-09T04:45:17Z",
                reason="authored OCC#8760",
            ),
        ]
        assert _evaluate(self._fetcher(runs)).code == EXIT_PENDING

    def test_an_incomplete_check_run_is_not_read(self) -> None:
        run = self._outcome_run("ERROR")
        run["status"] = "in_progress"
        assert _evaluate(self._fetcher([run])).code == EXIT_PENDING

    def test_a_present_evidence_source_bypasses_the_probe_entirely(self) -> None:
        """The short-circuit only ever replaces a would-be timeout."""
        fetcher = FakeFetcher(
            prs={
                (PRODUCT_REPO, "2500"): _product_pr(
                    "Evidence-Source: OCC#8760", head_sha=self.HEAD
                ),
                (OCC_REPO, "8760"): {
                    "state": "MERGED",
                    "mergeCommit": {"oid": "a" * 40},
                },
            },
            check_runs={(PRODUCT_REPO, self.HEAD): [self._outcome_run("ERROR")]},
        )
        assert _evaluate(fetcher).code == EXIT_PASS


class TestReadAutobindOutcome:
    def test_marker_line_is_parsed_off_the_summary(self) -> None:
        summary = (
            f"{AUTOBIND_OUTCOME_MARKER_PREFIX} ERROR repo=r pr=1 "
            "correlation_id=c reason=boom happened\n\nprose\n"
        )
        parsed = read_autobind_outcome(
            [
                {
                    "name": AUTOBIND_OUTCOME_CHECK_NAME,
                    "status": "completed",
                    "completed_at": "2026-09-09T00:00:00Z",
                    "output": {"summary": summary},
                }
            ]
        )
        assert parsed == ("ERROR", "boom happened")

    def test_a_summary_with_no_marker_yields_none(self) -> None:
        assert (
            read_autobind_outcome(
                [
                    {
                        "name": AUTOBIND_OUTCOME_CHECK_NAME,
                        "status": "completed",
                        "output": {"summary": "just prose"},
                    }
                ]
            )
            is None
        )

    def test_an_empty_list_yields_none(self) -> None:
        assert read_autobind_outcome([]) is None

    def test_non_dict_entries_are_skipped(self) -> None:
        assert read_autobind_outcome(["nonsense", 3]) is None  # type: ignore[list-item]
