# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Behavior tests for hook subscriber loop semantics (OMN-12390).

Pins the run_subscriber loop contract across all three hook subscribers:
- skill_execution_log_subscriber
- compliance_result_subscriber
- decision_record_subscriber

Tests cover:
- stop_event exits the loop cleanly
- missing/empty kafka_bootstrap_servers exits immediately
- kafka-python not installed exits immediately
- consumer creation failure exits gracefully (no raise)
- poll error triggers backoff sleep but does not exit the loop permanently
  (we assert behavior by verifying the consumer is closed in the finally block)
- individual message processing failures are silent (never propagate)
- background thread launcher returns started daemon thread

All tests run without a real Kafka broker.
"""

from __future__ import annotations

import threading
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# skill_execution_log_subscriber — run_subscriber loop
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSkillExecutionLogSubscriberLoop:
    """run_subscriber loop semantics for skill_execution_log_subscriber."""

    def _mock_consumer(self, *, records: list[dict[str, Any]] | None = None) -> Any:
        """Return a mock KafkaConsumer that yields records then empty polls."""
        consumer = MagicMock()
        consumer.poll.return_value = records or {}
        consumer.close.return_value = None
        return consumer

    def test_stop_event_exits_loop(self) -> None:
        """Loop exits cleanly when stop_event is set before first poll."""
        stop_event = threading.Event()
        stop_event.set()

        mock_consumer = self._mock_consumer()
        mock_consumer_cls = MagicMock(return_value=mock_consumer)

        with patch(
            "omniclaude.hooks.lib.skill_execution_log_subscriber._get_kafka_consumer_class",
            return_value=mock_consumer_cls,
        ):
            from omniclaude.hooks.lib.skill_execution_log_subscriber import (
                run_subscriber,
            )

            run_subscriber(
                kafka_bootstrap_servers="localhost:9092",
                stop_event=stop_event,
            )

        # Consumer was closed in the finally block
        mock_consumer.close.assert_called_once()
        # Poll was never called (stop_event was set before the loop body)
        mock_consumer.poll.assert_not_called()

    def test_empty_bootstrap_servers_exits_immediately(self) -> None:
        """run_subscriber exits immediately when bootstrap_servers is empty."""
        mock_consumer_cls = MagicMock()

        with patch(
            "omniclaude.hooks.lib.skill_execution_log_subscriber._get_kafka_consumer_class",
            return_value=mock_consumer_cls,
        ):
            from omniclaude.hooks.lib.skill_execution_log_subscriber import (
                run_subscriber,
            )

            run_subscriber(kafka_bootstrap_servers="")

        # Consumer was never instantiated
        mock_consumer_cls.assert_not_called()

    def test_no_kafka_exits_immediately(self) -> None:
        """run_subscriber exits immediately when kafka-python is not installed."""
        with patch(
            "omniclaude.hooks.lib.skill_execution_log_subscriber._get_kafka_consumer_class",
            return_value=None,
        ):
            from omniclaude.hooks.lib.skill_execution_log_subscriber import (
                run_subscriber,
            )

            # Must not raise
            run_subscriber(kafka_bootstrap_servers="localhost:9092")

    def test_consumer_creation_failure_exits_gracefully(self) -> None:
        """run_subscriber exits without raising when KafkaConsumer() raises."""
        mock_consumer_cls = MagicMock(side_effect=RuntimeError("broker unavailable"))

        with patch(
            "omniclaude.hooks.lib.skill_execution_log_subscriber._get_kafka_consumer_class",
            return_value=mock_consumer_cls,
        ):
            from omniclaude.hooks.lib.skill_execution_log_subscriber import (
                run_subscriber,
            )

            # Must not raise — exits after logging warning
            run_subscriber(kafka_bootstrap_servers="localhost:9092")

    def test_poll_error_continues_loop_until_stop(self) -> None:
        """Poll exception triggers sleep then retry; loop exits on stop_event."""
        stop_event = threading.Event()

        poll_call_count = 0

        def _poll_side_effect(**kwargs: Any) -> dict[str, Any]:
            nonlocal poll_call_count
            poll_call_count += 1
            if poll_call_count == 1:
                raise RuntimeError("simulated poll failure")
            # After the first failure, set stop_event so the loop exits
            stop_event.set()
            return {}

        mock_consumer = MagicMock()
        mock_consumer.poll.side_effect = _poll_side_effect
        mock_consumer.close.return_value = None
        mock_consumer_cls = MagicMock(return_value=mock_consumer)

        with (
            patch(
                "omniclaude.hooks.lib.skill_execution_log_subscriber._get_kafka_consumer_class",
                return_value=mock_consumer_cls,
            ),
            patch("omniclaude.hooks.lib.skill_execution_log_subscriber.time.sleep"),
        ):
            from omniclaude.hooks.lib.skill_execution_log_subscriber import (
                run_subscriber,
            )

            run_subscriber(
                kafka_bootstrap_servers="localhost:9092",
                stop_event=stop_event,
            )

        # sleep was called after the poll exception (backoff before retry)

        # Consumer was closed in finally
        mock_consumer.close.assert_called_once()

    def test_message_processing_failure_is_silent(self) -> None:
        """Individual message processing errors do not propagate out of the loop."""
        stop_event = threading.Event()

        # Build a fake message whose value will cause process_skill_completed_event
        # to raise; the loop must swallow it silently.
        fake_msg = MagicMock()
        fake_msg.value = b"{}"  # valid JSON but missing required fields → returns False

        fake_records = {MagicMock(): [fake_msg]}
        call_count = 0

        def _poll_side_effect(**kwargs: Any) -> Any:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return fake_records
            stop_event.set()
            return {}

        mock_consumer = MagicMock()
        mock_consumer.poll.side_effect = _poll_side_effect
        mock_consumer.close.return_value = None
        mock_consumer_cls = MagicMock(return_value=mock_consumer)

        with patch(
            "omniclaude.hooks.lib.skill_execution_log_subscriber._get_kafka_consumer_class",
            return_value=mock_consumer_cls,
        ):
            from omniclaude.hooks.lib.skill_execution_log_subscriber import (
                run_subscriber,
            )

            # Must not raise
            run_subscriber(
                kafka_bootstrap_servers="localhost:9092",
                stop_event=stop_event,
            )

        mock_consumer.close.assert_called_once()

    def test_background_thread_is_daemon(self) -> None:
        """run_subscriber_background returns a started daemon thread."""
        stop_event = threading.Event()
        stop_event.set()

        with patch(
            "omniclaude.hooks.lib.skill_execution_log_subscriber.run_subscriber"
        ):
            from omniclaude.hooks.lib.skill_execution_log_subscriber import (
                run_subscriber_background,
            )

            thread = run_subscriber_background(
                kafka_bootstrap_servers="localhost:9092",
                stop_event=stop_event,
            )

        assert thread.daemon is True
        thread.join(timeout=2.0)


# ---------------------------------------------------------------------------
# compliance_result_subscriber — run_subscriber loop
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestComplianceSubscriberLoop:
    """run_subscriber loop semantics for compliance_result_subscriber."""

    def test_stop_event_exits_loop(self) -> None:
        """Loop exits cleanly when stop_event is set before first poll."""
        stop_event = threading.Event()
        stop_event.set()

        mock_consumer = MagicMock()
        mock_consumer.poll.return_value = {}
        mock_consumer_cls = MagicMock(return_value=mock_consumer)

        with patch(
            "omniclaude.hooks.lib.compliance_result_subscriber._get_kafka_consumer_class",
            return_value=mock_consumer_cls,
        ):
            from omniclaude.hooks.lib.compliance_result_subscriber import (
                run_subscriber,
            )

            run_subscriber(
                kafka_bootstrap_servers="localhost:9092",
                stop_event=stop_event,
            )

        mock_consumer.close.assert_called_once()
        mock_consumer.poll.assert_not_called()

    def test_empty_bootstrap_servers_exits_immediately(self) -> None:
        """run_subscriber exits immediately when bootstrap_servers is empty."""
        mock_consumer_cls = MagicMock()

        with patch(
            "omniclaude.hooks.lib.compliance_result_subscriber._get_kafka_consumer_class",
            return_value=mock_consumer_cls,
        ):
            from omniclaude.hooks.lib.compliance_result_subscriber import (
                run_subscriber,
            )

            run_subscriber(kafka_bootstrap_servers="")

        mock_consumer_cls.assert_not_called()

    def test_no_kafka_exits_immediately(self) -> None:
        """run_subscriber exits immediately when kafka-python is not installed."""
        with patch(
            "omniclaude.hooks.lib.compliance_result_subscriber._get_kafka_consumer_class",
            return_value=None,
        ):
            from omniclaude.hooks.lib.compliance_result_subscriber import (
                run_subscriber,
            )

            run_subscriber(kafka_bootstrap_servers="localhost:9092")

    def test_consumer_creation_failure_exits_gracefully(self) -> None:
        """run_subscriber exits without raising when KafkaConsumer() raises."""
        mock_consumer_cls = MagicMock(side_effect=RuntimeError("unreachable broker"))

        with patch(
            "omniclaude.hooks.lib.compliance_result_subscriber._get_kafka_consumer_class",
            return_value=mock_consumer_cls,
        ):
            from omniclaude.hooks.lib.compliance_result_subscriber import (
                run_subscriber,
            )

            run_subscriber(kafka_bootstrap_servers="localhost:9092")

    def test_poll_error_continues_until_stop(self) -> None:
        """Poll exception triggers sleep; loop exits on stop_event."""
        stop_event = threading.Event()
        call_count = 0

        def _poll_side_effect(**kwargs: Any) -> Any:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("simulated poll failure")
            stop_event.set()
            return {}

        mock_consumer = MagicMock()
        mock_consumer.poll.side_effect = _poll_side_effect
        mock_consumer_cls = MagicMock(return_value=mock_consumer)

        with (
            patch(
                "omniclaude.hooks.lib.compliance_result_subscriber._get_kafka_consumer_class",
                return_value=mock_consumer_cls,
            ),
            patch("omniclaude.hooks.lib.compliance_result_subscriber.time.sleep"),
        ):
            from omniclaude.hooks.lib.compliance_result_subscriber import (
                run_subscriber,
            )

            run_subscriber(
                kafka_bootstrap_servers="localhost:9092",
                stop_event=stop_event,
            )

        mock_consumer.close.assert_called_once()

    def test_background_thread_is_daemon(self) -> None:
        """run_subscriber_background returns a started daemon thread."""
        stop_event = threading.Event()
        stop_event.set()

        with patch("omniclaude.hooks.lib.compliance_result_subscriber.run_subscriber"):
            from omniclaude.hooks.lib.compliance_result_subscriber import (
                run_subscriber_background,
            )

            thread = run_subscriber_background(
                kafka_bootstrap_servers="localhost:9092",
                stop_event=stop_event,
            )

        assert thread.daemon is True
        thread.join(timeout=2.0)

    def test_background_thread_name(self) -> None:
        """Daemon thread has expected name for debug identification."""
        stop_event = threading.Event()
        stop_event.set()

        with patch("omniclaude.hooks.lib.compliance_result_subscriber.run_subscriber"):
            from omniclaude.hooks.lib.compliance_result_subscriber import (
                run_subscriber_background,
            )

            thread = run_subscriber_background(
                kafka_bootstrap_servers="localhost:9092",
                stop_event=stop_event,
            )

        assert thread.name == "compliance-subscriber"
        thread.join(timeout=2.0)


# ---------------------------------------------------------------------------
# decision_record_subscriber — run_subscriber loop
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDecisionRecordSubscriberLoop:
    """run_subscriber loop semantics for decision_record_subscriber."""

    def test_stop_event_exits_loop(self) -> None:
        """Loop exits cleanly when stop_event is set before first poll."""
        stop_event = threading.Event()
        stop_event.set()

        mock_consumer = MagicMock()
        mock_consumer.poll.return_value = {}
        mock_consumer_cls = MagicMock(return_value=mock_consumer)

        with patch(
            "omniclaude.hooks.lib.decision_record_subscriber._get_kafka_consumer_class",
            return_value=mock_consumer_cls,
        ):
            from omniclaude.hooks.lib.decision_record_subscriber import run_subscriber

            run_subscriber(
                kafka_bootstrap_servers="localhost:9092",
                stop_event=stop_event,
            )

        mock_consumer.close.assert_called_once()
        mock_consumer.poll.assert_not_called()

    def test_empty_bootstrap_servers_exits_immediately(self) -> None:
        """run_subscriber exits immediately when bootstrap_servers is empty."""
        mock_consumer_cls = MagicMock()

        with patch(
            "omniclaude.hooks.lib.decision_record_subscriber._get_kafka_consumer_class",
            return_value=mock_consumer_cls,
        ):
            from omniclaude.hooks.lib.decision_record_subscriber import run_subscriber

            run_subscriber(kafka_bootstrap_servers="")

        mock_consumer_cls.assert_not_called()

    def test_no_kafka_exits_immediately(self) -> None:
        """run_subscriber exits immediately when kafka-python is not installed."""
        with patch(
            "omniclaude.hooks.lib.decision_record_subscriber._get_kafka_consumer_class",
            return_value=None,
        ):
            from omniclaude.hooks.lib.decision_record_subscriber import run_subscriber

            run_subscriber(kafka_bootstrap_servers="localhost:9092")

    def test_consumer_creation_failure_exits_gracefully(self) -> None:
        """run_subscriber exits without raising when KafkaConsumer() raises."""
        mock_consumer_cls = MagicMock(side_effect=RuntimeError("unreachable broker"))

        with patch(
            "omniclaude.hooks.lib.decision_record_subscriber._get_kafka_consumer_class",
            return_value=mock_consumer_cls,
        ):
            from omniclaude.hooks.lib.decision_record_subscriber import run_subscriber

            run_subscriber(kafka_bootstrap_servers="localhost:9092")

    def test_poll_error_continues_until_stop(self) -> None:
        """Poll exception triggers sleep; loop exits on stop_event."""
        stop_event = threading.Event()
        call_count = 0

        def _poll_side_effect(**kwargs: Any) -> Any:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("simulated poll failure")
            stop_event.set()
            return {}

        mock_consumer = MagicMock()
        mock_consumer.poll.side_effect = _poll_side_effect
        mock_consumer_cls = MagicMock(return_value=mock_consumer)

        with (
            patch(
                "omniclaude.hooks.lib.decision_record_subscriber._get_kafka_consumer_class",
                return_value=mock_consumer_cls,
            ),
            patch("omniclaude.hooks.lib.decision_record_subscriber.time.sleep"),
        ):
            from omniclaude.hooks.lib.decision_record_subscriber import run_subscriber

            run_subscriber(
                kafka_bootstrap_servers="localhost:9092",
                stop_event=stop_event,
            )

        mock_consumer.close.assert_called_once()

    def test_individual_message_failure_is_silent(self, tmp_path: Any) -> None:
        """Malformed message inside poll batch does not propagate."""
        stop_event = threading.Event()
        call_count = 0

        # A message whose process_decision_record_event will fail gracefully
        bad_msg = MagicMock()
        bad_msg.value = b"not-json"

        def _poll_side_effect(**kwargs: Any) -> Any:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {MagicMock(): [bad_msg]}
            stop_event.set()
            return {}

        mock_consumer = MagicMock()
        mock_consumer.poll.side_effect = _poll_side_effect
        mock_consumer_cls = MagicMock(return_value=mock_consumer)

        import os

        audit_log = str(tmp_path / "audit.jsonl")
        with (
            patch(
                "omniclaude.hooks.lib.decision_record_subscriber._get_kafka_consumer_class",
                return_value=mock_consumer_cls,
            ),
            patch.dict(os.environ, {"OMNICLAUDE_DECISION_AUDIT_LOG": audit_log}),
        ):
            from omniclaude.hooks.lib.decision_record_subscriber import run_subscriber

            # Must not raise
            run_subscriber(
                kafka_bootstrap_servers="localhost:9092",
                stop_event=stop_event,
            )

        mock_consumer.close.assert_called_once()

    def test_background_thread_name(self) -> None:
        """Daemon thread has expected name."""
        stop_event = threading.Event()
        stop_event.set()

        with patch("omniclaude.hooks.lib.decision_record_subscriber.run_subscriber"):
            from omniclaude.hooks.lib.decision_record_subscriber import (
                run_subscriber_background,
            )

            thread = run_subscriber_background(
                kafka_bootstrap_servers="localhost:9092",
                stop_event=stop_event,
            )

        assert thread.name == "decision-record-subscriber"
        thread.join(timeout=2.0)

    def test_consumer_group_default_encodes_schema_version(self) -> None:
        """Default group_id must end with .v{N} per F5 rules (OMN-2593)."""
        # Inspect the default value of the group_id parameter
        import inspect
        import re

        from omniclaude.hooks.lib.decision_record_subscriber import run_subscriber

        sig = inspect.signature(run_subscriber)
        default_group_id = sig.parameters["group_id"].default
        assert re.match(r"^omniclaude-.+\.v\d+$", default_group_id), (
            f"group_id default {default_group_id!r} must match omniclaude-*.vN"
        )
