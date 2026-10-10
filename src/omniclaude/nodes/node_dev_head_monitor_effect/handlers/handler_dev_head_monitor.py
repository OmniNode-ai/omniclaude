# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Native dev-head monitor (OMN-18836), integrating the prior monitor's ports.

The contract executor invokes this handler from a bus command. CI holds the
scoped GitHub installation token locally; neither credentials nor caller
asserted CI conclusions are accepted on the command topic.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Final, Literal, Protocol
from uuid import UUID

import httpx
import yaml
from pydantic import BaseModel, ConfigDict

logger = logging.getLogger(__name__)

EXIT_OK: Final[int] = 0
EXIT_ERROR: Final[int] = 1
RED_CONCLUSIONS: Final[frozenset[str]] = frozenset(
    {"failure", "timed_out", "startup_failure", "action_required"}
)
GREEN_CONCLUSIONS: Final[frozenset[str]] = frozenset({"success"})
NON_VERDICT_CONCLUSIONS: Final[frozenset[str]] = frozenset(
    {"cancelled", "neutral", "skipped", "stale"}
)
KNOWN_CONCLUSIONS: Final[frozenset[str]] = (
    RED_CONCLUSIONS | GREEN_CONCLUSIONS | NON_VERDICT_CONCLUSIONS
)
COMMENT_MARKER_PREFIX: Final[str] = "<!-- onex:dev-head-red-alert:"
DEFAULT_CONFIG_PATH: Final[Path] = (
    Path(__file__).resolve().parents[1] / "dev_head_watch.json"
)
LINEAR_TIMEOUT_S: Final[int] = 30


class EnumDevHeadOutcome(StrEnum):
    """One value per branch. Every tick records one of these per target.

    A single "nothing to do" covering both "the head is fine" and "I could not
    tell" is the failure mode this enum exists to prevent.
    """

    TICKET_FILED = "ticket_filed"
    ALREADY_FILED = "already_filed"
    HEAD_GREEN = "head_green"
    NO_VERDICT = "no_verdict"
    NO_COMPLETED_RUN = "no_completed_run"
    UNREADABLE = "unreadable"
    FILING_UNAVAILABLE = "filing_unavailable"


class EnumHeadVerdict(StrEnum):
    """What a run's conclusion says about the head, if anything."""

    RED = "red"
    GREEN = "green"
    UNDECIDED = "undecided"


@dataclass(frozen=True)
class WatchTarget:
    """One repository's ``dev`` head, and the workflow that proves it."""

    repo: str
    workflow: str
    branch: str


@dataclass(frozen=True)
class RunObservation:
    """The fields of an Actions run this module reasons about."""

    run_id: int
    head_sha: str
    conclusion: str
    html_url: str = ""


@dataclass(frozen=True)
class DevHeadDecision:
    """One target's verdict for one tick."""

    outcome: EnumDevHeadOutcome
    repo: str
    head_sha: str
    detail: str
    failing_jobs: tuple[str, ...] = ()

    @property
    def is_error(self) -> bool:
        """Whether this outcome must make the job go red.

        Both members are cases where the module KNOWS something is wrong and
        could not record it. Neither is "the head is broken" — a red head that
        was filed successfully is this module working, not failing.
        """
        return self.outcome in {
            EnumDevHeadOutcome.UNREADABLE,
            EnumDevHeadOutcome.FILING_UNAVAILABLE,
        }


class ModelDevHeadMonitorRequest(BaseModel):
    """A tick, with no caller-supplied conclusion or credentials."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    correlation_id: UUID
    dry_run: bool = False


class ModelDevHeadMonitorResult(BaseModel):
    """Correlated terminal event for the scheduled contract executor."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    correlation_id: UUID
    status: Literal["completed", "failed"]
    decisions: tuple[DevHeadDecision, ...]

    @property
    def exit_code(self) -> int:
        return EXIT_ERROR if self.status == "failed" else EXIT_OK


def classify_conclusion(conclusion: str) -> EnumHeadVerdict:
    """Map a run conclusion onto what it says about the head.

    Only declared non-verdicts are UNDECIDED. An unrecognised conclusion is
    unreadable and must fail the tick before it can file a ticket.
    """
    normalised = (conclusion or "").strip().lower()
    if normalised in RED_CONCLUSIONS:
        return EnumHeadVerdict.RED
    if normalised in GREEN_CONCLUSIONS:
        return EnumHeadVerdict.GREEN
    if normalised in NON_VERDICT_CONCLUSIONS:
        return EnumHeadVerdict.UNDECIDED
    raise RuntimeError("run entry carries an unrecognised conclusion")


def issue_title(repo: str, head_sha: str) -> str:
    """Stable dedup key containing the full repository and full commit sha."""
    return f"ci: dev red at {head_sha} in {repo}"


def comment_marker(head_sha: str) -> str:
    """The idempotency marker for the pull-request comment on one head."""
    return f"{COMMENT_MARKER_PREFIX}{head_sha} -->"


def decide_dev_head(
    target: WatchTarget, run: RunObservation | None, *, already_filed: bool
) -> DevHeadDecision:
    """Decide what one target's latest completed push run means.

    Pure. Every read it depends on has already happened; nothing here can
    touch the network, which is what makes the branch table testable without
    a fixture server.
    """
    where = f"{target.repo}@{target.branch}"
    if run is None:
        return DevHeadDecision(
            outcome=EnumDevHeadOutcome.NO_COMPLETED_RUN,
            repo=target.repo,
            head_sha="",
            detail=f"{where}: no completed push-triggered run of {target.workflow} to read. Either nothing has merged since the trigger landed, or this target has no push trigger on that branch at all — the second is a watchlist error, not a green head",
        )
    verdict = classify_conclusion(run.conclusion)
    at = f"{where} {run.head_sha[:8]} (run {run.run_id})"
    if verdict is EnumHeadVerdict.GREEN:
        return DevHeadDecision(
            outcome=EnumDevHeadOutcome.HEAD_GREEN,
            repo=target.repo,
            head_sha=run.head_sha,
            detail=f"{at}: conclusion {run.conclusion!r}, head is green",
        )
    if verdict is EnumHeadVerdict.UNDECIDED:
        return DevHeadDecision(
            outcome=EnumDevHeadOutcome.NO_VERDICT,
            repo=target.repo,
            head_sha=run.head_sha,
            detail=f"{at}: conclusion {run.conclusion!r} decides nothing — a superseded or non-verdict run is neither a red head nor a green one, and is not reported as either",
        )
    if already_filed:
        return DevHeadDecision(
            outcome=EnumDevHeadOutcome.ALREADY_FILED,
            repo=target.repo,
            head_sha=run.head_sha,
            detail=f"{at}: red, and already filed on an earlier tick",
        )
    return DevHeadDecision(
        outcome=EnumDevHeadOutcome.TICKET_FILED,
        repo=target.repo,
        head_sha=run.head_sha,
        detail=f"{at}: conclusion {run.conclusion!r}, filing",
    )


class GhPort(Protocol):
    """The GitHub reads, and the one write, this module needs."""

    def latest_completed_push_run(
        self, *, repo: str, workflow: str, branch: str
    ) -> RunObservation | None: ...

    def failing_job_names(self, *, repo: str, run_id: int) -> tuple[str, ...]: ...

    def merge_pull_request(self, *, repo: str, head_sha: str) -> int | None: ...

    def comment_exists(self, *, repo: str, number: int, marker: str) -> bool: ...

    def add_comment(self, *, repo: str, number: int, body: str) -> None: ...


class LinearPort(Protocol):
    """The Linear search and create this module needs."""

    @property
    def available(self) -> bool:
        """Whether a credential is present. See the module docstring."""
        ...

    def find_issue(self, *, title: str) -> str | None: ...

    def create_issue(
        self, *, title: str, description: str, team_key: str, parent: str
    ) -> str: ...


class GhCli:
    """:class:`GhPort` over the ``gh`` binary. Fixed argv, never a shell."""

    def __init__(self, token: str = "") -> None:
        self._token = token

    def _json(self, args: list[str]) -> Any:
        if not self._token:
            raise RuntimeError("scoped GitHub App token is unavailable")
        try:
            completed = subprocess.run(
                ["gh", *args],
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
                env={**os.environ, "GH_TOKEN": self._token},
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError("GitHub request could not complete") from exc
        if completed.returncode != 0:
            raise RuntimeError(
                f"gh {' '.join(args)} exited {completed.returncode}: {completed.stderr.strip()}"
            )
        try:
            return json.loads(completed.stdout or "null")
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"gh {' '.join(args)} returned non-JSON: {exc}") from exc

    def latest_completed_push_run(
        self, *, repo: str, workflow: str, branch: str
    ) -> RunObservation | None:
        payload = self._json(
            [
                "api",
                f"repos/{repo}/actions/workflows/{workflow}/runs?event=push&branch={branch}&status=completed&per_page=1",
            ]
        )
        if not isinstance(payload, dict):
            raise RuntimeError(f"unreadable run list for {repo}@{branch}")
        runs = payload.get("workflow_runs")
        if not isinstance(runs, list):
            raise RuntimeError(f"run list for {repo}@{branch} carries no workflow_runs")
        if not runs:
            return None
        entry = runs[0]
        if not isinstance(entry, dict):
            raise RuntimeError(f"unreadable run entry for {repo}@{branch}")
        run_id = entry.get("id")
        head_sha = entry.get("head_sha")
        if not isinstance(run_id, int) or not isinstance(head_sha, str) or not head_sha:
            raise RuntimeError(f"run entry for {repo}@{branch} carries no id/head_sha")
        conclusion = entry.get("conclusion")
        if not isinstance(conclusion, str) or conclusion not in KNOWN_CONCLUSIONS:
            raise RuntimeError("run entry carries an unreadable conclusion")
        html_url = entry.get("html_url")
        return RunObservation(
            run_id=run_id,
            head_sha=head_sha,
            conclusion=conclusion,
            html_url=html_url if isinstance(html_url, str) else "",
        )

    def failing_job_names(self, *, repo: str, run_id: int) -> tuple[str, ...]:
        pages = self._json(
            [
                "api",
                "--paginate",
                "--slurp",
                f"repos/{repo}/actions/runs/{run_id}/jobs?per_page=100",
            ]
        )
        if not isinstance(pages, list) or not pages:
            raise RuntimeError(f"unreadable job list for {repo} run {run_id}")
        return tuple(
            name for page in pages for name in failing_job_names_in_payload(page)
        )

    def merge_pull_request(self, *, repo: str, head_sha: str) -> int | None:
        payload = self._json(
            ["api", "--paginate", "--slurp", f"repos/{repo}/commits/{head_sha}/pulls"]
        )
        if not isinstance(payload, list) or not payload:
            raise RuntimeError(f"unreadable pull list for {repo} sha {head_sha[:8]}")
        for page in payload:
            if not isinstance(page, list):
                raise RuntimeError("pull list carries an unreadable page")
            for entry in page:
                if not isinstance(entry, dict) or not isinstance(
                    entry.get("number"), int
                ):
                    raise RuntimeError("pull list carries a malformed pull request")
                if "merged_at" not in entry or "merge_commit_sha" not in entry:
                    raise RuntimeError("pull list carries no merge attribution")
                if entry.get("merged_at") and entry.get("merge_commit_sha") == head_sha:
                    number = entry["number"]
                    assert isinstance(number, int)
                    return number
        return None

    def comment_exists(self, *, repo: str, number: int, marker: str) -> bool:
        payload = self._json(
            [
                "api",
                "--paginate",
                "--slurp",
                f"repos/{repo}/issues/{number}/comments?per_page=100",
            ]
        )
        if not isinstance(payload, list) or not payload:
            raise RuntimeError(f"unreadable comments for {repo}#{number}")
        found = False
        for page in payload:
            if not isinstance(page, list):
                raise RuntimeError("comment list carries an unreadable page")
            for entry in page:
                if not isinstance(entry, dict) or not isinstance(
                    entry.get("body"), str
                ):
                    raise RuntimeError("comment list carries an unreadable comment")
                found = found or marker in entry["body"]
        return found

    def add_comment(self, *, repo: str, number: int, body: str) -> None:
        self._json(
            [
                "api",
                f"repos/{repo}/issues/{number}/comments",
                "-X",
                "POST",
                "-f",
                f"body={body}",
            ]
        )


def failing_job_names_in_payload(payload: object) -> tuple[str, ...]:
    """The names of the jobs that actually failed, in run order.

    A skipped or cancelled job is not a failing job. Naming one in the comment
    would point the reader at the cascade rather than at its cause.
    """
    if not isinstance(payload, dict):
        raise RuntimeError("job list carries an unreadable page")
    jobs = payload.get("jobs")
    if not isinstance(jobs, list):
        raise RuntimeError("job list carries no jobs")
    out: list[str] = []
    for entry in jobs:
        if not isinstance(entry, dict):
            raise RuntimeError("job list carries a malformed job")
        name = entry.get("name")
        conclusion = entry.get("conclusion")
        if not isinstance(conclusion, str) or conclusion not in KNOWN_CONCLUSIONS:
            raise RuntimeError("job list carries an unreadable conclusion")
        if not isinstance(name, str) or not name:
            raise RuntimeError("job list carries an unreadable job name")
        if conclusion.strip().lower() in RED_CONCLUSIONS:
            out.append(name)
    return tuple(out)


class LinearApi:
    """:class:`LinearPort` over Linear's GraphQL API.

    :attr:`available` is False when no key is configured. That is a
    configuration fact, not an error, and the caller decides what it means —
    see the module docstring for why it is inert on a green head and red on a
    red one.
    """

    def __init__(self, api_key: str = "") -> None:
        self._api_key = api_key
        try:
            contract = yaml.safe_load(
                (DEFAULT_CONFIG_PATH.parent / "contract.yaml").read_text()
            )
            endpoint = contract["metadata"]["integrations"]["linear"][
                "graphql_endpoint"
            ]
        except (OSError, yaml.YAMLError, KeyError, TypeError) as exc:
            raise RuntimeError("Linear integration contract is unreadable") from exc
        if not isinstance(endpoint, str) or not endpoint:
            raise RuntimeError("Linear integration contract carries no endpoint")
        self._endpoint = endpoint

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    def _query(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        if not self.available:
            raise RuntimeError("no LINEAR_API_KEY configured")
        try:
            response = httpx.post(
                self._endpoint,
                json={"query": query, "variables": variables},
                headers={"Authorization": self._api_key},
                timeout=LINEAR_TIMEOUT_S,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Linear request failed: {type(exc).__name__}") from None
        if not isinstance(payload, dict):
            raise RuntimeError("Linear returned a non-object response")
        if payload.get("errors"):
            raise RuntimeError(f"Linear returned errors: {payload['errors']}")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise RuntimeError("Linear response carries no data object")
        return data

    def find_issue(self, *, title: str) -> str | None:
        data = self._query(
            "\n            query($title: String!) {\n              issues(filter: { title: { eq: $title } }, first: 1, includeArchived: true) {\n                nodes { identifier }\n              }\n            }\n            ",
            {"title": title},
        )
        issues = data.get("issues")
        if not isinstance(issues, dict):
            raise RuntimeError("Linear search response carries no issues object")
        nodes = issues.get("nodes")
        if not isinstance(nodes, list):
            raise RuntimeError("Linear search response carries no nodes list")
        for node in nodes:
            if (
                not isinstance(node, dict)
                or not isinstance(node.get("identifier"), str)
                or not node["identifier"]
            ):
                raise RuntimeError("Linear search carries a malformed issue row")
            if isinstance(node, dict) and isinstance(node.get("identifier"), str):
                identifier = node["identifier"]
                assert isinstance(identifier, str)
                return identifier
        return None

    def create_issue(
        self, *, title: str, description: str, team_key: str, parent: str
    ) -> str:
        teams = self._query(
            "\n            query($key: String!) {\n              teams(filter: { key: { eq: $key } }, first: 1) { nodes { id } }\n            }\n            ",
            {"key": team_key},
        )
        team_id = _first_id(teams.get("teams"), what=f"team {team_key!r}")
        parent_data = self._query(
            "query($id: String!) { issue(id: $id) { id } }", {"id": parent}
        )
        issue = parent_data.get("issue")
        if not isinstance(issue, dict) or not isinstance(issue.get("id"), str):
            raise RuntimeError(f"Linear parent issue {parent!r} did not resolve")
        parent_id = issue["id"]
        created = self._query(
            "\n            mutation($input: IssueCreateInput!) {\n              issueCreate(input: $input) { success issue { identifier } }\n            }\n            ",
            {
                "input": {
                    "teamId": team_id,
                    "title": title,
                    "description": description,
                    "parentId": parent_id,
                }
            },
        )
        result = created.get("issueCreate")
        if not isinstance(result, dict) or not result.get("success"):
            raise RuntimeError(f"Linear issueCreate did not succeed: {result!r}")
        issue_node = result.get("issue")
        if not isinstance(issue_node, dict) or not isinstance(
            issue_node.get("identifier"), str
        ):
            raise RuntimeError("Linear issueCreate returned no identifier")
        identifier = issue_node["identifier"]
        assert isinstance(identifier, str)
        if not identifier:
            raise RuntimeError("Linear issueCreate returned an empty identifier")
        return identifier


def _first_id(container: object, *, what: str) -> str:
    if not isinstance(container, dict):
        raise RuntimeError(f"Linear response for {what} is not an object")
    nodes = container.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        raise RuntimeError(f"Linear returned no {what}")
    node = nodes[0]
    if not isinstance(node, dict) or not isinstance(node.get("id"), str):
        raise RuntimeError(f"Linear returned no id for {what}")
    identifier = node["id"]
    assert isinstance(identifier, str)
    if not identifier:
        raise RuntimeError(f"Linear returned an empty id for {what}")
    return identifier


@dataclass(frozen=True)
class WatchConfig:
    """The parsed watchlist. No repository slug lives in this module."""

    targets: tuple[WatchTarget, ...]
    team_key: str
    parent_issue: str


def load_config(path: Path) -> WatchConfig:
    """Read the watchlist, refusing anything it cannot fully understand."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"could not read watch config {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise RuntimeError(f"watch config {path} is not an object")
    linear = raw.get("linear")
    if not isinstance(linear, dict):
        raise RuntimeError(f"watch config {path} carries no `linear` object")
    team_key = linear.get("team_key")
    parent_issue = linear.get("parent_issue")
    if not isinstance(team_key, str) or not team_key:
        raise RuntimeError(f"watch config {path} carries no linear.team_key")
    if not isinstance(parent_issue, str) or not parent_issue:
        raise RuntimeError(f"watch config {path} carries no linear.parent_issue")
    entries = raw.get("targets")
    if not isinstance(entries, list) or not entries:
        raise RuntimeError(f"watch config {path} carries no targets")
    targets: list[WatchTarget] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise RuntimeError(f"watch config {path} carries a non-object target")
        repo = entry.get("repo")
        workflow = entry.get("workflow")
        branch = entry.get("branch")
        if not all(isinstance(v, str) and v for v in (repo, workflow, branch)):
            raise RuntimeError(
                f"watch config {path} target is missing a field: {entry}"
            )
        assert isinstance(repo, str)
        assert isinstance(workflow, str)
        assert isinstance(branch, str)
        targets.append(WatchTarget(repo=repo, workflow=workflow, branch=branch))
    return WatchConfig(
        targets=tuple(targets), team_key=team_key, parent_issue=parent_issue
    )


def build_description(
    decision: DevHeadDecision, run: RunObservation, target: WatchTarget
) -> str:
    """The Linear body for a red head. Names the suspects, not just the fact."""
    jobs = "\n".join(f"- `{name}`" for name in decision.failing_jobs) or "- (none read)"
    return f"Gate: live-gate defect: post-merge dev head CI\n\n## What happened\n\nThe latest completed push-triggered run of `{target.workflow}` on `{target.repo}` `{target.branch}` concluded `{run.conclusion}`.\n\n- head sha: `{run.head_sha}`\n- run: {run.html_url or run.run_id}\n\n## Failing jobs\n\n{jobs}\n\n## Why this matters\n\n`{target.branch}` is the base every open pull request in that repository merges into, so while this is red, every one of them inherits the failure and none can land. Filed automatically by the OMN-18836 dev-head monitor; this ticket exists so the break is visible before somebody discovers it by accident.\n\n## Acceptance criteria\n\n- AC1: the named jobs pass on a later push-triggered run of the same workflow on `{target.branch}`. Falsifier: that run's conclusion is anything but `success`.\n"


def build_comment(
    decision: DevHeadDecision, run: RunObservation, target: WatchTarget, *, ticket: str
) -> str:
    """The merge pull request's comment. Carries its own dedup marker."""
    jobs = "\n".join(f"- `{name}`" for name in decision.failing_jobs) or "- (none read)"
    filed = f"Filed as {ticket}." if ticket else "No Linear issue was filed."
    return f"{comment_marker(run.head_sha)}\n**`{target.branch}` went red at this merge.**\n\nThe push-triggered run of `{target.workflow}` on `{target.branch}` at `{run.head_sha[:8]}` concluded `{run.conclusion}`.\n\nFailing jobs:\n\n{jobs}\n\nRun: {run.html_url or run.run_id}\n\nThis is not necessarily a defect in this pull request. A break can be formed by the union of this merge with another that was also green on its own — that is the case this monitor exists to catch. {filed}\n\nPosted by the OMN-18836 dev-head monitor."


def evaluate_target(
    target: WatchTarget,
    *,
    gh: GhPort,
    linear: LinearPort,
    config: WatchConfig,
    dry_run: bool,
) -> DevHeadDecision:
    """Read every prerequisite before creating; retry a missing comment later."""
    run: RunObservation | None = None
    failing: tuple[str, ...] = ()
    read = "run list"
    try:
        run = gh.latest_completed_push_run(
            repo=target.repo, workflow=target.workflow, branch=target.branch
        )
        if (
            run is None
            or classify_conclusion(run.conclusion) is not EnumHeadVerdict.RED
        ):
            return decide_dev_head(target, run, already_filed=False)

        if not linear.available:
            return DevHeadDecision(
                EnumDevHeadOutcome.FILING_UNAVAILABLE,
                target.repo,
                run.head_sha,
                "red head cannot be recorded: Linear credential is unavailable",
            )

        read = "Linear search"
        title = issue_title(target.repo, run.head_sha)
        existing = linear.find_issue(title=title)
        read = "job list"
        failing = gh.failing_job_names(repo=target.repo, run_id=run.run_id)
        read = "merge PR"
        number = gh.merge_pull_request(repo=target.repo, head_sha=run.head_sha)
        read = "comment list"
        commented = number is not None and gh.comment_exists(
            repo=target.repo, number=number, marker=comment_marker(run.head_sha)
        )
        decision = DevHeadDecision(
            EnumDevHeadOutcome.ALREADY_FILED
            if existing
            else EnumDevHeadOutcome.TICKET_FILED,
            target.repo,
            run.head_sha,
            f"{target.repo}: red ({run.conclusion})",
            failing,
        )
        ticket = existing or "(dry run)"
        if not existing and not dry_run:
            read = "Linear create"
            ticket = linear.create_issue(
                title=title,
                description=build_description(decision, run, target),
                team_key=config.team_key,
                parent=config.parent_issue,
            )
        if number is not None and not commented and not dry_run:
            read = "comment write"
            gh.add_comment(
                repo=target.repo,
                number=number,
                body=build_comment(decision, run, target, ticket=ticket),
            )
        return decision
    except RuntimeError as exc:
        return DevHeadDecision(
            EnumDevHeadOutcome.UNREADABLE,
            target.repo,
            run.head_sha if run else "",
            f"{target.repo}: could not read or complete {read}: {exc}",
            failing,
        )


class HandlerDevHeadMonitor:
    """Native effect handler hosted by the scheduled contract executor.

    The executor constructs its ports in the CI process, after the job mints
    the scoped App token. These values never enter a request or result model.
    Explicit port injection supports hermetic acceptance tests.
    """

    handler_key = "dev_head_monitor"

    def __init__(
        self,
        *,
        config: WatchConfig | None = None,
        gh: GhPort | None = None,
        linear: LinearPort | None = None,
    ) -> None:
        self._config = (
            config if config is not None else load_config(DEFAULT_CONFIG_PATH)
        )
        self._gh = gh if gh is not None else GhCli(token=os.environ.get("GH_TOKEN", ""))
        self._linear = (
            linear
            if linear is not None
            else LinearApi(api_key=os.environ.get("LINEAR_API_KEY", ""))
        )

    def handle(self, request: ModelDevHeadMonitorRequest) -> ModelDevHeadMonitorResult:
        decisions = tuple(
            evaluate_target(
                target,
                gh=self._gh,
                linear=self._linear,
                config=self._config,
                dry_run=request.dry_run,
            )
            for target in self._config.targets
        )
        for decision in decisions:
            line = f"{decision.outcome.value}: {decision.detail}"
            if decision.is_error:
                logger.error("%s", line)
            else:
                logger.info("%s", line)
        return ModelDevHeadMonitorResult(
            correlation_id=request.correlation_id,
            status="failed"
            if any(decision.is_error for decision in decisions)
            else "completed",
            decisions=decisions,
        )
