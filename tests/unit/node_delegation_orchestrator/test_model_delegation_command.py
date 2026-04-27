# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for ModelDelegationCommand — OMN-10136."""

from pathlib import Path

import pytest
from pydantic import ValidationError


def test_delegation_command_has_recipient_field() -> None:
    from omniclaude.nodes.node_delegation_orchestrator.models.model_delegation_command import (
        ModelDelegationCommand,
    )

    cmd = ModelDelegationCommand(prompt="do it", recipient="claude")
    assert cmd.recipient == "claude"


def test_delegation_command_wait_for_result_default_false() -> None:
    from omniclaude.nodes.node_delegation_orchestrator.models.model_delegation_command import (
        ModelDelegationCommand,
    )

    cmd = ModelDelegationCommand(prompt="do it")
    assert cmd.wait_for_result is False


def test_delegation_command_working_directory_default_none() -> None:
    from omniclaude.nodes.node_delegation_orchestrator.models.model_delegation_command import (
        ModelDelegationCommand,
    )

    cmd = ModelDelegationCommand(prompt="do it")
    assert cmd.working_directory is None


def test_delegation_command_recipient_invalid_value_raises() -> None:
    from omniclaude.nodes.node_delegation_orchestrator.models.model_delegation_command import (
        ModelDelegationCommand,
    )

    with pytest.raises(ValidationError):
        ModelDelegationCommand(prompt="do it", recipient="gpt-5")


def test_delegation_command_auto_recipient_rejects_working_directory() -> None:
    from omniclaude.nodes.node_delegation_orchestrator.models.model_delegation_command import (
        ModelDelegationCommand,
    )

    with pytest.raises(ValidationError):
        ModelDelegationCommand(
            prompt="do it", recipient="auto", working_directory=Path("/tmp")
        )


def test_delegation_command_non_auto_accepts_working_directory() -> None:
    from omniclaude.nodes.node_delegation_orchestrator.models.model_delegation_command import (
        ModelDelegationCommand,
    )

    cmd = ModelDelegationCommand(
        prompt="do it", recipient="claude", working_directory=Path("/tmp/work")
    )
    assert cmd.working_directory == Path("/tmp/work")


def test_delegation_command_codex_sandbox_mode_default_none() -> None:
    from omniclaude.nodes.node_delegation_orchestrator.models.model_delegation_command import (
        ModelDelegationCommand,
    )

    cmd = ModelDelegationCommand(prompt="do it")
    assert cmd.codex_sandbox_mode is None


def test_delegation_command_codex_sandbox_mode_valid_values() -> None:
    from omniclaude.nodes.node_delegation_orchestrator.models.model_delegation_command import (
        ModelDelegationCommand,
    )

    for mode in ("read-only", "workspace-write", "danger-full-access"):
        cmd = ModelDelegationCommand(
            prompt="do it", recipient="codex", codex_sandbox_mode=mode
        )
        assert cmd.codex_sandbox_mode == mode


def test_delegation_command_existing_fields_unchanged() -> None:
    from omniclaude.nodes.node_delegation_orchestrator.models.model_delegation_command import (
        ModelDelegationCommand,
    )

    cmd = ModelDelegationCommand(
        prompt="hello",
        correlation_id="corr-123",
        session_id="sess-456",
        prompt_length=5,
    )
    assert cmd.prompt == "hello"
    assert cmd.correlation_id == "corr-123"
    assert cmd.session_id == "sess-456"
    assert cmd.prompt_length == 5
    assert cmd.recipient == "auto"
    assert cmd.wait_for_result is False
    assert cmd.working_directory is None
    assert cmd.codex_sandbox_mode is None
