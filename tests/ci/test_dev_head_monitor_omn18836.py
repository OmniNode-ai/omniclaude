# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-18836: exercise the native monitor with hermetic external ports."""

from __future__ import annotations

import ast
import json
import runpy
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
import yaml

from omniclaude.nodes.node_dev_head_monitor_effect.handlers.handler_dev_head_monitor import (
    DEFAULT_CONFIG_PATH,
    EnumDevHeadOutcome,
    GhCli,
    HandlerDevHeadMonitor,
    LinearApi,
    ModelDevHeadMonitorRequest,
    RunObservation,
    WatchConfig,
    WatchTarget,
    comment_marker,
    issue_title,
    load_config,
)

ROOT = Path(__file__).resolve().parents[2]
REPO = "example/service"
SHA = "a" * 40
TARGET = WatchTarget(repo=REPO, workflow="ci.yml", branch="dev")
CONFIG = WatchConfig(targets=(TARGET,), team_key="TEAM", parent_issue="parent-id")


class FakeGh:
    def __init__(self, conclusion: str = "failure", *, fail: str = "") -> None:
        self.run = RunObservation(101, SHA, conclusion, "https://example.test/run/101")
        self.fail = fail
        self.comments: list[str] = []

    def _read(self, name: str) -> None:
        if self.fail == name:
            raise RuntimeError(f"unreadable {name}")

    def latest_completed_push_run(self, **kwargs: object) -> RunObservation | None:
        self._read("run list")
        return self.run

    def failing_job_names(self, **kwargs: object) -> tuple[str, ...]:
        self._read("job list")
        return ("unit tests", "contract boot")

    def merge_pull_request(self, **kwargs: object) -> int:
        self._read("merge PR")
        return 42

    def comment_exists(self, *, marker: str, **kwargs: object) -> bool:
        self._read("comment list")
        return any(marker in comment for comment in self.comments)

    def add_comment(self, *, body: str, **kwargs: object) -> None:
        self._read("comment write")
        self.comments.append(body)


class FakeLinear:
    available = True

    def __init__(self, *, fail: str = "") -> None:
        self.fail = fail
        self.created: list[dict[str, str]] = []

    def find_issue(self, *, title: str) -> str | None:
        if self.fail == "search":
            raise RuntimeError("unreadable Linear search")
        return next(
            ("issue-1" for item in self.created if item["title"] == title), None
        )

    def create_issue(self, **kwargs: str) -> str:
        if self.fail == "create":
            raise RuntimeError("unreadable Linear create")
        self.created.append(kwargs)
        return "issue-1"


def tick(gh: FakeGh, linear: FakeLinear):
    return HandlerDevHeadMonitor(config=CONFIG, gh=gh, linear=linear).handle(
        ModelDevHeadMonitorRequest(correlation_id=uuid4())
    )


@pytest.mark.parametrize(
    "conclusion", ["failure", "timed_out", "startup_failure", "action_required"]
)
def test_red_creates_one_issue_and_one_comment(conclusion: str) -> None:
    gh, linear = FakeGh(conclusion), FakeLinear()
    result = tick(gh, linear)
    assert result.exit_code == 0
    assert result.decisions[0].outcome == EnumDevHeadOutcome.TICKET_FILED
    assert len(linear.created) == 1
    assert SHA in linear.created[0]["title"]
    assert REPO in linear.created[0]["description"]
    assert len(gh.comments) == 1
    assert all(
        value in gh.comments[0] for value in (SHA, "unit tests", "contract boot")
    )


def test_next_tick_deduplicates_issue_and_comment() -> None:
    gh, linear = FakeGh(), FakeLinear()
    tick(gh, linear)
    result = tick(gh, linear)
    assert result.exit_code == 0
    assert result.decisions[0].outcome == EnumDevHeadOutcome.ALREADY_FILED
    assert len(linear.created) == 1
    assert len(gh.comments) == 1


def test_sha_prefix_collision_does_not_deduplicate_another_sha() -> None:
    gh, linear = FakeGh(), FakeLinear()
    tick(gh, linear)
    gh.run = RunObservation(102, SHA[:8] + "b" * 32, "failure")
    tick(gh, linear)
    assert len(linear.created) == 2
    assert len(gh.comments) == 2
    assert issue_title(REPO, SHA) != issue_title(REPO, gh.run.head_sha)


@pytest.mark.parametrize("read", ["run list", "job list", "merge PR", "comment list"])
def test_unreadable_github_fails_closed(
    read: str, caplog: pytest.LogCaptureFixture
) -> None:
    gh, linear = FakeGh(fail=read), FakeLinear()
    result = tick(gh, linear)
    assert result.exit_code == 1
    assert result.decisions[0].outcome == EnumDevHeadOutcome.UNREADABLE
    assert read in caplog.text
    assert linear.created == []
    assert gh.comments == []


@pytest.mark.parametrize("operation", ["search", "create"])
def test_unreadable_linear_fails_closed(
    operation: str, caplog: pytest.LogCaptureFixture
) -> None:
    gh, linear = FakeGh(), FakeLinear(fail=operation)
    result = tick(gh, linear)
    assert result.exit_code == 1
    assert "Linear" in caplog.text
    assert linear.created == []
    assert gh.comments == []


def test_green_creates_nothing() -> None:
    gh, linear = FakeGh("success"), FakeLinear()
    result = tick(gh, linear)
    assert result.exit_code == 0
    assert result.decisions[0].outcome == EnumDevHeadOutcome.HEAD_GREEN
    assert linear.created == []
    assert gh.comments == []


def test_dry_run_has_no_effects() -> None:
    gh, linear = FakeGh(), FakeLinear()
    result = HandlerDevHeadMonitor(config=CONFIG, gh=gh, linear=linear).handle(
        ModelDevHeadMonitorRequest(correlation_id=uuid4(), dry_run=True)
    )
    assert result.exit_code == 0
    assert linear.created == []
    assert gh.comments == []


@pytest.mark.parametrize("conclusion", ["cancelled", "neutral", "skipped"])
def test_cancelled_is_a_distinct_non_verdict(conclusion: str) -> None:
    gh, linear = FakeGh(conclusion), FakeLinear()
    result = tick(gh, linear)
    assert result.exit_code == 0
    assert result.decisions[0].outcome == EnumDevHeadOutcome.NO_VERDICT
    assert result.decisions[0].outcome != EnumDevHeadOutcome.HEAD_GREEN
    assert linear.created == []
    assert gh.comments == []


def test_comment_failure_is_reported_and_next_tick_repairs_without_new_issue() -> None:
    gh, linear = FakeGh(fail="comment write"), FakeLinear()
    assert tick(gh, linear).exit_code == 1
    assert len(linear.created) == 1
    gh.fail = ""
    assert tick(gh, linear).exit_code == 0
    assert len(linear.created) == 1
    assert len(gh.comments) == 1


def test_missing_linear_key_is_inert_only_on_green() -> None:
    linear = FakeLinear()
    linear.available = False
    assert tick(FakeGh("success"), linear).exit_code == 0
    assert tick(FakeGh("failure"), linear).exit_code == 1
    assert linear.created == []


def test_watchlist_is_data_and_request_cannot_assert_a_verdict() -> None:
    config = load_config(DEFAULT_CONFIG_PATH)
    assert config.targets
    assert "conclusion" not in ModelDevHeadMonitorRequest.model_fields
    import omniclaude.nodes.node_dev_head_monitor_effect.handlers.handler_dev_head_monitor as module

    tree = ast.parse(Path(module.__file__).read_text())
    for target in config.targets:
        assert not any(
            isinstance(item, ast.Constant) and item.value == target.repo
            for item in ast.walk(tree)
        )


def test_invalid_config_refuses_before_effects(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"targets": []}))
    with pytest.raises(RuntimeError):
        load_config(path)


def test_run_reader_rejects_unreadable_conclusion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gh = GhCli(token="fake-token")
    monkeypatch.setattr(
        gh,
        "_json",
        lambda args: {
            "workflow_runs": [{"id": 1, "head_sha": SHA, "conclusion": None}]
        },
    )
    with pytest.raises(RuntimeError, match="conclusion"):
        gh.latest_completed_push_run(repo=REPO, workflow="ci.yml", branch="dev")


@pytest.mark.parametrize("conclusion", ["", "unknown", "SUCCESS"])
def test_unrecognised_run_conclusion_fails_before_effects(
    conclusion: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = GhCli(token="fake-token")
    monkeypatch.setattr(
        client,
        "_json",
        lambda args: {
            "workflow_runs": [{"id": 101, "head_sha": SHA, "conclusion": conclusion}]
        },
    )
    gh, linear = FakeGh(), FakeLinear()
    gh.latest_completed_push_run = client.latest_completed_push_run
    result = tick(gh, linear)
    assert result.exit_code == 1
    assert "run list" in result.decisions[0].detail
    assert linear.created == []
    assert gh.comments == []


@pytest.mark.parametrize("read", ["merge PR", "comment list"])
def test_empty_paginated_response_fails_before_effects(
    read: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = GhCli(token="fake-token")
    monkeypatch.setattr(client, "_json", lambda args: [])
    gh, linear = FakeGh(), FakeLinear()
    if read == "merge PR":
        gh.merge_pull_request = client.merge_pull_request
    else:
        gh.comment_exists = client.comment_exists
    result = tick(gh, linear)
    assert result.exit_code == 1
    assert read in result.decisions[0].detail
    assert linear.created == []
    assert gh.comments == []


def test_linear_search_rejects_malformed_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    linear = LinearApi(api_key="fake-key")
    monkeypatch.setattr(linear, "_query", lambda *args: {"issues": {"nodes": [{}]}})
    with pytest.raises(RuntimeError):
        linear.find_issue(title="red head")


def test_github_reads_paginate_and_attribute_only_the_merge_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gh = GhCli(token="fake-token")
    calls: list[list[str]] = []
    marker = comment_marker(SHA)

    def api(args: list[str]) -> object:
        calls.append(args)
        if "/jobs?" in args[-1]:
            return [
                {"jobs": [{"name": "build", "conclusion": "success"}]},
                {"jobs": [{"name": "tests", "conclusion": "failure"}]},
            ]
        if args[-1].endswith("/pulls"):
            return [
                [
                    {"number": 1, "merged_at": None, "merge_commit_sha": SHA},
                    {"number": 2, "merged_at": "2026-10-08", "merge_commit_sha": SHA},
                ]
            ]
        return [[{"body": "other"}], [{"body": marker}]]

    monkeypatch.setattr(gh, "_json", api)
    assert gh.failing_job_names(repo=REPO, run_id=101) == ("tests",)
    assert gh.merge_pull_request(repo=REPO, head_sha=SHA) == 2
    assert gh.comment_exists(repo=REPO, number=2, marker=marker)
    assert all("--paginate" in args and "--slurp" in args for args in calls)


@pytest.mark.parametrize("read", ["job list", "merge PR", "comment list"])
def test_malformed_paginated_github_read_has_no_effects(
    read: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gh = GhCli(token="fake-token")
    monkeypatch.setattr(gh, "_json", lambda args: [{}])
    fake = FakeGh()
    if read == "job list":
        fake.failing_job_names = gh.failing_job_names
    elif read == "merge PR":
        fake.merge_pull_request = gh.merge_pull_request
    else:
        fake.comment_exists = gh.comment_exists
    linear = FakeLinear()
    result = tick(fake, linear)
    assert result.exit_code == 1
    assert read in result.decisions[0].detail
    assert linear.created == []
    assert fake.comments == []


# OMN-20074: the monitor's host is the non-OCC scheduled poller, so retiring
# occ-companion-merge-heal.yml with the rest of OCC does not delete it.
HOST_WORKFLOW = ROOT / ".github/workflows/auto-merge-stale-poller.yml"
OCC_HEAL_WORKFLOW = ROOT / ".github/workflows/occ-companion-merge-heal.yml"
MONITOR_CRON = "*/10 * * * *"
POLLER_CRON = "*/15 * * * *"


def _host_workflow() -> dict[str, Any]:
    document = yaml.safe_load(HOST_WORKFLOW.read_text())
    assert isinstance(document, dict)
    return document


def test_contract_and_schedule_wire_the_native_bus_worker() -> None:
    contract = yaml.safe_load(
        (
            ROOT / "src/omniclaude/nodes/node_dev_head_monitor_effect/contract.yaml"
        ).read_text()
    )
    workflow = _host_workflow()
    triggers = workflow.get("on", workflow.get(True))
    assert MONITOR_CRON in {entry["cron"] for entry in triggers["schedule"]}
    job = workflow["jobs"]["dev-head-red-alert"]
    assert "continue-on-error" not in job
    runs = "\n".join(step.get("run", "") for step in job["steps"])
    assert "run_monitor_tick" in runs
    assert 'backend_overrides={"event_bus": "kafka"}' in runs
    assert "host_handlers=True" in runs
    assert "scripts/ci/dev_head_red_alert.py" not in runs
    assert contract["event_bus"]["subscribe_topics"] == [
        "onex.cmd.omniclaude.dev-head-monitor.v1"
    ]
    assert contract["event_bus"]["publish_topics"] == [
        "onex.evt.omniclaude.dev-head-monitor-completed.v1"
    ]
    mint = next(
        step
        for step in job["steps"]
        if "create-github-app-token" in step.get("uses", "")
    )
    assert mint["with"]["permission-actions"] == "read"
    assert mint["with"]["permission-pull-requests"] == "write"


def test_monitor_is_not_hosted_by_the_occ_heal_workflow() -> None:
    occ_heal = yaml.safe_load(OCC_HEAL_WORKFLOW.read_text())
    assert "dev-head-red-alert" not in occ_heal["jobs"], (
        "the dev-head monitor must not live in the OCC heal workflow, which the "
        "OCC retirement deletes (OMN-20074)"
    )
    assert "dev-head-red-alert" in _host_workflow()["jobs"]


def test_each_job_runs_only_on_its_own_schedule() -> None:
    workflow = _host_workflow()
    triggers = workflow.get("on", workflow.get(True))
    assert {entry["cron"] for entry in triggers["schedule"]} == {
        MONITOR_CRON,
        POLLER_CRON,
    }
    jobs = workflow["jobs"]
    monitor_if = jobs["dev-head-red-alert"]["if"]
    poller_if = jobs["poll-and-enqueue"]["if"]
    assert f"github.event.schedule == '{MONITOR_CRON}'" in monitor_if
    assert f"github.event.schedule == '{POLLER_CRON}'" in poller_if
    assert POLLER_CRON not in monitor_if
    assert MONITOR_CRON not in poller_if


def test_host_grants_write_only_where_each_job_needs_it() -> None:
    workflow = _host_workflow()
    assert workflow["permissions"] == {"contents": "read"}
    jobs = workflow["jobs"]
    assert jobs["dev-head-red-alert"]["permissions"] == {"contents": "read"}
    assert jobs["poll-and-enqueue"]["permissions"] == {
        "contents": "read",
        "pull-requests": "write",
    }


def test_monitor_dry_run_is_its_own_dispatch_input() -> None:
    workflow = _host_workflow()
    triggers = workflow.get("on", workflow.get(True))
    inputs = triggers["workflow_dispatch"]["inputs"]
    assert inputs["dev-head-monitor-dry-run"]["type"] == "boolean"
    assert inputs["dev-head-monitor-dry-run"]["default"] is False
    steps = workflow["jobs"]["dev-head-red-alert"]["steps"]
    env = next(step["env"] for step in steps if "DRY_RUN" in step.get("env", {}))
    assert "inputs.dev-head-monitor-dry-run == true" in env["DRY_RUN"]


@pytest.mark.parametrize("sha", ["b" * 40, "dev"])
def test_ci_bus_checkout_uses_a_full_locked_sha(
    sha: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow = _host_workflow()
    steps = workflow["jobs"]["dev-head-red-alert"]["steps"]
    resolver = next(step for step in steps if step.get("id") == "bus_pin")
    checkout = next(
        step for step in steps if step.get("with", {}).get("path") == ".monitor-bus"
    )
    assert checkout["with"]["ref"] == "${{ steps.bus_pin.outputs.rev }}"
    script = resolver["run"].split("python3 - <<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
    script_path = tmp_path / "resolve_bus_source.py"
    script_path.write_text(script)
    (tmp_path / "uv.lock").write_text(
        '[[package]]\nname = "omnimarket"\n'
        f'source = {{ git = "https://example.test/repository.git#{sha}" }}\n'
    )
    output = tmp_path / "output"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    if sha == "dev":
        with pytest.raises(SystemExit, match="full commit sha"):
            runpy.run_path(str(script_path))
        assert not output.exists()
    else:
        runpy.run_path(str(script_path))
        assert output.read_text() == f"rev={sha}\n"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("conclusion", "fail", "expected"),
    [
        ("failure", "", "completed"),
        ("success", "", "completed"),
        ("cancelled", "", "completed"),
        ("failure", "run list", "failed"),
    ],
)
async def test_real_contract_executor_roundtrip(
    conclusion: str,
    fail: str,
    expected: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Use the same contract/adapter/handler as CI, with an in-memory test bus."""
    from importlib import metadata

    from omnibase_core.runtime.runtime_local import RuntimeLocal

    import omniclaude.nodes.node_dev_head_monitor_effect.handlers.handler_dev_head_monitor as module

    # The CI host loads the handler from its contract, without package discovery.
    entry_points = metadata.entry_points

    def without_monitor_entry_point(**kwargs):
        return metadata.EntryPoints(
            entry
            for entry in entry_points(**kwargs)
            if entry.name != "node_dev_head_monitor_effect"
        )

    monkeypatch.setattr(metadata, "entry_points", without_monitor_entry_point)
    assert not any(
        entry.name == "node_dev_head_monitor_effect"
        for entry in metadata.entry_points(group="onex.nodes")
    )
    gh, linear = FakeGh(conclusion, fail=fail), FakeLinear()
    monkeypatch.setattr(module, "GhCli", lambda **kwargs: gh)
    monkeypatch.setattr(module, "LinearApi", lambda **kwargs: linear)
    seen = []
    original = module.HandlerDevHeadMonitor.handle

    def capture(self, request):
        result = original(self, request)
        seen.append((request, result))
        return result

    monkeypatch.setattr(module.HandlerDevHeadMonitor, "handle", capture)
    contract = ROOT / "src/omniclaude/nodes/node_dev_head_monitor_effect/contract.yaml"
    runtime = RuntimeLocal(
        workflow_path=contract,
        state_root=tmp_path / "first",
        timeout=2,
        host_handlers=True,
    )
    result = await runtime.run_async()
    assert result.value.lower() == expected
    assert len(seen) == 1
    assert seen[0][0].correlation_id == seen[0][1].correlation_id
    if conclusion == "failure" and not fail:
        assert len(linear.created) == 1
        again = RuntimeLocal(
            workflow_path=contract,
            state_root=tmp_path / "second",
            timeout=2,
            host_handlers=True,
        )
        assert (await again.run_async()).value.lower() == "completed"
        assert len(linear.created) == 1
        assert len(gh.comments) == 1
    else:
        assert linear.created == []
        assert gh.comments == []
