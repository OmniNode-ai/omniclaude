# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for HandlerCrossCLIInvoker — OMN-10135 Task 4."""

from __future__ import annotations

import json


def test_invoker_builds_claude_args_correctly() -> None:
    from omniclaude.nodes.node_delegation_orchestrator.handlers.handler_cross_cli_invoker import (
        HandlerCrossCLIInvoker,
    )

    invoker = HandlerCrossCLIInvoker()
    args = invoker._build_claude_args("hello")
    assert args[0] == "claude"
    assert "-p" in args
    assert "--output-format" in args
    assert "json" in args
    assert "--bare" not in args


def test_invoker_builds_opencode_args_correctly() -> None:
    from omniclaude.nodes.node_delegation_orchestrator.handlers.handler_cross_cli_invoker import (
        HandlerCrossCLIInvoker,
    )

    invoker = HandlerCrossCLIInvoker()
    args = invoker._build_opencode_args("hello", working_directory="/tmp/work")
    assert args[0] == "opencode"
    assert "run" in args
    assert "--format" in args and "json" in args
    assert "--pure" in args
    assert "--dir" in args and "/tmp/work" in args


def test_invoker_builds_codex_workspace_write_for_code_tasks() -> None:
    from omniclaude.nodes.node_delegation_orchestrator.handlers.handler_cross_cli_invoker import (
        HandlerCrossCLIInvoker,
    )

    invoker = HandlerCrossCLIInvoker()
    args = invoker._build_codex_args(
        "write code",
        task_type="code_generation",
        working_directory="/tmp/work",
        sandbox_override=None,
    )
    assert "-s" in args and "workspace-write" in args


def test_invoker_builds_codex_read_only_for_review_tasks() -> None:
    from omniclaude.nodes.node_delegation_orchestrator.handlers.handler_cross_cli_invoker import (
        HandlerCrossCLIInvoker,
    )

    invoker = HandlerCrossCLIInvoker()
    args = invoker._build_codex_args(
        "review this",
        task_type="code_review",
        working_directory="/tmp/work",
        sandbox_override=None,
    )
    assert "-s" in args and "read-only" in args


def test_invoker_respects_explicit_sandbox_override() -> None:
    from omniclaude.nodes.node_delegation_orchestrator.handlers.handler_cross_cli_invoker import (
        HandlerCrossCLIInvoker,
    )

    invoker = HandlerCrossCLIInvoker()
    args = invoker._build_codex_args(
        "do something",
        task_type="research",
        working_directory="/tmp",
        sandbox_override="workspace-write",
    )
    assert "workspace-write" in args


def test_invoker_infers_codex_task_type_from_structured_field_only() -> None:
    from omniclaude.nodes.node_delegation_orchestrator.handlers.handler_cross_cli_invoker import (
        _infer_task_type,
    )

    assert _infer_task_type("code_generation") == "code_generation"
    assert _infer_task_type("refactor") == "code_generation"
    assert _infer_task_type("test") == "code_generation"
    assert _infer_task_type("document") == "code_generation"
    assert _infer_task_type("code_review") == "research"
    assert _infer_task_type("research") == "research"
    assert _infer_task_type(None) == "research"


def test_invoker_parses_claude_json_output() -> None:
    from omniclaude.nodes.node_delegation_orchestrator.handlers.handler_cross_cli_invoker import (
        HandlerCrossCLIInvoker,
    )

    raw = json.dumps(
        {"type": "result", "result": "done", "duration_ms": 2000, "is_error": False}
    )
    invoker = HandlerCrossCLIInvoker()
    parsed = invoker._parse_claude_output(
        raw,
        stderr="warning",
        exit_code=0,
        runtime_seconds=2.0,
        correlation_id="c1",
        working_directory="/tmp",
    )
    assert parsed.stdout == "done"
    assert parsed.stderr == "warning"
    assert parsed.runtime_seconds == 2.0
    assert parsed.success is True


def test_invoker_parses_opencode_jsonl_output() -> None:
    from omniclaude.nodes.node_delegation_orchestrator.handlers.handler_cross_cli_invoker import (
        HandlerCrossCLIInvoker,
    )

    lines = [
        json.dumps({"type": "step_start", "timestamp": 1000}),
        json.dumps(
            {
                "type": "text",
                "timestamp": 2000,
                "part": {"type": "text", "text": "hello world"},
            }
        ),
    ]
    invoker = HandlerCrossCLIInvoker()
    parsed = invoker._parse_opencode_output(
        "\n".join(lines),
        stderr="",
        exit_code=0,
        runtime_seconds=1.25,
        correlation_id="c1",
        working_directory="/tmp",
    )
    assert "hello world" in parsed.stdout
    assert parsed.runtime_seconds == 1.25


def test_invoker_parses_codex_jsonl_output() -> None:
    from omniclaude.nodes.node_delegation_orchestrator.handlers.handler_cross_cli_invoker import (
        HandlerCrossCLIInvoker,
    )

    lines = [
        json.dumps({"type": "thread.started", "thread_id": "t1"}),
        json.dumps(
            {
                "type": "item.completed",
                "item": {"id": "i1", "type": "agent_message", "text": "answer"},
            }
        ),
    ]
    invoker = HandlerCrossCLIInvoker()
    parsed = invoker._parse_codex_output(
        "\n".join(lines),
        stderr="diagnostic",
        exit_code=0,
        runtime_seconds=1.0,
        correlation_id="c1",
        working_directory="/tmp",
    )
    assert "answer" in parsed.stdout
    assert parsed.stderr == "diagnostic"
