# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for lifecycle module — on_start / on_shutdown / start_workers.

Ticket: OMN-7659 - Extract PluginClaude custom init into lifecycle modules.

All tests mock external dependencies (Kafka, publisher, backends) to ensure
they run without infrastructure.
"""

from __future__ import annotations

import threading
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from omniclaude.runtime.lifecycle import (
    LifecycleState,
    ModelLifecycleDiagnostic,
    _WorkerDescriptor,
    on_shutdown,
    on_start,
    start_workers,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# LifecycleState
# ---------------------------------------------------------------------------


class TestLifecycleState:
    def test_initial_state(self):
        state = LifecycleState()
        assert state.publisher is None
        assert state.vllm_backend is None
        assert not state.shutdown_in_progress
        assert state.worker_health() == {}
        assert state.all_workers_alive() is True

    def test_worker_health_reflects_threads(self):
        state = LifecycleState()
        mock_thread = MagicMock()
        mock_thread.is_alive.return_value = True
        state.workers["test"] = _WorkerDescriptor(
            name="test", thread=mock_thread, stop_event=threading.Event()
        )
        assert state.worker_health() == {"test": True}
        assert state.all_workers_alive() is True

        mock_thread.is_alive.return_value = False
        assert state.worker_health() == {"test": False}
        assert state.all_workers_alive() is False


# ---------------------------------------------------------------------------
# _WorkerDescriptor
# ---------------------------------------------------------------------------


class TestWorkerDescriptor:
    def test_is_alive_false_when_no_thread(self):
        w = _WorkerDescriptor(name="test")
        assert not w.is_alive

    def test_is_alive_delegates_to_thread(self):
        mock_thread = MagicMock()
        mock_thread.is_alive.return_value = True
        w = _WorkerDescriptor(name="test", thread=mock_thread)
        assert w.is_alive

    def test_stop_sets_event_and_clears_refs(self):
        stop_event = MagicMock()
        w = _WorkerDescriptor(
            name="test", thread=MagicMock(), stop_event=stop_event
        )
        w.stop()
        stop_event.set.assert_called_once()
        assert w.stop_event is None
        assert w.thread is None

    def test_stop_safe_without_event(self):
        w = _WorkerDescriptor(name="test", thread=MagicMock())
        w.stop()  # should not raise
        assert w.thread is None


# ---------------------------------------------------------------------------
# ModelLifecycleDiagnostic
# ---------------------------------------------------------------------------


class TestModelLifecycleDiagnostic:
    def test_frozen(self):
        d = ModelLifecycleDiagnostic(
            component="test", operation="init", success=True
        )
        with pytest.raises(AttributeError):
            d.component = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# on_start
# ---------------------------------------------------------------------------


class TestOnStart:
    @pytest.mark.asyncio
    async def test_starts_publisher_and_backend(self):
        state = LifecycleState()
        mock_publisher = AsyncMock()
        mock_publisher.start = AsyncMock()

        with patch.dict(
            "sys.modules",
            {
                "omniclaude.publisher.publisher_config": MagicMock(
                    PublisherConfig=MagicMock(return_value=MagicMock())
                ),
                "omniclaude.publisher.embedded_publisher": MagicMock(
                    EmbeddedEventPublisher=MagicMock(return_value=mock_publisher)
                ),
                "omniclaude.config.model_local_llm_config": MagicMock(
                    LocalLlmEndpointRegistry=MagicMock(return_value=MagicMock())
                ),
                "omniclaude.nodes.node_local_llm_inference_effect.backends": MagicMock(
                    VllmInferenceBackend=MagicMock(return_value=MagicMock())
                ),
            },
        ):
            diagnostics = await on_start(state, "localhost:9092")

        assert state.publisher is not None
        mock_publisher.start.assert_awaited_once()
        # Should have publisher + backend diagnostics
        assert len(diagnostics) >= 1
        assert diagnostics[0].success is True
        assert diagnostics[0].component == "EmbeddedEventPublisher"

    @pytest.mark.asyncio
    async def test_publisher_failure_returns_failed_diagnostic(self):
        state = LifecycleState()
        mock_publisher = AsyncMock()
        mock_publisher.start = AsyncMock(side_effect=RuntimeError("Kafka down"))
        mock_publisher.stop = AsyncMock()

        with patch.dict(
            "sys.modules",
            {
                "omniclaude.publisher.publisher_config": MagicMock(
                    PublisherConfig=MagicMock(return_value=MagicMock())
                ),
                "omniclaude.publisher.embedded_publisher": MagicMock(
                    EmbeddedEventPublisher=MagicMock(return_value=mock_publisher)
                ),
            },
        ):
            diagnostics = await on_start(state, "localhost:9092")

        assert diagnostics[0].success is False
        assert "Kafka down" in (diagnostics[0].error or "")
        assert state.publisher is None

    @pytest.mark.asyncio
    async def test_backend_failure_is_non_fatal(self):
        state = LifecycleState()
        mock_publisher = AsyncMock()
        mock_publisher.start = AsyncMock()

        with patch.dict(
            "sys.modules",
            {
                "omniclaude.publisher.publisher_config": MagicMock(
                    PublisherConfig=MagicMock(return_value=MagicMock())
                ),
                "omniclaude.publisher.embedded_publisher": MagicMock(
                    EmbeddedEventPublisher=MagicMock(return_value=mock_publisher)
                ),
                "omniclaude.config.model_local_llm_config": MagicMock(
                    LocalLlmEndpointRegistry=MagicMock(
                        side_effect=RuntimeError("registry fail")
                    )
                ),
            },
        ):
            diagnostics = await on_start(state, "localhost:9092")

        # Publisher should succeed, backend should fail
        assert diagnostics[0].success is True
        assert any(
            not d.success and d.component == "VllmInferenceBackend"
            for d in diagnostics
        )
        assert state.publisher is not None
        assert state.vllm_backend is None


# ---------------------------------------------------------------------------
# start_workers
# ---------------------------------------------------------------------------


class TestStartWorkers:
    @pytest.mark.asyncio
    async def test_starts_both_subscriber_threads(self):
        state = LifecycleState()
        mock_compliance_thread = MagicMock()
        mock_compliance_thread.is_alive.return_value = True
        mock_compliance_thread.name = ""
        mock_decision_thread = MagicMock()
        mock_decision_thread.is_alive.return_value = True
        mock_decision_thread.name = ""

        with patch.dict(
            "sys.modules",
            {
                "omniclaude.hooks.lib.compliance_result_subscriber": MagicMock(
                    run_subscriber_background=MagicMock(
                        return_value=mock_compliance_thread
                    )
                ),
                "omniclaude.hooks.lib.decision_record_subscriber": MagicMock(
                    run_subscriber_background=MagicMock(
                        return_value=mock_decision_thread
                    )
                ),
                "omniclaude.runtime.introspection": MagicMock(
                    SkillNodeIntrospectionProxy=MagicMock(
                        return_value=MagicMock(
                            publish_all=AsyncMock(return_value=0)
                        )
                    )
                ),
            },
        ):
            diagnostics = await start_workers(state, "localhost:9092")

        assert "compliance-subscriber" in state.workers
        assert "decision-record-subscriber" in state.workers
        success_components = [d.component for d in diagnostics if d.success]
        assert "compliance-subscriber" in success_components
        assert "decision-record-subscriber" in success_components

    @pytest.mark.asyncio
    async def test_skipped_during_shutdown(self):
        state = LifecycleState()
        state.shutdown_in_progress = True

        diagnostics = await start_workers(state, "localhost:9092")

        assert len(diagnostics) == 1
        assert not diagnostics[0].success
        assert "shutdown" in (diagnostics[0].error or "")

    @pytest.mark.asyncio
    async def test_idempotent_when_all_alive(self):
        state = LifecycleState()
        mock_thread = MagicMock()
        mock_thread.is_alive.return_value = True
        state.workers["compliance-subscriber"] = _WorkerDescriptor(
            name="compliance-subscriber", thread=mock_thread
        )
        state.workers["decision-record-subscriber"] = _WorkerDescriptor(
            name="decision-record-subscriber", thread=mock_thread
        )

        diagnostics = await start_workers(state, "localhost:9092")

        assert len(diagnostics) == 1
        assert diagnostics[0].success is True
        assert "already running" in diagnostics[0].message.lower()


# ---------------------------------------------------------------------------
# on_shutdown
# ---------------------------------------------------------------------------


class TestOnShutdown:
    @pytest.mark.asyncio
    async def test_stops_workers_and_publisher(self):
        state = LifecycleState()
        mock_publisher = AsyncMock()
        mock_publisher.stop = AsyncMock()
        state.publisher = mock_publisher

        stop_event = MagicMock()
        state.workers["compliance-subscriber"] = _WorkerDescriptor(
            name="compliance-subscriber",
            thread=MagicMock(),
            stop_event=stop_event,
        )

        diagnostics = await on_shutdown(state)

        stop_event.set.assert_called_once()
        mock_publisher.stop.assert_awaited_once()
        assert state.publisher is None
        assert len(state.workers) == 0
        assert not state.shutdown_in_progress

    @pytest.mark.asyncio
    async def test_no_op_when_already_shutting_down(self):
        state = LifecycleState()
        state.shutdown_in_progress = True

        diagnostics = await on_shutdown(state)

        assert diagnostics == []

    @pytest.mark.asyncio
    async def test_publisher_stop_failure_reported(self):
        state = LifecycleState()
        mock_publisher = AsyncMock()
        mock_publisher.stop = AsyncMock(side_effect=RuntimeError("stop fail"))
        state.publisher = mock_publisher

        diagnostics = await on_shutdown(state)

        failed = [d for d in diagnostics if not d.success]
        assert len(failed) == 1
        assert "stop fail" in (failed[0].error or "")
        # References still cleared
        assert state.publisher is None
        assert not state.shutdown_in_progress

    @pytest.mark.asyncio
    async def test_vllm_backend_closed(self):
        state = LifecycleState()
        mock_backend = AsyncMock()
        mock_backend.aclose = AsyncMock()
        state.vllm_backend = mock_backend

        await on_shutdown(state)

        mock_backend.aclose.assert_awaited_once()
        assert state.vllm_backend is None

    @pytest.mark.asyncio
    async def test_resets_shutdown_flag_on_error(self):
        state = LifecycleState()
        mock_publisher = AsyncMock()
        mock_publisher.stop = AsyncMock(side_effect=RuntimeError("boom"))
        state.publisher = mock_publisher

        await on_shutdown(state)

        assert not state.shutdown_in_progress
