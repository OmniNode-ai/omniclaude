# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Generate deterministic mock-seam fixtures for OMN-19513."""

from __future__ import annotations

import argparse
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import yaml
from pydantic import BaseModel, ConfigDict

from omniclaude.hooks.model_claude_hook_event import (
    EnumClaudeHookEventName,
    ModelClaudeHookEvent,
    ModelContentScrubResult,
    ModelHookCaptureResult,
    ModelHookContentRecord,
    ModelSubagentSidecar,
    map_hook_stdin,
)

type JsonValue = (
    None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]
)

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = REPO_ROOT / "tests/fixtures/hooks/claude_hook_capture"
FIXED_TIME = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)
FAKE_SECRET = "sk-ant-FAKE0000000000000000000000000000"  # noqa: S105  # pragma: allowlist secret  # secret-ok: planted fake fixture value
CONTRACT_PATH = (
    REPO_ROOT / "src/omniclaude/hooks/contracts/contract_hook_claude_capture.yaml"
)
# secret-ok: the next line is a detection regex, not a secret
_MOCK_SECRET_PATTERN = re.compile(r"sk-ant-[A-Za-z0-9_-]{8,}")  # secret-ok: regex


def _source_topic() -> str:
    """Read the metadata topic from the contract; topics never live in Python."""

    contract = yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))
    name = contract["topics"]["metadata"]["name"]
    if not isinstance(name, str) or not name:
        raise AssertionError("contract topics.metadata.name must be a string")
    return name


def mock_content_scrubber(value: str) -> ModelContentScrubResult:
    """MOCK span scrub for fixtures only -- NOT a production control.

    It stands in for the restricted content family's span scrub
    (capture_redaction.yaml secret_patterns, applied by the producer) so the
    fixtures show the required order: scrub first, then hash. It knows one
    pattern, the one the fixtures plant.
    """

    scrubbed, count = _MOCK_SECRET_PATTERN.subn("[REDACTED:anthropic_api_key]", value)
    if count:
        return ModelContentScrubResult(
            value=scrubbed,
            redaction_state="secret_detected",
            matched_pattern_names=("anthropic_api_key",),
        )
    return ModelContentScrubResult(
        value=value, redaction_state="clean", matched_pattern_names=()
    )


class ScenarioInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    stdin: dict[str, JsonValue]
    sidecar: ModelSubagentSidecar | None = None
    turn_id: str | None = "turn-fixed-1"


def _base(name: str, *, session_id: str = "session-fixture-1") -> dict[str, JsonValue]:
    return {
        "session_id": session_id,
        "transcript_path": f"/restricted/{session_id}.jsonl",
        "cwd": "/workspace/fixture",
        "prompt_id": "prompt-fixed-1",
        "permission_mode": "default",
        "effort": {"level": "high"},
        "hook_event_name": name,
    }


def _all_stdin() -> dict[EnumClaudeHookEventName, dict[str, JsonValue]]:
    fixtures: dict[EnumClaudeHookEventName, dict[str, JsonValue]] = {}

    def add(hook_name: EnumClaudeHookEventName, **fields: JsonValue) -> None:
        fixtures[hook_name] = {**_base(hook_name.value), **fields}

    add(
        EnumClaudeHookEventName.PRE_TOOL_USE,
        tool_name="Bash",
        tool_input={"command": "printf fixture", "timeout": 30},
        tool_use_id="toolu-fixture-1",
        mcp_server={"name": "fixture-server", "version": "1"},
    )
    add(
        EnumClaudeHookEventName.POST_TOOL_USE,
        tool_name="Bash",
        tool_input={"command": "printf fixture"},
        tool_response={"output": f"fixture {FAKE_SECRET}", "interrupted": False},
        tool_use_id="toolu-fixture-1",
        duration_ms=125,
    )
    add(
        EnumClaudeHookEventName.POST_TOOL_USE_FAILURE,
        tool_name="Bash",
        tool_input={"command": "exit 1"},
        tool_use_id="toolu-fixture-failure",
        error="private command failure text",
        is_interrupt=False,
        duration_ms=9,
    )
    add(
        EnumClaudeHookEventName.POST_TOOL_BATCH,
        tool_calls=[
            {
                "tool_name": "Read",
                "tool_input": {"file_path": "/private/a"},
                "tool_use_id": "toolu-batch-1",
                "tool_response": "private response",
            },
            {
                "tool_name": "Grep",
                "tool_input": {"pattern": "needle"},
                "tool_use_id": "toolu-batch-2",
            },
        ],
    )
    add(
        EnumClaudeHookEventName.NOTIFICATION,
        message="private notification message",
        title="private notification title",
        notification_type="permission_prompt",
    )
    add(
        EnumClaudeHookEventName.USER_PROMPT_SUBMIT,
        prompt=f"fixture prompt containing {FAKE_SECRET}",
        source="user",
        session_title="private session title",
    )
    add(
        EnumClaudeHookEventName.USER_PROMPT_EXPANSION,
        expansion_type="slash_command",
        command_name="review",
        command_args="private command arguments",
        command_source="project",
        prompt="private expanded prompt",
    )
    add(
        EnumClaudeHookEventName.SESSION_START,
        source="startup",
        model="claude-opus-4-1",
        session_title="private title not projected",
        seconds_since_last_response=12.5,
        context_tokens=4096,
        prompt_cache_likely_expired=False,
        estimated_cache_write_usd=0.01,
    )
    add(EnumClaudeHookEventName.SESSION_END, reason="clear")
    add(
        EnumClaudeHookEventName.STOP,
        stop_hook_active=True,
        last_assistant_message="private assistant response",
        background_tasks=[{"id": "background-1"}],
        session_crons=[{"id": "cron-1"}, {"id": "cron-2"}],
    )
    add(
        EnumClaudeHookEventName.STOP_FAILURE,
        error="max_turns",
        error_details="private stop error details",
        last_assistant_message="private final assistant text",
    )
    add(
        EnumClaudeHookEventName.SUBAGENT_START,
        agent_id="agent-fixture-1",
        agent_type="Explore",
    )
    add(
        EnumClaudeHookEventName.SUBAGENT_STOP,
        stop_hook_active=False,
        agent_id="agent-fixture-1",
        agent_type="Explore",
        agent_transcript_path="/restricted/agent-fixture-1.jsonl",
        last_assistant_message="private subagent answer",
        background_tasks=[],
        session_crons=[],
    )
    add(
        EnumClaudeHookEventName.PRE_COMPACT,
        trigger="manual",
        custom_instructions="private compaction instructions",
    )
    add(
        EnumClaudeHookEventName.POST_COMPACT,
        trigger="manual",
        compact_summary="private compact summary",
    )
    add(EnumClaudeHookEventName.PRE_MODEL_SWITCH)
    add(EnumClaudeHookEventName.POST_MODEL_SWITCH)
    add(
        EnumClaudeHookEventName.PERMISSION_REQUEST,
        tool_name="Bash",
        tool_input={"command": "private command"},
        permission_suggestions=[{"type": "allow_once"}],
        mcp_server={"name": "fixture-server"},
    )
    add(
        EnumClaudeHookEventName.PERMISSION_DENIED,
        tool_name="Bash",
        tool_input={"command": "private command"},
        tool_use_id="toolu-denied-1",
        reason="private denial reason",
    )
    add(EnumClaudeHookEventName.SETUP, trigger="init")
    add(
        EnumClaudeHookEventName.TEAMMATE_IDLE,
        teammate_name="teammate-fixture",
        team_name="team-fixture",
    )
    task_fields: dict[str, JsonValue] = {
        "task_id": "task-fixture-1",
        "task_subject": "private task subject",
        "task_description": "private task description",
        "teammate_name": "teammate-fixture",
        "team_name": "team-fixture",
    }
    add(EnumClaudeHookEventName.TASK_CREATED, **task_fields)
    add(EnumClaudeHookEventName.TASK_COMPLETED, **task_fields)
    add(
        EnumClaudeHookEventName.ELICITATION,
        mcp_server_name="fixture-server",
        message="private elicitation message",
        mode="form",
        elicitation_id="elicit-fixture-1",
        requested_schema={"account": {"type": "string"}, "region": {}},
    )
    add(
        EnumClaudeHookEventName.ELICITATION_RESULT,
        mcp_server_name="fixture-server",
        elicitation_id="elicit-fixture-1",
        mode="form",
        action="accept",
        content={"account": "private account", "region": "private region"},
    )
    add(
        EnumClaudeHookEventName.CONFIG_CHANGE,
        source="user_settings",
        file_path="/restricted/settings.json",
    )
    add(EnumClaudeHookEventName.WORKTREE_CREATE, name="private-worktree-name")
    add(
        EnumClaudeHookEventName.WORKTREE_REMOVE,
        worktree_path="/restricted/worktrees/private",
    )
    add(
        EnumClaudeHookEventName.INSTRUCTIONS_LOADED,
        file_path="/restricted/CLAUDE.md",
        memory_type="project",
        load_reason="session_start",
        globs=["**/*.md", "docs/**"],
        trigger_file_path="/restricted/trigger.md",
        parent_file_path="/restricted/parent.md",
    )
    add(
        EnumClaudeHookEventName.CWD_CHANGED,
        old_cwd="/restricted/old",
        new_cwd="/restricted/new",
    )
    add(
        EnumClaudeHookEventName.FILE_CHANGED,
        file_path="/restricted/private.py",
        event="change",
    )
    add(
        EnumClaudeHookEventName.DIRECTORY_ADDED,
        directory="/restricted/new-directory",
        source="slash_command",
    )
    add(
        EnumClaudeHookEventName.MESSAGE_DISPLAY,
        turn_id="turn-message-1",
        message_id="message-fixture-1",
        index=0,
        final=False,
        delta="private streamed delta",
    )
    return fixtures


def _sidecar(
    *,
    agent_type: str,
    spawn_depth: int,
    tool_use_id: str | None = None,
    workflow_phase: str | None = None,
    workflow_run_id: str | None = None,
) -> ModelSubagentSidecar:
    return ModelSubagentSidecar.model_validate(
        {
            "agentType": agent_type,
            "description": "deterministic fixture agent",
            "model": "claude-opus-4-1",
            "requestNonInteractive": True,
            "requestShape": "Agent",
            "spawnDepth": spawn_depth,
            "toolUseId": tool_use_id,
            "workflowPhase": workflow_phase,
            "workflow_run_id": workflow_run_id,
        }
    )


def _scenario_input(
    name: str,
    *,
    session_id: str,
    agent_id: str | None = None,
    agent_type: str | None = None,
    **fields: JsonValue,
) -> dict[str, JsonValue]:
    value = {**_base(name, session_id=session_id), **fields}
    if agent_id is not None:
        value["agent_id"] = agent_id
    if agent_type is not None:
        value["agent_type"] = agent_type
    return value


def _subagent_scenario() -> list[ScenarioInput]:
    session_id = "session-subagent-tree"
    a1_sidecar = _sidecar(
        agent_type="general-purpose", spawn_depth=1, tool_use_id="toolu_main_1"
    )
    a2_sidecar = _sidecar(
        agent_type="Explore", spawn_depth=2, tool_use_id="toolu_sub_2"
    )
    values = [
        ScenarioInput(
            stdin=_scenario_input(
                "UserPromptSubmit",
                session_id=session_id,
                prompt="build a nested agent fixture",
                source="user",
            )
        ),
        ScenarioInput(
            stdin=_scenario_input(
                "PreToolUse",
                session_id=session_id,
                tool_name="Agent",
                tool_input={"prompt": "spawn a1"},
                tool_use_id="toolu_main_1",
            )
        ),
        ScenarioInput(
            stdin=_scenario_input(
                "SubagentStart",
                session_id=session_id,
                agent_id="a1",
                agent_type="general-purpose",
            ),
            sidecar=a1_sidecar,
        ),
        ScenarioInput(
            stdin=_scenario_input(
                "PreToolUse",
                session_id=session_id,
                agent_id="a1",
                agent_type="general-purpose",
                tool_name="Bash",
                tool_input={"command": "printf a1"},
                tool_use_id="toolu_sub_1",
            ),
            sidecar=a1_sidecar,
        ),
        ScenarioInput(
            stdin=_scenario_input(
                "PostToolUse",
                session_id=session_id,
                agent_id="a1",
                agent_type="general-purpose",
                tool_name="Bash",
                tool_input={"command": "printf a1"},
                tool_response={"output": "a1 output"},
                tool_use_id="toolu_sub_1",
                duration_ms=4,
            ),
            sidecar=a1_sidecar,
        ),
        ScenarioInput(
            stdin=_scenario_input(
                "PreToolUse",
                session_id=session_id,
                agent_id="a1",
                agent_type="general-purpose",
                tool_name="Agent",
                tool_input={"prompt": "spawn a2"},
                tool_use_id="toolu_sub_2",
            ),
            sidecar=a1_sidecar,
        ),
        ScenarioInput(
            stdin=_scenario_input(
                "SubagentStart",
                session_id=session_id,
                agent_id="a2",
                agent_type="Explore",
            ),
            sidecar=a2_sidecar,
        ),
        ScenarioInput(
            stdin=_scenario_input(
                "PreToolUse",
                session_id=session_id,
                agent_id="a2",
                agent_type="Explore",
                tool_name="Read",
                tool_input={"file_path": "/restricted/nested.py"},
                tool_use_id="toolu_sub_3",
            ),
            sidecar=a2_sidecar,
        ),
        ScenarioInput(
            stdin=_scenario_input(
                "PostToolUse",
                session_id=session_id,
                agent_id="a2",
                agent_type="Explore",
                tool_name="Read",
                tool_input={"file_path": "/restricted/nested.py"},
                tool_response="nested file content",
                tool_use_id="toolu_sub_3",
                duration_ms=3,
            ),
            sidecar=a2_sidecar,
        ),
        ScenarioInput(
            stdin=_scenario_input(
                "SubagentStop",
                session_id=session_id,
                agent_id="a2",
                agent_type="Explore",
                stop_hook_active=False,
                agent_transcript_path="/restricted/a2.jsonl",
                last_assistant_message="a2 result",
            ),
            sidecar=a2_sidecar,
        ),
        ScenarioInput(
            stdin=_scenario_input(
                "PostToolUse",
                session_id=session_id,
                agent_id="a1",
                agent_type="general-purpose",
                tool_name="Agent",
                tool_input={"prompt": "spawn a2"},
                tool_response={"agent_id": "a2", "result": "done"},
                tool_use_id="toolu_sub_2",
                duration_ms=10,
            ),
            sidecar=a1_sidecar,
        ),
        ScenarioInput(
            stdin=_scenario_input(
                "SubagentStop",
                session_id=session_id,
                agent_id="a1",
                agent_type="general-purpose",
                stop_hook_active=False,
                agent_transcript_path="/restricted/a1.jsonl",
                last_assistant_message="a1 result",
            ),
            sidecar=a1_sidecar,
        ),
        ScenarioInput(
            stdin=_scenario_input(
                "PostToolUse",
                session_id=session_id,
                tool_name="Agent",
                tool_input={"prompt": "spawn a1"},
                tool_response={"agent_id": "a1", "result": "done"},
                tool_use_id="toolu_main_1",
                duration_ms=20,
            )
        ),
        ScenarioInput(
            stdin=_scenario_input(
                "Stop",
                session_id=session_id,
                stop_hook_active=False,
                last_assistant_message="main result",
            )
        ),
    ]
    return values


def _workflow_scenario() -> list[ScenarioInput]:
    session_id = "session-workflow-agent"
    sidecar = _sidecar(
        agent_type="workflow-worker",
        spawn_depth=1,
        workflow_phase="implementation",
        workflow_run_id="workflow-run-1",
    )
    return [
        ScenarioInput(
            stdin=_scenario_input(
                "SubagentStart",
                session_id=session_id,
                agent_id="workflow-a1",
                agent_type="workflow-worker",
            ),
            sidecar=sidecar,
        ),
        ScenarioInput(
            stdin=_scenario_input(
                "PreToolUse",
                session_id=session_id,
                agent_id="workflow-a1",
                agent_type="workflow-worker",
                tool_name="Bash",
                tool_input={"command": "printf workflow"},
                tool_use_id="toolu-workflow-1",
            ),
            sidecar=sidecar,
        ),
        ScenarioInput(
            stdin=_scenario_input(
                "PostToolUse",
                session_id=session_id,
                agent_id="workflow-a1",
                agent_type="workflow-worker",
                tool_name="Bash",
                tool_input={"command": "printf workflow"},
                tool_response={"output": "workflow output"},
                tool_use_id="toolu-workflow-1",
                duration_ms=5,
            ),
            sidecar=sidecar,
        ),
        ScenarioInput(
            stdin=_scenario_input(
                "SubagentStop",
                session_id=session_id,
                agent_id="workflow-a1",
                agent_type="workflow-worker",
                stop_hook_active=False,
                agent_transcript_path="/restricted/workflow-a1.jsonl",
                last_assistant_message="workflow result",
            ),
            sidecar=sidecar,
        ),
    ]


def _orphan_scenario() -> list[ScenarioInput]:
    """A subagent whose sidecar was unreadable at emit time (sidecar=None).

    Its parent is UNKNOWN, which the fold must keep distinct from the main
    thread: a null parent_agent_id alone cannot say which of the two it is.
    """

    session_id = "session-orphan-agent"
    return [
        ScenarioInput(
            stdin=_scenario_input(
                "SubagentStart",
                session_id=session_id,
                agent_id="orphan-a1",
                agent_type="general-purpose",
            ),
        ),
        ScenarioInput(
            stdin=_scenario_input(
                "PostToolUse",
                session_id=session_id,
                agent_id="orphan-a1",
                agent_type="general-purpose",
                tool_name="Bash",
                tool_input={"command": "printf orphan"},
                tool_response={"output": "orphan output"},
                tool_use_id="toolu-orphan-1",
                duration_ms=2,
            ),
        ),
    ]


def _map_sequence(
    values: list[ScenarioInput], *, start: datetime
) -> list[ModelHookCaptureResult]:
    results: list[ModelHookCaptureResult] = []
    for index, value in enumerate(values):
        results.append(
            map_hook_stdin(
                value.stdin,
                emitted_at=start + timedelta(seconds=index),
                sidecar=value.sidecar,
                claude_code_version="2.1.283",
                turn_id=value.turn_id,
                content_scrubber=mock_content_scrubber,
            )
        )
    return results


def _as_json(value: object) -> JsonValue:
    return cast("JsonValue", json.loads(json.dumps(value, default=str)))


def _event_json(event: ModelClaudeHookEvent) -> JsonValue:
    return cast("JsonValue", event.model_dump(mode="json"))


def _record_json(record: ModelHookContentRecord) -> JsonValue:
    return cast("JsonValue", record.model_dump(mode="json"))


def _pretty(value: JsonValue) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _jsonl(values: list[JsonValue]) -> str:
    return "".join(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
        for value in values
    )


def _reference_projection(
    events: list[ModelClaudeHookEvent],
) -> tuple[list[JsonValue], list[JsonValue]]:
    """Reference expectation the omnimarket production fold must reproduce.

    This is NOT a production fold. It exists so the writer's tests have an
    expected output computed from the same contract as the producer's fixtures.
    """

    source_topic = _source_topic()
    pre_tool_agents: dict[tuple[str, str], str | None] = {}
    event_rows: list[JsonValue] = []
    spans: dict[tuple[str, str], dict[str, JsonValue]] = {}

    for event in events:
        lineage = event.lineage
        if (
            event.hook_event_name is EnumClaudeHookEventName.PRE_TOOL_USE
            and lineage.tool_use_id is not None
        ):
            pre_tool_agents[(lineage.session_id, lineage.tool_use_id)] = (
                lineage.agent_id
            )

        parent_agent_id = None
        parent_resolution = "unknown"
        if lineage.parent_tool_use_id is not None:
            parent_key = (lineage.session_id, lineage.parent_tool_use_id)
            if parent_key in pre_tool_agents:
                parent_agent_id = pre_tool_agents[parent_key]
                parent_resolution = (
                    "main_thread" if parent_agent_id is None else "resolved"
                )
        elif lineage.workflow_run_id is not None:
            parent_resolution = "workflow"
        payload = event.payload.model_dump(mode="json")
        row: dict[str, JsonValue] = {
            "event_id": str(event.event_id),
            "session_id": lineage.session_id,
            "agent_id": lineage.agent_id,
            "is_subagent": lineage.is_subagent,
            "agent_type": lineage.agent_type,
            "parent_tool_use_id": lineage.parent_tool_use_id,
            "parent_agent_id": parent_agent_id,
            "workflow_run_id": lineage.workflow_run_id,
            "spawn_depth": lineage.spawn_depth,
            "hook_event_name": event.hook_event_name.value,
            "tool_use_id": lineage.tool_use_id,
            "tool_name": payload.get("tool_name"),
            "prompt_id": lineage.prompt_id,
            "turn_id": lineage.turn_id,
            "correlation_id": str(lineage.correlation_id),
            "causation_id": (
                str(lineage.causation_id) if lineage.causation_id is not None else None
            ),
            "emitted_at": event.emitted_at.isoformat().replace("+00:00", "Z"),
            "payload": _as_json(payload),
            "content_ref_ids": [
                str(ref.content_record_id) for ref in event.content_refs
            ],
            "source_topic": source_topic,
            "ingested_at": event.emitted_at.isoformat().replace("+00:00", "Z"),
        }
        event_rows.append(row)

        if lineage.agent_id is None:
            continue
        key = (lineage.session_id, lineage.agent_id)
        span = spans.get(key)
        if span is None:
            span = {
                "session_id": lineage.session_id,
                "agent_id": lineage.agent_id,
                "agent_type": lineage.agent_type,
                "parent_tool_use_id": lineage.parent_tool_use_id,
                "parent_agent_id": parent_agent_id,
                "parent_resolution": parent_resolution,
                "workflow_run_id": lineage.workflow_run_id,
                "spawn_depth": lineage.spawn_depth,
                "started_at": event.emitted_at.isoformat().replace("+00:00", "Z"),
                "stopped_at": None,
                "tool_call_count": 0,
            }
            spans[key] = span
        if event.hook_event_name is EnumClaudeHookEventName.SUBAGENT_STOP:
            span["stopped_at"] = event.emitted_at.isoformat().replace("+00:00", "Z")
        if event.hook_event_name in {
            EnumClaudeHookEventName.POST_TOOL_USE,
            EnumClaudeHookEventName.POST_TOOL_USE_FAILURE,
        }:
            count = span["tool_call_count"]
            if not isinstance(count, int):
                raise AssertionError(
                    "reference fold tool_call_count must be an integer"
                )
            span["tool_call_count"] = count + 1

    span_rows: list[JsonValue] = [spans[key] for key in sorted(spans)]
    return event_rows, span_rows


def build_outputs() -> dict[Path, str]:
    outputs: dict[Path, str] = {}
    all_stdin = _all_stdin()
    if set(all_stdin) != set(EnumClaudeHookEventName):
        raise AssertionError("fixture generator must cover every hook enum member")

    for index, name in enumerate(EnumClaudeHookEventName):
        stdin = all_stdin[name]
        result = map_hook_stdin(
            stdin,
            emitted_at=FIXED_TIME + timedelta(seconds=index),
            sidecar=None,
            claude_code_version="2.1.283",
            turn_id="turn-fixed-1",
            content_scrubber=mock_content_scrubber,
        )
        outputs[FIXTURE_ROOT / "stdin" / f"{name.value}.json"] = _pretty(stdin)
        outputs[FIXTURE_ROOT / "events" / f"{name.value}.json"] = _pretty(
            _event_json(result.event)
        )
        outputs[FIXTURE_ROOT / "content" / f"{name.value}.json"] = _pretty(
            [_record_json(record) for record in result.content_records]
        )

    scenarios = {
        "subagent_tree": _subagent_scenario(),
        "workflow_agent": _workflow_scenario(),
        "orphan_agent": _orphan_scenario(),
    }
    all_scenario_events: list[ModelClaudeHookEvent] = []
    for scenario_index, (scenario_name, inputs) in enumerate(scenarios.items()):
        results = _map_sequence(
            inputs,
            start=FIXED_TIME + timedelta(hours=scenario_index + 1),
        )
        events = [result.event for result in results]
        records = [record for result in results for record in result.content_records]
        all_scenario_events.extend(events)
        outputs[FIXTURE_ROOT / "scenarios" / f"{scenario_name}.stdin.jsonl"] = _jsonl(
            [input_.stdin for input_ in inputs]
        )
        outputs[FIXTURE_ROOT / "scenarios" / f"{scenario_name}.events.jsonl"] = _jsonl(
            [_event_json(event) for event in events]
        )
        outputs[FIXTURE_ROOT / "scenarios" / f"{scenario_name}.content.jsonl"] = _jsonl(
            [_record_json(record) for record in records]
        )

    event_rows, span_rows = _reference_projection(all_scenario_events)
    outputs[FIXTURE_ROOT / "expected_projection" / "claude_hook_events.jsonl"] = _jsonl(
        event_rows
    )
    outputs[FIXTURE_ROOT / "expected_projection" / "claude_agent_spans.jsonl"] = _jsonl(
        span_rows
    )
    return outputs


def _write(outputs: dict[Path, str]) -> None:
    for path, content in sorted(outputs.items()):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def _check(outputs: dict[Path, str]) -> int:
    changed = [
        path
        for path, expected in sorted(outputs.items())
        if not path.exists() or path.read_text(encoding="utf-8") != expected
    ]
    if changed:
        print("Claude hook capture fixtures would change:")
        for path in changed:
            print(path.relative_to(REPO_ROOT))
        return 1
    print(f"Claude hook capture fixtures are current ({len(outputs)} files).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail and name files whose deterministic output differs",
    )
    args = parser.parse_args()
    outputs = build_outputs()
    if args.check:
        return _check(outputs)
    _write(outputs)
    print(f"Wrote {len(outputs)} Claude hook capture fixture files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
