# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""A red ``dev`` head must notify somebody (OMN-18836).

The four behaviours the brief names are the four classes below, in order: a
red run files exactly one ticket; a second tick on the same sha files none; an
unreadable API files none, says which read failed, and exits non-zero; a green
run files none. Two more are here because they are the cases that make the
monitor either trustworthy or noise.

``cancelled`` is the one worth reading twice. On the watched workflow it is
the ORDINARY outcome of two merges landing inside one run's wall clock — the
concurrency group coalesces them and the older run is cancelled — so a monitor
that mapped it to green would report health nobody observed, and one that
mapped it to red would file a ticket for a head that no longer exists. It is
its own outcome and is asserted to be distinguishable from both.

Every test drives fake ports. Nothing here touches the network, which is what
lets the branch table be exhaustive rather than representative.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import pytest

from scripts.ci.dev_head_red_alert import (
    EnumDevHeadOutcome,
    EnumHeadVerdict,
    RunObservation,
    WatchTarget,
    classify_conclusion,
    decide_dev_head,
    failing_job_names_in_payload,
    issue_title,
    main,
)

REPO = "OmniNode-ai/omnibase_infra"
SHA = "857726513f15af20e858eafb4cddb4d31c74650b"
TARGET = WatchTarget(repo=REPO, workflow="ci.yml", branch="dev")


class FakeGh:
    """A :class:`GhPort` whose every read can be told to fail."""

    def __init__(
        self,
        run: RunObservation | None,
        *,
        raise_on: str = "",
        pr_number: int | None = 3818,
        existing_comment: bool = False,
    ) -> None:
        self._run = run
        self._raise_on = raise_on
        self._pr_number = pr_number
        self._existing_comment = existing_comment
        self.comments: list[tuple[int, str]] = []

    def _maybe_raise(self, name: str) -> None:
        if self._raise_on == name:
            raise RuntimeError(f"simulated {name} failure")

    def latest_completed_push_run(
        self, *, repo: str, workflow: str, branch: str
    ) -> RunObservation | None:
        self._maybe_raise("runs")
        return self._run

    def failing_job_names(self, *, repo: str, run_id: int) -> tuple[str, ...]:
        self._maybe_raise("jobs")
        return ("Deploy Agent Tests (OMN-15378) / deploy-agent-tests", "CI Summary")

    def merge_pull_request(self, *, repo: str, head_sha: str) -> int | None:
        self._maybe_raise("pulls")
        return self._pr_number

    def comment_exists(self, *, repo: str, number: int, marker: str) -> bool:
        self._maybe_raise("comments")
        if self._existing_comment:
            return True
        return any(marker in body for _, body in self.comments)

    def add_comment(self, *, repo: str, number: int, body: str) -> None:
        self._maybe_raise("add_comment")
        self.comments.append((number, body))


class FakeLinear:
    """A :class:`LinearPort` that records creates and can be made unavailable."""

    def __init__(
        self,
        *,
        available: bool = True,
        existing: str | None = None,
        raise_on: str = "",
    ) -> None:
        self._available = available
        self._existing = existing
        self._raise_on = raise_on
        self.created: list[dict[str, str]] = []

    @property
    def available(self) -> bool:
        return self._available

    def find_issue(self, *, title: str) -> str | None:
        if self._raise_on == "find":
            raise RuntimeError("simulated Linear search failure")
        for issue in self.created:
            if issue["title"] == title:
                return "OMN-99999"
        return self._existing

    def create_issue(
        self, *, title: str, description: str, team_key: str, parent: str
    ) -> str:
        if self._raise_on == "create":
            raise RuntimeError("simulated Linear create failure")
        self.created.append(
            {
                "title": title,
                "description": description,
                "team_key": team_key,
                "parent": parent,
            }
        )
        return f"OMN-1000{len(self.created)}"


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    path = tmp_path / "watch.json"
    path.write_text(
        json.dumps(
            {
                "linear": {"team_key": "OMN", "parent_issue": "OMN-18834"},
                "targets": [{"repo": REPO, "workflow": "ci.yml", "branch": "dev"}],
            }
        ),
        encoding="utf-8",
    )
    return path


def _run(conclusion: str) -> RunObservation:
    return RunObservation(
        run_id=35444484991,
        head_sha=SHA,
        conclusion=conclusion,
        html_url="https://github.com/x/y/actions/runs/35444484991",
    )


def _main(
    config_path: Path, gh: FakeGh, linear: FakeLinear, *, dry_run: bool = False
) -> int:
    argv = ["--config", str(config_path)] + (["--dry-run"] if dry_run else [])
    return main(argv, gh=gh, linear=linear)


class TestRedRunFilesExactlyOneTicket:
    def test_one_ticket_is_created(
        self, config_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        gh, linear = FakeGh(_run("failure")), FakeLinear()
        assert _main(config_path, gh, linear) == 0
        assert len(linear.created) == 1, (
            f"expected exactly one ticket, got {linear.created!r}"
        )
        assert SHA[:8] in linear.created[0]["title"]
        assert "omnibase_infra" in linear.created[0]["title"]
        assert linear.created[0]["parent"] == "OMN-18834"
        assert EnumDevHeadOutcome.TICKET_FILED.value in capsys.readouterr().out

    def test_the_failing_jobs_are_named(self, config_path: Path) -> None:
        gh, linear = FakeGh(_run("failure")), FakeLinear()
        _main(config_path, gh, linear)
        body = linear.created[0]["description"]
        assert "Deploy Agent Tests (OMN-15378) / deploy-agent-tests" in body, (
            "the ticket does not name the job that failed, so the reader has "
            f"to open the run to learn anything. Got: {body!r}"
        )

    def test_the_merge_pull_request_is_commented_once(self, config_path: Path) -> None:
        """AC6 -- the durable surface that needs no Linear credential."""
        gh, linear = FakeGh(_run("failure")), FakeLinear()
        _main(config_path, gh, linear)
        assert len(gh.comments) == 1, f"expected one comment, got {gh.comments!r}"
        number, body = gh.comments[0]
        assert number == 3818
        assert SHA[:8] in body
        assert "Deploy Agent Tests (OMN-15378) / deploy-agent-tests" in body

    @pytest.mark.parametrize(
        "conclusion", ["failure", "timed_out", "startup_failure", "action_required"]
    )
    def test_every_red_conclusion_files(
        self, config_path: Path, conclusion: str
    ) -> None:
        """`startup_failure` matters most: it takes the rollup down by absence."""
        gh, linear = FakeGh(_run(conclusion)), FakeLinear()
        _main(config_path, gh, linear)
        assert len(linear.created) == 1, f"{conclusion!r} did not file"


class TestSecondTickOnTheSameShaFilesNothing:
    def test_no_second_ticket(self, config_path: Path) -> None:
        gh, linear = FakeGh(_run("failure")), FakeLinear()
        assert _main(config_path, gh, linear) == 0
        assert len(linear.created) == 1

        # Same sha, same run, a tick later. The schedule fires every ten
        # minutes and a red head stays red until somebody fixes it, so this is
        # the common case, not the edge case.
        assert _main(config_path, gh, linear) == 0
        assert len(linear.created) == 1, (
            "a second tick on the same head filed another ticket; at a "
            "ten-minute cadence that is six duplicates an hour until the head "
            f"is fixed. Got: {linear.created!r}"
        )

    def test_no_second_comment(self, config_path: Path) -> None:
        gh, linear = FakeGh(_run("failure")), FakeLinear()
        _main(config_path, gh, linear)
        _main(config_path, gh, linear)
        assert len(gh.comments) == 1, (
            f"the merge pull request was commented twice: {gh.comments!r}"
        )

    def test_an_issue_filed_by_an_earlier_process_also_dedups(
        self, config_path: Path
    ) -> None:
        """Dedup is a search, so it survives this process restarting."""
        gh = FakeGh(_run("failure"), existing_comment=True)
        linear = FakeLinear(existing="OMN-12345")
        assert _main(config_path, gh, linear) == 0
        assert linear.created == []
        assert gh.comments == []


class TestUnreadableApiFilesNothingAndExitsNonZero:
    @pytest.mark.parametrize("failing_read", ["runs", "jobs"])
    def test_a_failed_github_read_is_fatal(
        self, config_path: Path, failing_read: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        gh = FakeGh(_run("failure"), raise_on=failing_read)
        linear = FakeLinear()
        assert _main(config_path, gh, linear) == 1, (
            "an unreadable API exited zero. A monitor that cannot read the "
            "status it reasons about has not observed a green head; it has "
            "observed nothing, and reporting that as a clean sweep is the "
            "defect this module exists to avoid."
        )
        assert linear.created == []
        out = capsys.readouterr().out
        assert EnumDevHeadOutcome.UNREADABLE.value in out
        assert "::error::" in out
        assert failing_read in out or "could not read" in out

    @pytest.mark.parametrize("failing_call", ["find", "create"])
    def test_a_failed_linear_call_is_fatal(
        self, config_path: Path, failing_call: str
    ) -> None:
        gh = FakeGh(_run("failure"))
        linear = FakeLinear(raise_on=failing_call)
        assert _main(config_path, gh, linear) == 1
        assert linear.created == []

    def test_an_unreadable_config_is_fatal_and_files_nothing(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        missing = tmp_path / "absent.json"
        gh, linear = FakeGh(_run("failure")), FakeLinear()
        assert main(["--config", str(missing)], gh=gh, linear=linear) == 1
        assert linear.created == []
        assert "::error::" in capsys.readouterr().out

    def test_a_red_head_with_no_linear_credential_is_fatal(
        self, config_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Measured 2026-09-19: LINEAR_API_KEY is unset at org and repo scope.

        Degrading to a warning, the way the two existing workflows in this
        repository do, would make the monitor report a clean tick over a break
        it found and could not record. It still posts the comment, because
        that surface needs only the App token.
        """
        gh, linear = FakeGh(_run("failure")), FakeLinear(available=False)
        assert _main(config_path, gh, linear) == 1
        assert linear.created == []
        out = capsys.readouterr().out
        assert EnumDevHeadOutcome.FILING_UNAVAILABLE.value in out
        assert len(gh.comments) == 1, (
            "the comment is the surface that works without Linear and must "
            f"still be posted. Got: {gh.comments!r}"
        )


class TestGreenRunFilesNothing:
    def test_green_is_silent_and_exits_zero(
        self, config_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        gh, linear = FakeGh(_run("success")), FakeLinear()
        assert _main(config_path, gh, linear) == 0
        assert linear.created == []
        assert gh.comments == []
        assert EnumDevHeadOutcome.HEAD_GREEN.value in capsys.readouterr().out

    def test_green_with_no_linear_credential_is_still_quiet(
        self, config_path: Path
    ) -> None:
        """The missing key must be inert until it actually blocks something."""
        gh, linear = FakeGh(_run("success")), FakeLinear(available=False)
        assert _main(config_path, gh, linear) == 0, (
            "a green head went red because a credential it never needed was "
            "absent; at a ten-minute cadence that is 144 red runs a day and "
            "the job gets muted before the first real break arrives"
        )


class TestANonVerdictDecidesNothing:
    @pytest.mark.parametrize("conclusion", ["cancelled", "neutral", "skipped", "stale"])
    def test_no_verdict_is_neither_red_nor_green(
        self, config_path: Path, conclusion: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        gh, linear = FakeGh(_run(conclusion)), FakeLinear()
        assert _main(config_path, gh, linear) == 0
        assert linear.created == []
        assert gh.comments == []
        out = capsys.readouterr().out
        assert EnumDevHeadOutcome.NO_VERDICT.value in out, (
            f"{conclusion!r} did not produce its own outcome. On the watched "
            "workflow a cancelled push run is the ordinary result of two "
            "merges inside one run's wall clock; folding it into either "
            "verdict reports something nobody observed."
        )
        assert EnumDevHeadOutcome.HEAD_GREEN.value not in out

    def test_an_unknown_conclusion_does_not_file(self, config_path: Path) -> None:
        """GitHub has added conclusion values before."""
        gh, linear = FakeGh(_run("some_future_value")), FakeLinear()
        assert _main(config_path, gh, linear) == 0
        assert linear.created == []

    def test_no_completed_run_is_its_own_outcome(
        self, config_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        gh, linear = FakeGh(None), FakeLinear()
        assert _main(config_path, gh, linear) == 0
        assert EnumDevHeadOutcome.NO_COMPLETED_RUN.value in capsys.readouterr().out


class TestPureHelpers:
    @pytest.mark.parametrize(
        ("conclusion", "expected"),
        [
            ("failure", EnumHeadVerdict.RED),
            ("FAILURE", EnumHeadVerdict.RED),
            ("timed_out", EnumHeadVerdict.RED),
            ("startup_failure", EnumHeadVerdict.RED),
            ("action_required", EnumHeadVerdict.RED),
            ("success", EnumHeadVerdict.GREEN),
            ("cancelled", EnumHeadVerdict.UNDECIDED),
            ("", EnumHeadVerdict.UNDECIDED),
            ("brand_new", EnumHeadVerdict.UNDECIDED),
        ],
    )
    def test_conclusion_table(self, conclusion: str, expected: EnumHeadVerdict) -> None:
        assert classify_conclusion(conclusion) is expected

    def test_title_is_the_dedup_key(self) -> None:
        title = issue_title(REPO, SHA)
        assert title == "ci: dev red at 85772651 in omnibase_infra"
        assert issue_title(REPO, SHA) == title, "the title must be deterministic"

    def test_failing_job_names_excludes_skipped_and_cancelled(self) -> None:
        payload: dict[str, Any] = {
            "jobs": [
                {"name": "CI Tests Gate", "conclusion": "failure"},
                {"name": "Detect Changes", "conclusion": "skipped"},
                {"name": "Lint", "conclusion": "success"},
                {"name": "Runtime Boot Smoke (compose)", "conclusion": "cancelled"},
            ]
        }
        assert failing_job_names_in_payload(payload) == ("CI Tests Gate",), (
            "a skipped or cancelled job is not a failing job; naming one "
            "points the reader at the cascade instead of at its cause"
        )

    def test_decide_is_pure_over_its_inputs(self) -> None:
        red = decide_dev_head(TARGET, _run("failure"), already_filed=False)
        assert red.outcome is EnumDevHeadOutcome.TICKET_FILED
        again = decide_dev_head(TARGET, _run("failure"), already_filed=True)
        assert again.outcome is EnumDevHeadOutcome.ALREADY_FILED


class TestTheWatchlistIsData:
    def test_no_repository_slug_is_a_literal_in_the_decision_path(self) -> None:
        """AC7 -- adding a repository is a data change, never a code change.

        Scoped to the DECISION PATH, which is every string the module can act
        on. Docstrings are excluded deliberately: the module's own prose names
        the repository the 2026-09-19 incident happened in, and a test that
        banned that would be enforcing silence about the evidence rather than
        enforcing that the watchlist is data. A docstring cannot route a read.
        """
        module = (
            Path(__file__).resolve().parents[2]
            / "scripts"
            / "ci"
            / "dev_head_red_alert.py"
        )
        tree = ast.parse(module.read_text(encoding="utf-8"))

        docstrings = {
            id(node.body[0].value)
            for node in ast.walk(tree)
            if isinstance(
                node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
            )
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        }
        actionable = [
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstrings
        ]

        for slug in ("OmniNode-ai", "omnibase_infra", "omnimarket", "omniclaude"):
            offenders = [s for s in actionable if slug in s]
            assert not offenders, (
                f"{slug!r} appears in a live string in dev_head_red_alert.py. "
                "The watchlist is configuration precisely so that adding a "
                "repository the day its own push trigger lands is an edit to "
                f"the JSON and nothing else. Offending literals: {offenders!r}"
            )

    def test_the_shipped_config_parses_and_names_a_parent(self) -> None:
        from scripts.ci.dev_head_red_alert import DEFAULT_CONFIG_PATH, load_config

        config = load_config(DEFAULT_CONFIG_PATH)
        assert config.targets, "the shipped watchlist is empty"
        assert config.parent_issue.startswith("OMN-")
        assert config.team_key


class TestNoCallerAssertableVerdict:
    def test_the_parser_declares_no_conclusion_or_force_option(self) -> None:
        """The conclusion is resolved in-process, never handed to the module.

        Same posture as the prod-promotion gate's health probe: an option that
        let a caller assert the fact would let a caller file a ticket, or
        suppress one, against something this module never read.
        """
        from scripts.ci.dev_head_red_alert import _build_parser

        declared = {
            option
            for action in _build_parser()._actions
            for option in action.option_strings
        }
        for forbidden in (
            "--conclusion",
            "--status",
            "--force",
            "--skip",
            "--assume-green",
            "--head-sha",
        ):
            assert forbidden not in declared, (
                f"{forbidden} is declared on the parser; a caller-assertable "
                f"verdict is not a verdict. Declared: {sorted(declared)}"
            )


class TestWorkflowWiring:
    """A module nothing runs is not a monitor.

    The script above is exhaustively tested against fakes, which proves it
    decides correctly and proves nothing about whether it ever executes. These
    assertions are the other half: the job exists, on the schedule that
    already runs, with the identity its cross-repository reads require, and
    with no arrangement that would let a broken tick look like a clean one.
    """

    @staticmethod
    def _workflow() -> dict[str, Any]:
        import yaml

        path = (
            Path(__file__).resolve().parents[2]
            / ".github"
            / "workflows"
            / "occ-companion-merge-heal.yml"
        )
        with path.open(encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle)
        assert isinstance(loaded, dict)
        return loaded

    def test_the_job_exists_on_the_ten_minute_schedule(self) -> None:
        workflow = self._workflow()
        assert "dev-head-red-alert" in workflow["jobs"], (
            "the monitor job is gone from the workflow, so nothing runs "
            "dev_head_red_alert.py and a red dev head notifies no one again"
        )
        triggers = workflow.get(True, workflow.get("on"))
        crons = [entry["cron"] for entry in triggers["schedule"]]
        assert "*/10 * * * *" in crons, (
            f"the ten-minute schedule this job rides on is gone: {crons!r}"
        )

    def test_the_job_actually_invokes_the_script(self) -> None:
        steps = self._workflow()["jobs"]["dev-head-red-alert"]["steps"]
        runs = " ".join(str(step.get("run", "")) for step in steps)
        assert "scripts/ci/dev_head_red_alert.py" in runs, (
            "the job no longer runs the monitor; a job that does not call it "
            "is a green tick over nothing"
        )

    def test_the_job_cannot_pass_while_failing(self) -> None:
        job = self._workflow()["jobs"]["dev-head-red-alert"]
        assert "continue-on-error" not in job, (
            "continue-on-error on a monitor turns every unreadable tick into "
            "a green one, which is the exact failure the script's fail-closed "
            "exit code exists to prevent"
        )
        steps = job["steps"]
        for step in steps:
            assert "continue-on-error" not in step, (
                f"a step opts out of failure: {step.get('name')!r}"
            )
            assert "|| true" not in str(step.get("run", "")), (
                f"a step swallows its exit code: {step.get('name')!r}"
            )

    def test_the_token_is_scoped_and_has_no_fallback(self) -> None:
        """A silent fallback would read every watched head as unreadable.

        The ambient token cannot read another repository at all, so
        substituting it when the mint fails would not degrade the monitor, it
        would break it while looking configured.
        """
        steps = self._workflow()["jobs"]["dev-head-red-alert"]["steps"]
        mint = next(
            step
            for step in steps
            if "create-github-app-token" in str(step.get("uses", ""))
        )
        assert mint["with"]["permission-actions"] == "read"
        assert mint["with"]["permission-pull-requests"] == "write"
        assert "permission-contents" not in mint["with"], (
            "the token grants more than the two verbs this job uses"
        )
        run_step = next(
            step
            for step in steps
            if "dev_head_red_alert.py" in str(step.get("run", ""))
        )
        token = str(run_step["env"]["GH_TOKEN"])
        assert "app-token" in token, f"GH_TOKEN is not the App token: {token!r}"
        assert "||" not in token, f"GH_TOKEN carries a fallback expression: {token!r}"
