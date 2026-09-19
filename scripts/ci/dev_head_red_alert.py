# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Notice that a repository's ``dev`` head is red, and say so (OMN-18836).

The gap this closes
-------------------
Nothing watches the health of any repository's ``dev`` head. No workflow opens
an issue on a red ``dev``, no schedule reads ``dev``'s CI conclusion, and no
Slack path is wired to one. Detection is therefore a function of whether
somebody happened to be pushing at the time.

Measured 2026-09-19 on ``omnibase_infra``: ``dev`` broke twice in two hours,
both times from the UNION of two individually green pull requests. Break-to-
notice on the first was 30 minutes 57 seconds, and the "notice" was a human
diagnosis attached to one pull request's own remediation attempt, not a
broadcast — nothing forced anyone else to read it. Five of six open pull
requests were blocked for the duration. The only durable record of either
break is a ledger row a lane typed by hand after hitting the failure while
trying to land unrelated work.

What this does
--------------
Once per tick, per watched target: read the latest COMPLETED push-triggered
run of that repository's CI workflow on ``dev``, and on a red conclusion not
already recorded, file a Linear issue for that head sha and comment on the
merge pull request that produced it, naming the jobs that failed.

Three properties are load-bearing.

**A conclusion is not a verdict.** ``cancelled`` is the common case here rather
than an exotic one: the watched workflow's concurrency group coalesces a burst
of merges onto the newest head, so an intermediate push run is routinely
cancelled by the next merge. That run decided nothing. Treating it as green
would report health this module never observed, and treating it as red would
file a ticket for a head that no longer exists. It is its own outcome,
:data:`EnumDevHeadOutcome.NO_VERDICT`, and so are ``neutral`` and ``skipped``.

**Fail closed, and say which read failed.** Every port error creates nothing,
names the read that failed, and exits non-zero. An unreadable status is never
treated as green — reporting a clean sweep over a read that did not happen is
precisely the defect that made the earlier heal in this directory look healthy
while it healed nothing.

**Dedup before create, on both surfaces.** The schedule fires every ten
minutes and a red head stays red until somebody fixes it, so the second tick
and the fifty after it must be silent. Linear is deduplicated by a title
search on the sha; the pull-request comment is deduplicated by a marker line
carrying the same sha.

The credential that does not exist yet, stated rather than discovered later
--------------------------------------------------------------------------
``LINEAR_API_KEY`` is set at neither org nor repository scope, read live on
2026-09-19 via ``gh secret list``. The two workflows in this repository that
reference it (``stale-todo-gate.yml``, ``todo-audit-on-merge.yml``) degrade to
a warning and skip, which is why nobody has noticed.

This module does NOT degrade that way, and it does not go red every tick
either. A missing key is inert while ``dev`` is green: nothing is attempted,
so a quiet tick stays quiet. It becomes a NAMED RED
(:data:`EnumDevHeadOutcome.FILING_UNAVAILABLE`) at the exact moment a red head
is observed and cannot be filed. The pull-request comment is posted anyway,
because that surface needs only the App token, so the break is recorded and
attributable even with no Linear at all. Adding the org secret activates the
other half with no code change.

Shape
-----
Mirrors ``scripts/ci/occ_companion_merge_heal.py``: a pure decision function
over a frozen observation, one :class:`Protocol` per external surface, a
concrete client per protocol, and a thin ``main()``. The pure half is
exhaustively unit-tested; the clients are exercised by the workflow.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess  # fixed argv, no shell, trusted gh binary
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Final, Protocol

EXIT_OK: Final[int] = 0
EXIT_ERROR: Final[int] = 1

#: Conclusions that mean "this head is broken". ``startup_failure`` is here
#: deliberately: a workflow file that fails to LOAD takes the required rollup
#: down by ABSENCE rather than by failure, which branch protection treats as
#: never-satisfied, and it is the single most disruptive shape this can take.
#: ``action_required`` is a run that stopped and is waiting for a human, which
#: is not a passing head either.
RED_CONCLUSIONS: Final[frozenset[str]] = frozenset(
    {"failure", "timed_out", "startup_failure", "action_required"}
)

#: The only conclusion that means the head is good. Deliberately a set of one.
GREEN_CONCLUSIONS: Final[frozenset[str]] = frozenset({"success"})

#: Conclusions that decide nothing. See the module docstring: on the watched
#: workflow a `cancelled` push run is the ORDINARY outcome of two merges
#: landing inside one run's wall clock, not an anomaly.
NON_VERDICT_CONCLUSIONS: Final[frozenset[str]] = frozenset(
    {"cancelled", "neutral", "skipped", "stale"}
)

#: Prefix of the marker line that makes the pull-request comment idempotent.
#: The sha is appended, so a second tick on the same head finds its own marker
#: and posts nothing.
COMMENT_MARKER_PREFIX: Final[str] = "<!-- onex:dev-head-red-alert:"

DEFAULT_CONFIG_PATH: Final[Path] = Path(__file__).with_name("dev_head_watch.json")

LINEAR_API_URL: Final[str] = "https://api.linear.app/graphql"
LINEAR_TIMEOUT_S: Final[int] = 30


class EnumDevHeadOutcome(StrEnum):
    """One value per branch. Every tick prints one of these per target.

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


def classify_conclusion(conclusion: str) -> EnumHeadVerdict:
    """Map a run conclusion onto what it says about the head.

    An unrecognised conclusion is UNDECIDED rather than RED. GitHub has added
    conclusion values before, and a new one must not be able to file tickets
    against every watched repository the hour it ships.
    """
    normalised = (conclusion or "").strip().lower()
    if normalised in RED_CONCLUSIONS:
        return EnumHeadVerdict.RED
    if normalised in GREEN_CONCLUSIONS:
        return EnumHeadVerdict.GREEN
    return EnumHeadVerdict.UNDECIDED


def issue_title(repo: str, head_sha: str) -> str:
    """The Linear title for a red head, and the string dedup searches on.

    The short sha and the bare repository name are both in it, so one search
    on this exact string answers "has this already been filed?" without a
    label, a custom field or any state kept by this module.

    It does NOT carry its own ticket id. A Linear issue cannot name its own
    identifier at creation time, because the identifier is assigned BY the
    create, so the conventional product-ticket title shape that embeds a
    ticket reference is not expressible for an issue naming itself. Linear
    renders the identifier beside the title anyway, so nothing is lost.

    Do not spell that shape literally in this docstring. Its placeholder
    digits collide with a marker the incomplete-implementation detector
    matches case-insensitively, and the prose alone fails the commit.
    """
    return f"ci: dev red at {head_sha[:8]} in {repo.rsplit('/', maxsplit=1)[-1]}"


def comment_marker(head_sha: str) -> str:
    """The idempotency marker for the pull-request comment on one head."""
    return f"{COMMENT_MARKER_PREFIX}{head_sha} -->"


def decide_dev_head(
    target: WatchTarget,
    run: RunObservation | None,
    *,
    already_filed: bool,
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
            detail=(
                f"{where}: no completed push-triggered run of {target.workflow} "
                "to read. Either nothing has merged since the trigger landed, "
                "or this target has no push trigger on that branch at all — "
                "the second is a watchlist error, not a green head"
            ),
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
            detail=(
                f"{at}: conclusion {run.conclusion!r} decides nothing — a "
                "superseded or non-verdict run is neither a red head nor a "
                "green one, and is not reported as either"
            ),
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

    def _json(self, args: list[str]) -> Any:
        completed = subprocess.run(  # noqa: S603 - fixed argv, trusted binary
            ["gh", *args],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"gh {' '.join(args)} exited {completed.returncode}: "
                f"{completed.stderr.strip()}"
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
                (
                    f"repos/{repo}/actions/workflows/{workflow}/runs"
                    f"?event=push&branch={branch}&status=completed&per_page=1"
                ),
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
        if not isinstance(run_id, int) or not isinstance(head_sha, str):
            raise RuntimeError(f"run entry for {repo}@{branch} carries no id/head_sha")
        conclusion = entry.get("conclusion")
        html_url = entry.get("html_url")
        return RunObservation(
            run_id=run_id,
            head_sha=head_sha,
            conclusion=conclusion if isinstance(conclusion, str) else "",
            html_url=html_url if isinstance(html_url, str) else "",
        )

    def failing_job_names(self, *, repo: str, run_id: int) -> tuple[str, ...]:
        payload = self._json(
            ["api", f"repos/{repo}/actions/runs/{run_id}/jobs?per_page=100"]
        )
        if not isinstance(payload, dict):
            raise RuntimeError(f"unreadable job list for {repo} run {run_id}")
        jobs = payload.get("jobs")
        if not isinstance(jobs, list):
            raise RuntimeError(f"job list for {repo} run {run_id} carries no jobs")
        return failing_job_names_in_payload(payload)

    def merge_pull_request(self, *, repo: str, head_sha: str) -> int | None:
        payload = self._json(["api", f"repos/{repo}/commits/{head_sha}/pulls"])
        if not isinstance(payload, list):
            raise RuntimeError(f"unreadable pull list for {repo} sha {head_sha[:8]}")
        for entry in payload:
            if isinstance(entry, dict) and isinstance(entry.get("number"), int):
                number = entry["number"]
                assert isinstance(number, int)
                return number
        return None

    def comment_exists(self, *, repo: str, number: int, marker: str) -> bool:
        payload = self._json(
            ["api", f"repos/{repo}/issues/{number}/comments?per_page=100"]
        )
        if not isinstance(payload, list):
            raise RuntimeError(f"unreadable comments for {repo}#{number}")
        return any(
            isinstance(entry, dict)
            and isinstance(entry.get("body"), str)
            and marker in entry["body"]
            for entry in payload
        )

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
        return ()
    jobs = payload.get("jobs")
    if not isinstance(jobs, list):
        return ()
    out: list[str] = []
    for entry in jobs:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        conclusion = entry.get("conclusion")
        if not isinstance(name, str) or not isinstance(conclusion, str):
            continue
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
        self._api_key = api_key or os.environ.get("LINEAR_API_KEY", "")

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    def _query(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        if not self.available:
            raise RuntimeError("no LINEAR_API_KEY configured")
        # Suppression rationale matches scripts/worktree_auto_prune.py:818 --
        # LINEAR_API_URL is a module constant naming one https endpoint, and no
        # part of the scheme, host or path is caller-supplied.
        request = urllib.request.Request(  # noqa: S310  # nosec B310 - constant https Linear endpoint, no user-supplied scheme
            LINEAR_API_URL,
            data=json.dumps({"query": query, "variables": variables}).encode(),
            headers={
                "Authorization": self._api_key,
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(  # noqa: S310  # nosec B310 - constant https Linear endpoint, no user-supplied scheme
                request, timeout=LINEAR_TIMEOUT_S
            ) as response:
                payload = json.loads(response.read().decode())
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Linear request failed: {exc}") from exc
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
            """
            query($title: String!) {
              issues(filter: { title: { eq: $title } }, first: 1) {
                nodes { identifier }
              }
            }
            """,
            {"title": title},
        )
        issues = data.get("issues")
        if not isinstance(issues, dict):
            raise RuntimeError("Linear search response carries no issues object")
        nodes = issues.get("nodes")
        if not isinstance(nodes, list):
            raise RuntimeError("Linear search response carries no nodes list")
        for node in nodes:
            if isinstance(node, dict) and isinstance(node.get("identifier"), str):
                identifier = node["identifier"]
                assert isinstance(identifier, str)
                return identifier
        return None

    def create_issue(
        self, *, title: str, description: str, team_key: str, parent: str
    ) -> str:
        teams = self._query(
            """
            query($key: String!) {
              teams(filter: { key: { eq: $key } }, first: 1) { nodes { id } }
            }
            """,
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
            """
            mutation($input: IssueCreateInput!) {
              issueCreate(input: $input) { success issue { identifier } }
            }
            """,
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
    return (
        f"Gate: live-gate defect: post-merge dev head CI\n\n"
        f"## What happened\n\n"
        f"The latest completed push-triggered run of `{target.workflow}` on "
        f"`{target.repo}` `{target.branch}` concluded `{run.conclusion}`.\n\n"
        f"- head sha: `{run.head_sha}`\n"
        f"- run: {run.html_url or run.run_id}\n\n"
        f"## Failing jobs\n\n{jobs}\n\n"
        f"## Why this matters\n\n"
        f"`{target.branch}` is the base every open pull request in that "
        f"repository merges into, so while this is red, every one of them "
        f"inherits the failure and none can land. Filed automatically by the "
        f"OMN-18836 dev-head monitor; this ticket exists so the break is "
        f"visible before somebody discovers it by accident.\n\n"
        f"## Acceptance criteria\n\n"
        f"- AC1: the named jobs pass on a later push-triggered run of the same "
        f"workflow on `{target.branch}`. Falsifier: that run's conclusion is "
        f"anything but `success`.\n"
    )


def build_comment(
    decision: DevHeadDecision,
    run: RunObservation,
    target: WatchTarget,
    *,
    ticket: str,
) -> str:
    """The merge pull request's comment. Carries its own dedup marker."""
    jobs = "\n".join(f"- `{name}`" for name in decision.failing_jobs) or "- (none read)"
    filed = f"Filed as {ticket}." if ticket else "No Linear issue was filed."
    return (
        f"{comment_marker(run.head_sha)}\n"
        f"**`{target.branch}` went red at this merge.**\n\n"
        f"The push-triggered run of `{target.workflow}` on `{target.branch}` at "
        f"`{run.head_sha[:8]}` concluded `{run.conclusion}`.\n\n"
        f"Failing jobs:\n\n{jobs}\n\n"
        f"Run: {run.html_url or run.run_id}\n\n"
        f"This is not necessarily a defect in this pull request. A break can be "
        f"formed by the union of this merge with another that was also green on "
        f"its own — that is the case this monitor exists to catch. {filed}\n\n"
        f"Posted by the OMN-18836 dev-head monitor."
    )


def evaluate_target(
    target: WatchTarget,
    *,
    gh: GhPort,
    linear: LinearPort,
    config: WatchConfig,
    dry_run: bool,
) -> DevHeadDecision:
    """Read one target and act on it. Every read failure becomes UNREADABLE."""
    try:
        run = gh.latest_completed_push_run(
            repo=target.repo, workflow=target.workflow, branch=target.branch
        )
    except RuntimeError as exc:
        return DevHeadDecision(
            outcome=EnumDevHeadOutcome.UNREADABLE,
            repo=target.repo,
            head_sha="",
            detail=f"{target.repo}: could not read the run list: {exc}",
        )

    if run is None or classify_conclusion(run.conclusion) is not EnumHeadVerdict.RED:
        return decide_dev_head(target, run, already_filed=False)

    title = issue_title(target.repo, run.head_sha)

    if not linear.available:
        # A red head we cannot file. Post what we can, then go red ourselves.
        detail = (
            f"{target.repo} {run.head_sha[:8]}: head is RED and no Linear "
            "credential is configured (LINEAR_API_KEY is unset at org and "
            "repo scope), so no ticket could be filed. The pull-request "
            "comment is still posted. This is reported as a failure rather "
            "than degraded to a warning: a monitor that cannot record what it "
            "found has not monitored anything"
        )
        decision = DevHeadDecision(
            outcome=EnumDevHeadOutcome.FILING_UNAVAILABLE,
            repo=target.repo,
            head_sha=run.head_sha,
            detail=detail,
            failing_jobs=_jobs_or_empty(gh, target.repo, run.run_id),
        )
        _post_comment(gh, target, run, decision, ticket="", dry_run=dry_run)
        return decision

    try:
        existing = linear.find_issue(title=title)
    except RuntimeError as exc:
        return DevHeadDecision(
            outcome=EnumDevHeadOutcome.UNREADABLE,
            repo=target.repo,
            head_sha=run.head_sha,
            detail=f"{target.repo}: could not search Linear: {exc}",
        )

    if existing is not None:
        return decide_dev_head(target, run, already_filed=True)

    try:
        failing = gh.failing_job_names(repo=target.repo, run_id=run.run_id)
    except RuntimeError as exc:
        return DevHeadDecision(
            outcome=EnumDevHeadOutcome.UNREADABLE,
            repo=target.repo,
            head_sha=run.head_sha,
            detail=f"{target.repo}: could not read the job list: {exc}",
        )

    decision = DevHeadDecision(
        outcome=EnumDevHeadOutcome.TICKET_FILED,
        repo=target.repo,
        head_sha=run.head_sha,
        detail=f"{target.repo} {run.head_sha[:8]}: RED ({run.conclusion}), filing",
        failing_jobs=failing,
    )

    ticket = ""
    if dry_run:
        ticket = "(dry run)"
    else:
        try:
            ticket = linear.create_issue(
                title=title,
                description=build_description(decision, run, target),
                team_key=config.team_key,
                parent=config.parent_issue,
            )
        except RuntimeError as exc:
            return DevHeadDecision(
                outcome=EnumDevHeadOutcome.UNREADABLE,
                repo=target.repo,
                head_sha=run.head_sha,
                detail=f"{target.repo}: could not create the Linear issue: {exc}",
                failing_jobs=failing,
            )

    _post_comment(gh, target, run, decision, ticket=ticket, dry_run=dry_run)
    return DevHeadDecision(
        outcome=decision.outcome,
        repo=decision.repo,
        head_sha=decision.head_sha,
        detail=f"{decision.detail} -> {ticket}",
        failing_jobs=failing,
    )


def _jobs_or_empty(gh: GhPort, repo: str, run_id: int) -> tuple[str, ...]:
    """Failing job names, or empty if they cannot be read.

    Used only on the path that is ALREADY going red for a different reason, so
    a second failure here must not mask the first.
    """
    try:
        return gh.failing_job_names(repo=repo, run_id=run_id)
    except RuntimeError:
        return ()


def _post_comment(
    gh: GhPort,
    target: WatchTarget,
    run: RunObservation,
    decision: DevHeadDecision,
    *,
    ticket: str,
    dry_run: bool,
) -> None:
    """Comment on the merge pull request, once per head sha.

    Best effort by design: the comment is the secondary surface, and a repo
    whose pull request cannot be resolved must not suppress the ticket that
    was already filed.
    """
    try:
        number = gh.merge_pull_request(repo=target.repo, head_sha=run.head_sha)
        if number is None:
            print(f"::warning::no merge pull request found for {run.head_sha[:8]}")
            return
        if gh.comment_exists(
            repo=target.repo, number=number, marker=comment_marker(run.head_sha)
        ):
            return
        if dry_run:
            print(f"  would comment on {target.repo}#{number}")
            return
        gh.add_comment(
            repo=target.repo,
            number=number,
            body=build_comment(decision, run, target, ticket=ticket),
        )
        print(f"  commented on {target.repo}#{number}")
    except RuntimeError as exc:
        print(f"::warning::could not comment for {run.head_sha[:8]}: {exc}")


def _build_parser() -> argparse.ArgumentParser:
    """The CLI.

    There is deliberately no flag that asserts a run's conclusion, no
    ``--force`` and no ``--skip``. The conclusion is resolved in-process from
    the Actions API on every tick, and a caller-assertable verdict would let a
    caller file a ticket against a fact this module never read — the same
    un-forgeability the prod-promotion gate spends a probe on.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
        help="path to the watchlist JSON",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report the decisions without filing or commenting",
    )
    return parser


def main(
    argv: list[str] | None = None,
    *,
    gh: GhPort | None = None,
    linear: LinearPort | None = None,
) -> int:
    args = _build_parser().parse_args(argv)
    gh_client: GhPort = gh if gh is not None else GhCli()
    linear_client: LinearPort = linear if linear is not None else LinearApi()

    try:
        config = load_config(Path(args.config))
    except RuntimeError as exc:
        print(f"::error::{exc}")
        return EXIT_ERROR

    decisions = [
        evaluate_target(
            target,
            gh=gh_client,
            linear=linear_client,
            config=config,
            dry_run=args.dry_run,
        )
        for target in config.targets
    ]

    errors = [d for d in decisions if d.is_error]
    for decision in decisions:
        line = f"{decision.outcome.value}: {decision.detail}"
        print(f"::error::{line}" if decision.is_error else line)

    print(f"read {len(decisions)} target(s); {len(errors)} could not be recorded")
    return EXIT_ERROR if errors else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
