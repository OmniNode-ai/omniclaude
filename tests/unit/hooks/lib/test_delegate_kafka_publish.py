# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Integration test: every /onex:delegate invocation publishes to delegation-request topic.

DoD evidence for OMN-8746:
- classify_and_publish() calls emit_event("delegation.request", ...) with a
  valid UUID correlation_id whenever the intent is delegatable.
- No fallback to delegation_orchestrator.py prose path.
- emit_event is asserted via a mocked Kafka producer (emit_client_wrapper mock),
  NOT a function-call mock on classify_and_publish itself.
"""

from __future__ import annotations

import importlib
import sys
import uuid
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

import pytest

# Ensure delegate/_lib/ and hooks/lib/ are on sys.path
_TESTS_DIR = Path(__file__).parent
_REPO_ROOT = _TESTS_DIR.parent.parent.parent.parent
_DELEGATE_LIB = _REPO_ROOT / "plugins" / "onex" / "skills" / "delegate" / "_lib"
_HOOKS_LIB = _REPO_ROOT / "plugins" / "onex" / "hooks" / "lib"

for _p in (_DELEGATE_LIB, _HOOKS_LIB):
    if _p.exists() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


@pytest.fixture
def delegate_run_with_mock_emit() -> pytest.Generator[
    tuple[ModuleType, MagicMock], None, None
]:
    """Load delegate run.py with a mocked emit_client_wrapper.

    Saves and restores sys.modules so reload side-effects don't leak.
    """
    mock_emit = MagicMock(return_value=True)
    mock_module = MagicMock()
    mock_module.emit_event = mock_emit

    saved = dict(sys.modules)
    sys.modules["emit_client_wrapper"] = mock_module

    # Remove stale cached module so reload picks up the mock
    sys.modules.pop("run", None)

    import run as delegate_run  # noqa: PLC0415

    importlib.reload(delegate_run)

    yield delegate_run, mock_emit

    # Restore sys.modules exactly (remove any modules added by reload)
    to_remove = [k for k in sys.modules if k not in saved]
    for k in to_remove:
        del sys.modules[k]
    sys.modules.update(saved)


@pytest.fixture
def delegate_run_with_failing_emit() -> pytest.Generator[
    tuple[ModuleType, MagicMock], None, None
]:
    """Load delegate run.py with an emit_client_wrapper that returns False."""
    mock_emit = MagicMock(return_value=False)
    mock_module = MagicMock()
    mock_module.emit_event = mock_emit

    saved = dict(sys.modules)
    sys.modules["emit_client_wrapper"] = mock_module
    sys.modules.pop("run", None)

    import run as delegate_run  # noqa: PLC0415

    importlib.reload(delegate_run)

    yield delegate_run, mock_emit

    to_remove = [k for k in sys.modules if k not in saved]
    for k in to_remove:
        del sys.modules[k]
    sys.modules.update(saved)


class TestDelegateKafkaPublish:
    """Assert that classify_and_publish publishes to Kafka — no prose fallback."""

    def test_delegatable_prompt_publishes_to_delegation_request_topic(
        self, delegate_run_with_mock_emit: tuple[ModuleType, MagicMock]
    ) -> None:
        """A delegatable prompt must call emit_event with delegation.request event type."""
        delegate_run, mock_emit = delegate_run_with_mock_emit

        result = delegate_run.classify_and_publish(
            prompt="write unit tests for handler_event_emitter.py",
        )

        assert result.get("success") is True, f"Expected success, got: {result}"

        mock_emit.assert_called_once()
        call_args = mock_emit.call_args
        assert call_args is not None

        event_type = (
            call_args.args[0] if call_args.args else call_args.kwargs.get("event_type")
        )
        assert event_type == "delegation.request", (
            f"Expected event_type='delegation.request', got {event_type!r}"
        )

        envelope = (
            call_args.args[1]
            if len(call_args.args) > 1
            else call_args.kwargs.get("payload")
        )
        assert isinstance(envelope, dict), (
            f"Expected dict envelope, got {type(envelope)}"
        )

        correlation_id = envelope.get("correlation_id") or (
            envelope.get("payload", {}).get("correlation_id")
        )
        assert correlation_id is not None, "correlation_id missing from envelope"
        try:
            uuid.UUID(str(correlation_id))
        except ValueError:
            pytest.fail(f"correlation_id {correlation_id!r} is not a valid UUID")

    def test_correlation_id_is_valid_uuid(
        self, delegate_run_with_mock_emit: tuple[ModuleType, MagicMock]
    ) -> None:
        """correlation_id in published envelope must be a valid UUID4."""
        delegate_run, _mock_emit = delegate_run_with_mock_emit

        result = delegate_run.classify_and_publish(
            prompt="document the routing architecture",
        )

        assert result.get("success") is True, f"Expected success, got: {result}"
        corr = result.get("correlation_id")
        assert corr is not None
        uuid.UUID(str(corr))  # raises ValueError if not a valid UUID

    def test_explicit_correlation_id_is_threaded_through(
        self, delegate_run_with_mock_emit: tuple[ModuleType, MagicMock]
    ) -> None:
        """When correlation_id is provided, it must appear in the Kafka envelope."""
        delegate_run, mock_emit = delegate_run_with_mock_emit
        expected_corr = str(uuid.uuid4())

        result = delegate_run.classify_and_publish(
            prompt="research and explain the delegation routing flow in detail",
            correlation_id=expected_corr,
        )

        assert result.get("success") is True, f"Expected success, got: {result}"
        assert result.get("correlation_id") == expected_corr

        call_args = mock_emit.call_args
        envelope = (
            call_args.args[1]
            if len(call_args.args) > 1
            else call_args.kwargs.get("payload")
        )
        published_corr = envelope.get("correlation_id") or (
            envelope.get("payload", {}).get("correlation_id")
        )
        assert published_corr == expected_corr, (
            f"Expected correlation_id={expected_corr!r} in envelope, got {published_corr!r}"
        )

    def test_non_delegatable_intent_does_not_publish(
        self, delegate_run_with_mock_emit: tuple[ModuleType, MagicMock]
    ) -> None:
        """Non-delegatable prompts must NOT call emit_event."""
        delegate_run, mock_emit = delegate_run_with_mock_emit

        result = delegate_run.classify_and_publish(
            prompt="debug the database connection failure",
        )

        mock_emit.assert_not_called()
        assert result.get("success") is False

    def test_emit_failure_returns_error_result(
        self, delegate_run_with_failing_emit: tuple[ModuleType, MagicMock]
    ) -> None:
        """When emit_event returns falsy, result must be success=False."""
        delegate_run, _mock_emit = delegate_run_with_failing_emit

        result = delegate_run.classify_and_publish(
            prompt="write unit tests for verify_registration.py",
        )

        assert result.get("success") is False
        assert "error" in result
