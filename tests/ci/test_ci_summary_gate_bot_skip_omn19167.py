# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-19167 — the conditional L5 admission, ported from omnibase_infra.

The defect is the same as the one that blocked omnibase_infra#3953-#3958
(squash `dd113694080b64c28d7ffd9b2bbdf8aa9565bfe6`): `occ-autobind` and
`occ-companion-effect` gate their caller jobs on the pull request carrying a
ticket token, doctrine's PR-title rule deliberately exempts a dependency bump
from carrying one, so the caller skips and the strict L5 bar counts that
declared skip as red.

**This repository's case is a RACE, not a standing red, and that is worse to
diagnose rather than better to have.** On omniclaude#2308 both caller rows
concluded `skipped` at 09:05:17Z and the umbrella reported SUCCESS — because
its verdict landed at 09:19:35Z, 14m18s later, inside the 1200s supersession
grace, where `verdict_is_provisional` drops the row from `settled` and it
passes quietly. Replay the same committed payload with only the observation
time varied and it reds from +20m on. A slower run on a saturated fleet
therefore reds a head nothing is wrong with, and nothing about the pull request
predicts which it gets.

The time-boundary test below is the load-bearing one: it is what proves the
green was luck.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from datetime import UTC, datetime, timedelta  # noqa: E402
from typing import Any  # noqa: E402

import pytest  # noqa: E402

from scripts.ci.ci_summary_gate import (  # noqa: E402
    CONDITIONAL_SWEEP_EXCLUSIONS,
    DEPENDENCY_BOT_AUTHORS,
    EXTERNAL_SWEEP_EXCLUSIONS,
    CheckRunState,
    ConditionalSweepExclusion,
    PullRequestContext,
    check_run_event_index,
    conditional_exclusion_admits,
    evaluate_external_sweep,
    occ_caller_job_is_eligible,
    title_rule_exempts_ticket,
    validate_conditional_sweep_exclusions,
)

FIXTURE = REPO_ROOT / "tests/ci/fixtures/omn19167_dependabot_pr2308_check_runs.json"

# Well past the 1200s supersession grace on the fixture rows, so a shape test
# measures the registry and never the grace. The grace has its own test.
NOW = datetime(2026, 9, 22, 10, 30, tzinfo=UTC)

CALLER_NAMES = ("occ-autobind", "occ-companion-effect")


def _fixture() -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return payload


def _live_context() -> PullRequestContext:
    p = _fixture()["_provenance"]
    return PullRequestContext(
        author=p["pr_author"],
        title=p["pr_title"],
        head_ref=p["pr_head_ref"],
        actor=p["event_actor"],
    )


def _sweep(
    context: PullRequestContext | None,
    *,
    check_runs: list[dict[str, Any]] | None = None,
    conditional: dict[str, ConditionalSweepExclusion] | None = None,
    now: datetime | None = NOW,
) -> list[str]:
    head = _fixture()
    failures, _in_flight, swept, _excluded = evaluate_external_sweep(
        check_runs if check_runs is not None else head["check_runs"],
        in_run_names=frozenset(head["in_run_job_names"]),
        exclusions=EXTERNAL_SWEEP_EXCLUSIONS,
        conditional_exclusions=(
            CONDITIONAL_SWEEP_EXCLUSIONS if conditional is None else conditional
        ),
        pr_context=context,
        events=check_run_event_index(head["workflow_runs"]),
        now=now,
    )
    assert swept or _excluded, "the sweep judged nothing, so any verdict is vacuous"
    lines: list[str] = failures
    return lines


def _named(failures: list[str], name: str) -> bool:
    return any(f.startswith(f"{name} (") for f in failures)


def _with_conclusion(name: str, conclusion: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = _fixture()["check_runs"]
    hits = 0
    for row in rows:
        if row["name"] == name:
            row["conclusion"] = conclusion
            hits += 1
    assert hits == 1, f"expected exactly one {name!r} row, found {hits}"
    return rows


class TestTheFixtureIsTheRealHead:
    def test_it_carries_the_two_skipped_caller_rows(self) -> None:
        rows = {r["name"]: r for r in _fixture()["check_runs"]}
        for name in CALLER_NAMES:
            assert rows[name]["status"] == "completed"
            assert rows[name]["conclusion"] == "skipped", rows[name]

    def test_provenance_records_that_the_live_verdict_was_green(self) -> None:
        """The premise of the whole module: this head PASSED, on a race."""

        p = _fixture()["_provenance"]
        assert p["pr"] == 2308
        assert p["live_verdict"] == "SUCCESS"
        assert p["pr_author"] == "dependabot[bot]"
        skipped_at = datetime.fromisoformat(p["caller_rows_completed_at"])
        verdict_at = datetime.fromisoformat(p["live_verdict_at"])
        gap = (verdict_at - skipped_at).total_seconds()
        assert 0 < gap < 1200, gap

    def test_the_title_and_head_ref_carry_no_ticket_token(self) -> None:
        ctx = _live_context()
        assert not ctx.carries_ticket_token
        assert re.search(r"OMN-\d+", ctx.title) is None


class TestTheGreenWasLuck:
    """The load-bearing test. Only the observation time varies."""

    @pytest.mark.parametrize(
        ("minutes", "expect_red"),
        [(5, False), (15, False), (20, True), (30, True), (60, True)],
    )
    def test_without_the_registry_the_verdict_depends_on_the_clock(
        self, minutes: int, expect_red: bool
    ) -> None:
        base = datetime(2026, 9, 22, 9, 6, tzinfo=UTC)
        failures = _sweep(
            _live_context(), conditional={}, now=base + timedelta(minutes=minutes)
        )
        occ = [f for f in failures if f.startswith("occ-")]
        assert bool(occ) is expect_red, (minutes, failures)

    @pytest.mark.parametrize("minutes", [5, 15, 20, 30, 60, 600])
    def test_with_the_registry_the_clock_stops_mattering(self, minutes: int) -> None:
        base = datetime(2026, 9, 22, 9, 6, tzinfo=UTC)
        failures = _sweep(_live_context(), now=base + timedelta(minutes=minutes))
        assert [f for f in failures if f.startswith("occ-")] == [], (
            minutes,
            failures,
        )

    def test_the_admission_is_reported_with_its_predicate(self) -> None:
        head = _fixture()
        _f, _i, _s, excluded = evaluate_external_sweep(
            head["check_runs"],
            in_run_names=frozenset(head["in_run_job_names"]),
            exclusions=EXTERNAL_SWEEP_EXCLUSIONS,
            conditional_exclusions=CONDITIONAL_SWEEP_EXCLUSIONS,
            pr_context=_live_context(),
            events=check_run_event_index(head["workflow_runs"]),
            now=NOW,
        )
        for name in CALLER_NAMES:
            assert (
                f"{name} (skipped; declared_ticketless_dependency_bot_skip)" in excluded
            ), excluded

    def test_a_merely_provisional_row_is_not_reported_as_an_admission(self) -> None:
        """A race and a considered decision must not read the same."""

        base = datetime(2026, 9, 22, 9, 6, tzinfo=UTC)
        head = _fixture()
        _f, _i, _s, excluded = evaluate_external_sweep(
            head["check_runs"],
            in_run_names=frozenset(head["in_run_job_names"]),
            exclusions=EXTERNAL_SWEEP_EXCLUSIONS,
            conditional_exclusions={},
            pr_context=_live_context(),
            events=check_run_event_index(head["workflow_runs"]),
            now=base + timedelta(minutes=5),
        )
        assert not [e for e in excluded if e.startswith("occ-autobind (")], excluded


class TestTheShapesItMustRefuse:
    def test_ticketed_pr_with_a_skipped_autobind_still_fails(self) -> None:
        ctx = PullRequestContext(
            author="a-human",
            title="fix(OMN-19167): something ticketed",
            head_ref="feature/omn-19167-x",
            actor="a-human",
        )
        failures = _sweep(ctx)
        for name in CALLER_NAMES:
            assert _named(failures, name), (name, failures)

    def test_a_bot_pr_that_does_carry_a_ticket_still_fails(self) -> None:
        ctx = PullRequestContext(
            author="dependabot[bot]",
            title="chore(deps): bump something OMN-19167",
            head_ref="dependabot/github_actions/x",
            actor="a-human",
        )
        failures = _sweep(ctx)
        for name in CALLER_NAMES:
            assert _named(failures, name), (name, failures)

    def test_a_failed_autobind_still_fails(self) -> None:
        rows = _with_conclusion("occ-autobind", "failure")
        failures = _sweep(_live_context(), check_runs=rows)
        assert _named(failures, "occ-autobind"), failures
        assert not _named(failures, "occ-companion-effect"), failures

    def test_a_cancelled_autobind_still_fails(self) -> None:
        rows = _with_conclusion("occ-autobind", "cancelled")
        failures = _sweep(_live_context(), check_runs=rows)
        assert _named(failures, "occ-autobind"), failures

    def test_non_bot_ticketless_pr_still_fails(self) -> None:
        ctx = PullRequestContext(
            author="a-human",
            title="chore(deps): bump something with no ticket",
            head_ref="feature/no-ticket",
            actor="a-human",
        )
        failures = _sweep(ctx)
        for name in CALLER_NAMES:
            assert _named(failures, name), (name, failures)

    def test_no_context_admits_nothing(self) -> None:
        failures = _sweep(None)
        for name in CALLER_NAMES:
            assert _named(failures, name), (name, failures)

    @pytest.mark.parametrize("missing", ["author", "title"])
    def test_a_missing_required_field_admits_nothing(self, missing: str) -> None:
        live = _live_context()
        fields = {
            "author": live.author,
            "title": live.title,
            "head_ref": live.head_ref,
            "actor": live.actor,
        }
        fields[missing] = ""
        failures = _sweep(PullRequestContext(**fields))
        for name in CALLER_NAMES:
            assert _named(failures, name), (missing, failures)

    def test_a_missing_clock_admits_nothing(self) -> None:
        failures = _sweep(_live_context(), now=None)
        for name in CALLER_NAMES:
            assert _named(failures, name), failures

    def test_an_expired_entry_re_arms_the_sweep(self) -> None:
        failures = _sweep(_live_context(), now=datetime(2026, 12, 20, tzinfo=UTC))
        for name in CALLER_NAMES:
            assert _named(failures, name), failures

    def test_an_entry_naming_a_missing_predicate_admits_nothing(self) -> None:
        broken = {
            name: ConditionalSweepExclusion(
                reason="deliberately names a predicate that does not exist",
                ticket="OMN-19167",
                added="2026-09-22",
                expires="2026-12-20",
                conclusions=frozenset({"skipped"}),
                condition="no_such_predicate",
            )
            for name in CALLER_NAMES
        }
        failures = _sweep(_live_context(), conditional=broken)
        for name in CALLER_NAMES:
            assert _named(failures, name), failures
        assert validate_conditional_sweep_exclusions(broken)


class TestTheRegistryBar:
    def test_the_shipped_registry_validates(self) -> None:
        assert validate_conditional_sweep_exclusions(CONDITIONAL_SWEEP_EXCLUSIONS) == []

    def test_it_covers_exactly_the_two_caller_names(self) -> None:
        assert sorted(CONDITIONAL_SWEEP_EXCLUSIONS) == sorted(CALLER_NAMES)

    def test_every_entry_admits_only_skipped(self) -> None:
        for name, entry in CONDITIONAL_SWEEP_EXCLUSIONS.items():
            assert entry.conclusions == frozenset({"skipped"}), name

    def test_success_may_not_be_listed(self) -> None:
        bad = {
            "occ-autobind": ConditionalSweepExclusion(
                reason="lists success, which needs no admission",
                ticket="OMN-19167",
                added="2026-09-22",
                expires="2026-12-20",
                conclusions=frozenset({"skipped", "success"}),
                condition="declared_ticketless_dependency_bot_skip",
            )
        }
        assert any("success" in f for f in validate_conditional_sweep_exclusions(bad))

    @pytest.mark.parametrize(
        ("field", "value", "needle"),
        [
            ("reason", "   ", "reason is empty"),
            ("ticket", "OMN-", "OMN-<number>"),
            ("added", "yesterday", "YYYY-MM-DD"),
            ("expires", "2026-09-21", "not after added"),
            ("expires", "2027-09-22", "cap"),
        ],
    )
    def test_the_shared_field_checks_apply_here_too(
        self, field: str, value: str, needle: str
    ) -> None:
        kwargs: dict[str, Any] = {
            "reason": "a reason",
            "ticket": "OMN-19167",
            "added": "2026-09-22",
            "expires": "2026-12-20",
            "conclusions": frozenset({"skipped"}),
            "condition": "declared_ticketless_dependency_bot_skip",
        }
        kwargs[field] = value
        findings = validate_conditional_sweep_exclusions(
            {"occ-autobind": ConditionalSweepExclusion(**kwargs)}
        )
        assert any(needle in f for f in findings), findings

    def test_the_two_registries_do_not_overlap(self) -> None:
        assert not (set(CONDITIONAL_SWEEP_EXCLUSIONS) & set(EXTERNAL_SWEEP_EXCLUSIONS))

    def test_it_refuses_an_unregistered_name(self) -> None:
        state = CheckRunState("Some Other Gate", "completed", "skipped")
        assert not conditional_exclusion_admits(
            "Some Other Gate",
            state,
            exclusions=CONDITIONAL_SWEEP_EXCLUSIONS,
            context=_live_context(),
            now=NOW,
        )

    def test_it_refuses_an_incomplete_row(self) -> None:
        state = CheckRunState("occ-autobind", "in_progress", None)
        assert not conditional_exclusion_admits(
            "occ-autobind",
            state,
            exclusions=CONDITIONAL_SWEEP_EXCLUSIONS,
            context=_live_context(),
            now=NOW,
        )


_TITLE_CHECK_CALLER = REPO_ROOT / ".github/workflows/pr-title-check.yml"
_UPSTREAM_SLUG = "OmniNode-ai/onex_change_control"
_UPSTREAM_PATH = ".github/workflows/pr-title-check-reusable.yml"


def _pinned_title_check_ref() -> str | None:
    if not _TITLE_CHECK_CALLER.is_file():
        return None
    match = re.search(
        rf"{re.escape(_UPSTREAM_SLUG)}/{re.escape(_UPSTREAM_PATH)}@([0-9a-f]{{40}})",
        _TITLE_CHECK_CALLER.read_text(encoding="utf-8"),
    )
    return match.group(1) if match else None


class TestTheTitleRuleMirrorIsPinned:
    def test_this_repo_tracks_main_so_the_mirror_is_NOT_sha_pinned_here(self) -> None:
        """The residual, asserted rather than skipped past.

        omnibase_infra pins the PR-title reusable at a 40-hex sha, so a test
        there can compare the mirror's pin against the caller's and go red when
        upstream moves. THIS repo's caller tracks ``@main``. That is a real,
        weaker guarantee and it is recorded here instead of being hidden behind
        a skip: an edit to that reusable's ``main`` changes the enforcer with no
        file in this repository changing, so nothing local can go red for it.

        The differential bash control below catches a TRANSCRIPTION error in
        the mirror; it cannot catch upstream DRIFT, because it transcribes the
        same upstream text. Closing that needs this caller sha-pinned, which is
        a separate change with its own blast radius and is deliberately not
        made here.

        This test fails the day the caller IS sha-pinned, which is the prompt to
        adopt the stronger form.
        """

        assert _TITLE_CHECK_CALLER.is_file()
        text = _TITLE_CHECK_CALLER.read_text(encoding="utf-8")
        assert f"{_UPSTREAM_SLUG}/{_UPSTREAM_PATH}@main" in text, (
            "this caller no longer tracks @main. If it is now sha-pinned, "
            "replace this test with the omnibase_infra form: assert the pin "
            "equals the sha title_rule_exempts_ticket was read from."
        )
        assert _pinned_title_check_ref() is None

    def test_the_module_comment_names_the_source_repo_path_and_pin(self) -> None:
        source = (REPO_ROOT / "scripts/ci/ci_summary_gate.py").read_text(
            encoding="utf-8"
        )
        for needle in (
            _UPSTREAM_SLUG,
            _UPSTREAM_PATH,
            "babdd13ce68f07df20f989f52ff1c4514d03d896",
        ):
            assert needle in source, needle

    @pytest.mark.parametrize(
        ("author", "title", "expected"),
        [
            ("dependabot[bot]", "literally anything", True),
            ("renovate[bot]", "feat: a feature", True),
            ("a-human", "chore(deps): bump x from 1 to 2", True),
            ("a-human", "CHORE(DEPS): bump x", True),
            ("a-human", "build(deps-dev): bump y", True),
            ("a-human", "Bump actions/checkout from 4 to 5", True),
            ("a-human", "bumpy road ahead", False),
            ("a-human", "chore: release 1.2.3", True),
            ("a-human", "chore(release): 1.2.3", True),
            ("a-human", "release: 1.2.3", True),
            ("a-human", "feat(OMN-19167): a change", False),
            ("a-human", "feat: a change", False),
            ("", "chore(deps): bump x", False),
            ("a-human", "", False),
        ],
    )
    def test_the_mirror_matches_the_upstream_arms(
        self, author: str, title: str, expected: bool
    ) -> None:
        assert title_rule_exempts_ticket(author=author, title=title) is expected

    def test_the_mirror_agrees_with_the_upstream_shell(self) -> None:
        """Differential control: the upstream logic, run as bash."""

        script = r"""
        TITLE_LOWER=$(echo "$PR_TITLE" | tr '[:upper:]' '[:lower:]')
        if [[ -z "$PR_TITLE" ]]; then exit 1; fi
        if [[ "$PR_AUTHOR" == *"[bot]" ]]; then exit 0; fi
        if [[ "$TITLE_LOWER" =~ ^(chore\(deps|build\(deps|bump ) ]]; then exit 0; fi
        if [[ "$TITLE_LOWER" =~ ^(chore:\ release|chore\(release\)|release:) ]]; then exit 0; fi
        exit 1
        """
        cases = [
            ("dependabot[bot]", "literally anything"),
            ("a-human", "chore(deps): bump x from 1 to 2"),
            ("a-human", "CHORE(DEPS): bump x"),
            ("a-human", "Bump actions/checkout from 4 to 5"),
            ("a-human", "bumpy road ahead"),
            ("a-human", "chore: release 1.2.3"),
            ("a-human", "release: 1.2.3"),
            ("a-human", "feat(OMN-19167): a change"),
            ("a-human", ""),
        ]
        for author, title in cases:
            try:
                proc = subprocess.run(
                    ["bash", "-c", script],
                    env={
                        "PR_AUTHOR": author,
                        "PR_TITLE": title,
                        "PATH": "/usr/bin:/bin",
                    },
                    capture_output=True,
                    check=False,
                )
            except FileNotFoundError:  # pragma: no cover - bash is present in CI
                pytest.skip("bash unavailable")
            assert title_rule_exempts_ticket(author=author, title=title) is (
                proc.returncode == 0
            ), (author, title)


class TestTheProducerEligibilityMirror:
    @pytest.mark.parametrize(
        "path",
        [
            ".github/workflows/call-occ-autobind.yml",
            ".github/workflows/call-occ-companion-effect.yml",
        ],
    )
    def test_both_callers_still_gate_on_the_arms_this_mirrors(self, path: str) -> None:
        text = (REPO_ROOT / path).read_text(encoding="utf-8")
        assert "github.actor != 'dependabot[bot]'" in text, path
        assert "github.actor != 'renovate[bot]'" in text, path
        assert "contains(github.event.pull_request.title, 'OMN-')" in text, path
        assert "contains(github.event.pull_request.head.ref, 'OMN-')" in text, path

    def test_the_bot_set_matches_the_logins_the_callers_name(self) -> None:
        assert frozenset({"dependabot[bot]", "renovate[bot]"}) == DEPENDENCY_BOT_AUTHORS

    @pytest.mark.parametrize(
        ("actor", "title", "head_ref", "eligible"),
        [
            ("a-human", "feat(OMN-1): x", "feature/x", True),
            ("a-human", "chore(deps): x", "feature/omn-1-x", False),
            ("dependabot[bot]", "feat(OMN-1): x", "feature/x", False),
            ("renovate[bot]", "feat(OMN-1): x", "feature/x", False),
        ],
    )
    def test_eligibility_matches_the_expression(
        self, actor: str, title: str, head_ref: str, eligible: bool
    ) -> None:
        ctx = PullRequestContext(
            author="whoever", title=title, head_ref=head_ref, actor=actor
        )
        assert occ_caller_job_is_eligible(ctx) is eligible


class TestTheCliSurface:
    def test_the_parser_declares_the_four_arguments(self) -> None:
        source = (REPO_ROOT / "scripts/ci/ci_summary_gate.py").read_text(
            encoding="utf-8"
        )
        for flag in ("--pr-author", "--pr-title", "--pr-head-ref", "--event-actor"):
            assert f'"{flag}"' in source, flag

    def test_ci_yml_passes_all_four(self) -> None:
        text = (REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        for flag in ("--pr-author", "--pr-title", "--pr-head-ref", "--event-actor"):
            assert flag in text, flag
        for env in ("PR_AUTHOR:", "PR_TITLE:", "PR_HEAD_REF:", "EVENT_ACTOR:"):
            assert env in text, env
