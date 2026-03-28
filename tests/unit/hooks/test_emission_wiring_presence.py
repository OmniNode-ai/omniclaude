#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Emission wiring presence tests — verify every emitter module has active emit calls.

Pattern: omniintelligence PR #487 ``TestEmissionWiringPresence`` adapted for omniclaude.

Two test categories per emitter module:

1. **Source-inspection tests** (``TestEmissionWiringPresence``):
   Read the Python source of each emitter module and assert that the expected
   ``emit_event`` call string is present.  This catches accidental deletion or
   commenting-out of emit calls.

2. **Mock-bus unit tests** (``TestEmitterMockBus*``):
   For each top-level emit helper in ``pipeline_event_emitters.py``, patch
   ``_get_emit_fn`` and verify the helper calls it with the correct event type.

Ticket: OMN-6866
"""

from __future__ import annotations

from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_HOOKS_LIB = Path(__file__).resolve().parents[3] / "plugins" / "onex" / "hooks" / "lib"


def _read_source(module_filename: str) -> str:
    """Return the source text of a hooks/lib module."""
    path = _HOOKS_LIB / module_filename
    assert path.exists(), f"Module not found: {path}"
    return path.read_text()


# ============================================================================
# Type 1: Source-inspection tests — verify emit_event call exists in source
# ============================================================================


@pytest.mark.unit
class TestEmissionWiringPresence:
    """Verify every emitter module contains an active emit_event() call.

    Each test reads the raw source of the module and checks for the expected
    emit call string.  This is intentionally a *textual* check — it catches
    cases where the call is commented out or removed, which import-based
    tests would miss.
    """

    # -- pipeline_event_emitters.py ------------------------------------------

    @pytest.mark.parametrize(
        "event_type",
        [
            "epic.run.updated",
            "pr.watch.updated",
            "gate.decision",
            "budget.cap.hit",
            "circuit.breaker.tripped",
            "hostile.reviewer.completed",
            "plan.review.completed",
            "dod.sweep.completed",
        ],
    )
    def test_pipeline_event_emitters_has_emit_call(self, event_type: str) -> None:
        source = _read_source("pipeline_event_emitters.py")
        assert f'emit_fn("{event_type}"' in source, (
            f"pipeline_event_emitters.py missing emit_fn call for '{event_type}'"
        )

    # -- agent_status_emitter.py ---------------------------------------------

    def test_agent_status_emitter_has_emit_call(self) -> None:
        source = _read_source("agent_status_emitter.py")
        assert 'emit_event("agent.status"' in source

    # -- correlation_trace_emitter.py ----------------------------------------

    def test_correlation_trace_emitter_has_emit_call(self) -> None:
        source = _read_source("correlation_trace_emitter.py")
        assert 'emit_event("correlation.trace.span"' in source

    # -- enrichment_observability_emitter.py ---------------------------------

    def test_enrichment_observability_emitter_has_emit_call(self) -> None:
        source = _read_source("enrichment_observability_emitter.py")
        # Uses _EVENT_TYPE constant, but also check the constant value
        assert '_EVENT_TYPE = "context.enrichment"' in source
        assert "emit_event(_EVENT_TYPE" in source

    # -- extraction_event_emitter.py -----------------------------------------

    @pytest.mark.parametrize(
        "event_type",
        [
            "context.utilization",
            "injection.recorded",
            "agent.match",
            "latency.breakdown",
        ],
    )
    def test_extraction_event_emitter_has_emit_call(self, event_type: str) -> None:
        source = _read_source("extraction_event_emitter.py")
        assert f'_emit_event("{event_type}"' in source, (
            f"extraction_event_emitter.py missing _emit_event call for '{event_type}'"
        )

    # -- route_via_events_wrapper.py -----------------------------------------

    @pytest.mark.parametrize(
        "event_type",
        [
            "routing.decision",
            "llm.routing.decision",
            "llm.routing.fallback",
        ],
    )
    def test_route_via_events_wrapper_has_emit_call(self, event_type: str) -> None:
        source = _read_source("route_via_events_wrapper.py")
        assert f'event_type="{event_type}"' in source, (
            f"route_via_events_wrapper.py missing emit call for '{event_type}'"
        )

    # -- pattern_enforcement.py ----------------------------------------------

    @pytest.mark.parametrize(
        "event_type",
        [
            "pattern.enforcement",
            "compliance.evaluate",
        ],
    )
    def test_pattern_enforcement_has_emit_call(self, event_type: str) -> None:
        source = _read_source("pattern_enforcement.py")
        assert f'emit_event("{event_type}"' in source, (
            f"pattern_enforcement.py missing emit_event call for '{event_type}'"
        )

    # -- metrics_emitter.py --------------------------------------------------

    def test_metrics_emitter_has_emit_call(self) -> None:
        source = _read_source("metrics_emitter.py")
        assert 'emit_event("phase.metrics"' in source

    # -- friction_observer_adapter.py ----------------------------------------

    def test_friction_observer_adapter_has_emit_call(self) -> None:
        source = _read_source("friction_observer_adapter.py")
        assert "emit_event(" in source

    # -- shadow_validation.py ------------------------------------------------

    def test_shadow_validation_has_emit_call(self) -> None:
        source = _read_source("shadow_validation.py")
        assert "emit_event(" in source

    # -- commit_intent_binder.py ---------------------------------------------

    def test_commit_intent_binder_has_emit_call(self) -> None:
        source = _read_source("commit_intent_binder.py")
        assert 'emit_event("intent.commit.bound"' in source

    # -- static_context_snapshot.py ------------------------------------------

    def test_static_context_snapshot_has_emit_call(self) -> None:
        source = _read_source("static_context_snapshot.py")
        assert 'emit_event("static.context.edit.detected"' in source

    # -- delegation_orchestrator.py ------------------------------------------

    def test_delegation_orchestrator_has_emit_call(self) -> None:
        source = _read_source("delegation_orchestrator.py")
        assert "emit_event(" in source

    # -- bash_guard.py -------------------------------------------------------

    def test_bash_guard_has_emit_call(self) -> None:
        source = _read_source("bash_guard.py")
        assert 'emit_event("validator.catch"' in source

    # -- pipeline_slack_notifier.py ------------------------------------------

    def test_pipeline_slack_notifier_has_emit_call(self) -> None:
        source = _read_source("pipeline_slack_notifier.py")
        assert "emit_event(" in source


# ============================================================================
# Type 2: Mock-bus unit tests — verify emit helpers call emit_fn correctly
# ============================================================================


@pytest.mark.unit
class TestEmitterMockBusPipelineEmitters:
    """Verify each pipeline_event_emitters helper calls emit_fn with correct event type."""

    @pytest.fixture(autouse=True)
    def _patch_emit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from unittest.mock import MagicMock

        self.mock_emit = MagicMock(return_value=True)
        monkeypatch.setattr(
            "plugins.onex.hooks.lib.pipeline_event_emitters._get_emit_fn",
            lambda: self.mock_emit,
        )

    def test_emit_epic_run_updated(self) -> None:
        from plugins.onex.hooks.lib.pipeline_event_emitters import (
            emit_epic_run_updated,
        )

        emit_epic_run_updated(
            run_id="r1", epic_id="E1", status="completed", correlation_id="c1"
        )
        self.mock_emit.assert_called_once()
        event_type, payload = self.mock_emit.call_args[0]
        assert event_type == "epic.run.updated"
        assert payload["run_id"] == "r1"
        assert "event_id" in payload

    def test_emit_pr_watch_updated(self) -> None:
        from plugins.onex.hooks.lib.pipeline_event_emitters import (
            emit_pr_watch_updated,
        )

        emit_pr_watch_updated(
            run_id="r2",
            pr_number=42,
            repo="OmniNode-ai/omniclaude",
            ticket_id="OMN-1",
            status="approved",
            correlation_id="c2",
        )
        self.mock_emit.assert_called_once()
        event_type, payload = self.mock_emit.call_args[0]
        assert event_type == "pr.watch.updated"
        assert payload["pr_number"] == 42

    def test_emit_gate_decision(self) -> None:
        from plugins.onex.hooks.lib.pipeline_event_emitters import (
            emit_gate_decision,
        )

        emit_gate_decision(
            gate_id="g1",
            decision="ACCEPTED",
            ticket_id="OMN-1",
            correlation_id="c3",
        )
        self.mock_emit.assert_called_once()
        event_type, payload = self.mock_emit.call_args[0]
        assert event_type == "gate.decision"
        assert payload["decision"] == "ACCEPTED"

    def test_emit_budget_cap_hit(self) -> None:
        from plugins.onex.hooks.lib.pipeline_event_emitters import (
            emit_budget_cap_hit,
        )

        emit_budget_cap_hit(
            run_id="r3",
            tokens_used=50000,
            tokens_budget=40000,
            correlation_id="c4",
        )
        self.mock_emit.assert_called_once()
        event_type, payload = self.mock_emit.call_args[0]
        assert event_type == "budget.cap.hit"
        assert payload["tokens_used"] == 50000

    def test_emit_circuit_breaker_tripped(self) -> None:
        from plugins.onex.hooks.lib.pipeline_event_emitters import (
            emit_circuit_breaker_tripped,
        )

        emit_circuit_breaker_tripped(
            session_id="s1",
            failure_count=5,
            threshold=3,
            reset_timeout_seconds=30.0,
            correlation_id="c5",
        )
        self.mock_emit.assert_called_once()
        event_type, payload = self.mock_emit.call_args[0]
        assert event_type == "circuit.breaker.tripped"
        assert payload["failure_count"] == 5

    def test_emit_hostile_reviewer_completed(self) -> None:
        from plugins.onex.hooks.lib.pipeline_event_emitters import (
            emit_hostile_reviewer_completed,
        )

        emit_hostile_reviewer_completed(
            mode="file",
            target="plan.md",
            verdict="clean",
            correlation_id="c6",
        )
        self.mock_emit.assert_called_once()
        event_type, payload = self.mock_emit.call_args[0]
        assert event_type == "hostile.reviewer.completed"
        assert payload["verdict"] == "clean"

    def test_emit_plan_review_completed(self) -> None:
        from plugins.onex.hooks.lib.pipeline_event_emitters import (
            emit_plan_review_completed,
        )

        emit_plan_review_completed(
            session_id="s2",
            plan_file="plan.md",
            total_rounds=3,
            final_status="converged",
            correlation_id="c7",
        )
        self.mock_emit.assert_called_once()
        event_type, payload = self.mock_emit.call_args[0]
        assert event_type == "plan.review.completed"
        assert payload["total_rounds"] == 3

    def test_emit_dod_sweep_completed(self) -> None:
        from plugins.onex.hooks.lib.pipeline_event_emitters import (
            emit_dod_sweep_completed,
        )

        emit_dod_sweep_completed(
            run_id="r4",
            overall_status="passed",
            total_tickets=10,
            passed=8,
            failed=1,
            exempted=1,
            lookback_days=7,
            correlation_id="c8",
        )
        self.mock_emit.assert_called_once()
        event_type, payload = self.mock_emit.call_args[0]
        assert event_type == "dod.sweep.completed"
        assert payload["total_tickets"] == 10


@pytest.mark.unit
class TestEmitterMockBusAgentStatus:
    """Verify agent_status_emitter calls emit_event with 'agent.status'.

    agent_status_emitter imports emit_event lazily inside the function body
    via ``from .emit_client_wrapper import emit_event``, so we must patch
    the emit_client_wrapper module rather than the emitter module.
    """

    def test_emit_agent_status_calls_emit_event(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from unittest.mock import MagicMock

        mock_emit = MagicMock(return_value=True)
        # Patch at the source — emit_client_wrapper.emit_event — since the
        # agent_status_emitter does a lazy ``from .emit_client_wrapper import emit_event``.
        monkeypatch.setattr(
            "plugins.onex.hooks.lib.emit_client_wrapper.emit_event",
            mock_emit,
        )

        from plugins.onex.hooks.lib.agent_status_emitter import emit_agent_status

        emit_agent_status(state="working", message="test")
        mock_emit.assert_called_once()
        event_type = mock_emit.call_args[0][0]
        assert event_type == "agent.status"


@pytest.mark.unit
class TestEmitterMockBusCorrelationTrace:
    """Verify correlation_trace_emitter calls emit_event with 'correlation.trace.span'.

    correlation_trace_emitter imports emit_event lazily inside emit_trace_span
    via ``from .emit_client_wrapper import emit_event``.
    """

    def test_emit_trace_span_calls_emit_event(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from datetime import UTC, datetime
        from unittest.mock import MagicMock

        mock_emit = MagicMock(return_value=True)
        monkeypatch.setattr(
            "plugins.onex.hooks.lib.emit_client_wrapper.emit_event",
            mock_emit,
        )

        from plugins.onex.hooks.lib.correlation_trace_emitter import emit_trace_span

        emit_trace_span(
            span_kind="hook",
            operation_name="test_op",
            status="ok",
            started_at=datetime.now(UTC),
        )
        mock_emit.assert_called_once()
        event_type = mock_emit.call_args[0][0]
        assert event_type == "correlation.trace.span"


@pytest.mark.unit
class TestEmitterMockBusEnrichment:
    """Verify enrichment_observability_emitter calls emit_event with 'context.enrichment'.

    enrichment_observability_emitter imports emit_event at module scope with a
    try/except fallback to None.  We must patch it before importing the function.
    """

    def test_emit_enrichment_events_calls_emit_event(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        mock_emit = MagicMock(return_value=True)

        import plugins.onex.hooks.lib.enrichment_observability_emitter as eoe_mod

        monkeypatch.setattr(eoe_mod, "emit_event", mock_emit)

        # Create a minimal result object with the fields the emitter reads
        result = SimpleNamespace(
            name="test_source",
            status="success",
            tokens=100,
            latency_ms=50.0,
            error=None,
        )

        eoe_mod.emit_enrichment_events(
            results=[result],
            kept_names={"test_source"},
            correlation_id="c-enrich",
            session_id="s-enrich",
        )
        # At least one call should have been made
        assert mock_emit.call_count >= 1
        # All calls should use the correct event type
        for call in mock_emit.call_args_list:
            assert call[0][0] == "context.enrichment"


# ============================================================================
# Completeness guard: verify SUPPORTED_EVENT_TYPES coverage
# ============================================================================


@pytest.mark.unit
class TestEmissionRegistryCoverage:
    """Verify that all event types in SUPPORTED_EVENT_TYPES have at least one
    emitter module that references them in source code.

    This is a structural completeness check — if a new event type is added to
    the registry but no emitter module references it, this test will flag it.
    """

    # Event types that are emitted by the daemon itself or by shell scripts
    # (not by Python emitter modules in hooks/lib/).
    _DAEMON_OR_SCRIPT_ONLY = frozenset(
        {
            "session.started",
            "session.ended",
            "session.outcome",
            "prompt.submitted",
            "tool.executed",
            "routing.feedback",
            "response.stopped",
            "change.frame.emitted",
            "skill.started",
            "skill.completed",
            "pr.validation.rollup",
            "dod.verify.completed",
            "dod.guard.fired",
            "audit.dispatch.validated",
            "audit.scope.violation",
            "skill.friction_recorded",
            "utilization.scoring.requested",
            "hostile.reviewer.failed",
            "agent.chat.broadcast",
        }
    )

    def test_every_python_emitted_event_type_has_source_reference(self) -> None:
        """For each event type NOT in the daemon-only set, at least one
        hooks/lib/*.py file must contain the event type string."""
        from plugins.onex.hooks.lib.emit_client_wrapper import SUPPORTED_EVENT_TYPES

        all_sources: dict[str, str] = {}
        for py_file in _HOOKS_LIB.glob("*.py"):
            all_sources[py_file.name] = py_file.read_text()

        combined_source = "\n".join(all_sources.values())

        missing: list[str] = []
        for event_type in sorted(SUPPORTED_EVENT_TYPES):
            if event_type in self._DAEMON_OR_SCRIPT_ONLY:
                continue
            # Check if the event type string appears in any hooks/lib source
            if f'"{event_type}"' not in combined_source:
                missing.append(event_type)

        assert not missing, (
            f"Event types registered in SUPPORTED_EVENT_TYPES but not referenced "
            f"in any hooks/lib/*.py emitter module: {missing}"
        )
