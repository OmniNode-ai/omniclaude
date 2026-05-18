# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for handle_cross_cli_dispatch — OMN-10135 Task 5."""

from __future__ import annotations

import inspect
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def test_cross_cli_dispatch_routes_to_invoker() -> None:
    from omniclaude.nodes.node_delegation_orchestrator.handlers.handler_delegation_dispatch import (
        handle_cross_cli_dispatch,
    )
    from omniclaude.nodes.node_delegation_orchestrator.models.model_cross_cli_invocation_result import (
        ModelCrossCLIInvocationResult,
    )
    from omniclaude.nodes.node_delegation_orchestrator.models.model_delegation_command import (
        ModelDelegationCommand,
    )

    cmd = ModelDelegationCommand(
        prompt="do something",
        recipient="claude",
        working_directory=Path("/tmp/w"),
        correlation_id="c1",
    )
    with patch(
        "omniclaude.nodes.node_delegation_orchestrator.handlers.handler_cross_cli_invoker.HandlerCrossCLIInvoker"
    ) as MockInvoker:
        mock_result = MagicMock(spec=ModelCrossCLIInvocationResult)
        MockInvoker.return_value.invoke.return_value = mock_result
        result = handle_cross_cli_dispatch(cmd)
    assert result is mock_result


def test_cross_cli_dispatch_raises_on_auto_recipient() -> None:
    from omniclaude.nodes.node_delegation_orchestrator.handlers.handler_delegation_dispatch import (
        handle_cross_cli_dispatch,
    )
    from omniclaude.nodes.node_delegation_orchestrator.models.model_delegation_command import (
        ModelDelegationCommand,
    )

    cmd = ModelDelegationCommand(prompt="x", recipient="auto")
    with pytest.raises(ValueError, match="recipient"):
        handle_cross_cli_dispatch(cmd)


def test_original_handle_delegation_dispatch_signature_unchanged() -> None:
    from omniclaude.nodes.node_delegation_orchestrator.handlers.handler_delegation_dispatch import (
        handle_delegation_dispatch,
    )

    hints = inspect.get_annotations(handle_delegation_dispatch)
    return_hint = hints.get("return")
    # Under `from __future__ import annotations`, annotations are strings
    name = getattr(return_hint, "__name__", return_hint)
    assert name == "ModelDelegationDispatchResult"
