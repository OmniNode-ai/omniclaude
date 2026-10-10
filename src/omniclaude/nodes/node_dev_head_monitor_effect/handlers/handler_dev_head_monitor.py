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
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from omniclaude.nodes.node_dev_head_monitor_effect.handlers.handler_gh_cli import (
    GhCli,
)
from omniclaude.nodes.node_dev_head_monitor_effect.handlers.handler_linear_api import (
    LinearApi,
)
from omniclaude.nodes.node_dev_head_monitor_effect.models.model_dev_head_types import (
    COMMENT_MARKER_PREFIX,
    DEFAULT_CONFIG_PATH,
    EXIT_ERROR,
    EXIT_OK,
    GREEN_CONCLUSIONS,
    NON_VERDICT_CONCLUSIONS,
    RED_CONCLUSIONS,
    DevHeadDecision,
    EnumDevHeadOutcome,
    EnumHeadVerdict,
    RunObservation,
    WatchTarget,
)

logger = logging.getLogger(__name__)


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
