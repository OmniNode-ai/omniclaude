# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT


def test_invocation_result_success_computed_from_exit_code() -> None:
    from omniclaude.nodes.node_delegation_orchestrator.models.model_cross_cli_invocation_result import (
        ModelCrossCLIInvocationResult,
    )

    r = ModelCrossCLIInvocationResult(
        correlation_id="c1",
        recipient="claude",
        stdout="hello",
        stderr="",
        exit_code=0,
        files_modified=[],
        runtime_seconds=1.2,
        working_directory="/tmp/work",
    )
    assert r.success is True
    assert r.exit_code == 0
    assert r.runtime_seconds == 1.2


def test_invocation_result_success_false_when_exit_code_nonzero() -> None:
    from omniclaude.nodes.node_delegation_orchestrator.models.model_cross_cli_invocation_result import (
        ModelCrossCLIInvocationResult,
    )

    r = ModelCrossCLIInvocationResult(
        correlation_id="c2",
        recipient="codex",
        stdout="",
        exit_code=1,
    )
    assert r.success is False


def test_invocation_result_success_false_when_stdout_empty() -> None:
    from omniclaude.nodes.node_delegation_orchestrator.models.model_cross_cli_invocation_result import (
        ModelCrossCLIInvocationResult,
    )

    r = ModelCrossCLIInvocationResult(
        correlation_id="c3",
        recipient="opencode",
        stdout="",
        exit_code=0,
    )
    assert r.success is False


def test_invocation_result_defaults() -> None:
    from omniclaude.nodes.node_delegation_orchestrator.models.model_cross_cli_invocation_result import (
        ModelCrossCLIInvocationResult,
    )

    r = ModelCrossCLIInvocationResult(
        correlation_id="c4",
        recipient="codex",
        stdout="answer",
        exit_code=0,
    )
    assert r.files_modified == []
    assert r.working_directory is None
    assert r.stderr == ""
    assert r.runtime_seconds == 0.0
