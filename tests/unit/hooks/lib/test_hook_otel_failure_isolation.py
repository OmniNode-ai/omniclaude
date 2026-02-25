# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests: Hook OTEL failure isolation (OMN-2734).

Requirement: Export errors must not propagate to the hook. The exporter
must be non-blocking and drop spans on failure without raising.

Test IDs (matches DoD):
    uv run pytest tests/unit/ -k hook_otel_failure_isolation
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# sys.path setup: mirror how hooks/lib scripts are loaded by hook scripts
# ---------------------------------------------------------------------------
_HOOKS_LIB = str(Path(__file__).parents[4] / "plugins" / "onex" / "hooks" / "lib")
if _HOOKS_LIB not in sys.path:
    sys.path.insert(0, _HOOKS_LIB)


# ---------------------------------------------------------------------------
# Tests: phoenix_otel_exporter failure isolation
# ---------------------------------------------------------------------------


class TestPhoenixOtelExporterIsolation:
    """emit_injection_span must never raise regardless of OTEL SDK state."""

    def setup_method(self) -> None:
        """Reset singleton state before each test."""
        # Import lazily to pick up sys.path changes
        import phoenix_otel_exporter as mod  # noqa: F401

        mod_obj = sys.modules.get("phoenix_otel_exporter")
        if mod_obj is not None:
            mod_obj.reset_tracer()

    def test_emit_returns_false_when_sdk_unavailable(self) -> None:
        """When opentelemetry SDK is not installed, emit_injection_span returns False (not raises)."""
        import phoenix_otel_exporter as mod

        with patch.object(mod, "_OTEL_AVAILABLE", False):
            mod.reset_tracer()
            result = mod.emit_injection_span(
                session_id="test-session",
                correlation_id="test-corr",
                manifest_injected=True,
                injected_pattern_count=3,
                agent_matched=True,
                selected_agent="polymorphic-agent",
                injection_latency_ms=42.0,
                cohort="treatment",
            )
        assert result is False

    def test_emit_returns_false_when_disabled(self) -> None:
        """When PHOENIX_OTEL_ENABLED=false, emit_injection_span returns False."""
        import phoenix_otel_exporter as mod

        mod.reset_tracer()
        with patch.dict("os.environ", {"PHOENIX_OTEL_ENABLED": "false"}):
            mod.reset_tracer()
            result = mod.emit_injection_span(
                session_id="test-session",
                correlation_id="test-corr",
                manifest_injected=False,
                injected_pattern_count=0,
                agent_matched=False,
                selected_agent="",
                injection_latency_ms=5.0,
                cohort="control",
            )
        assert result is False

    def test_emit_does_not_raise_when_tracer_raises(self) -> None:
        """If the OTEL tracer raises during span creation, emit_injection_span catches it."""
        import phoenix_otel_exporter as mod

        mock_tracer = MagicMock()
        mock_tracer.start_as_current_span.side_effect = RuntimeError("OTEL exploded")

        with patch.object(mod, "_get_tracer", return_value=mock_tracer):
            # Must not raise
            result = mod.emit_injection_span(
                session_id="s1",
                correlation_id="c1",
                manifest_injected=True,
                injected_pattern_count=1,
                agent_matched=True,
                selected_agent="agent-x",
                injection_latency_ms=10.0,
                cohort="treatment",
            )
        assert result is False

    def test_emit_does_not_raise_when_exporter_raises(self) -> None:
        """If OTLP export fails (network error), span emission returns False, no raise."""
        import phoenix_otel_exporter as mod

        mock_span = MagicMock()
        mock_span.__enter__ = MagicMock(return_value=mock_span)
        mock_span.__exit__ = MagicMock(return_value=False)
        mock_span.set_attribute.side_effect = Exception("network error")

        mock_tracer = MagicMock()
        mock_tracer.start_as_current_span.return_value = mock_span

        with patch.object(mod, "_get_tracer", return_value=mock_tracer):
            result = mod.emit_injection_span(
                session_id="s2",
                correlation_id="c2",
                manifest_injected=True,
                injected_pattern_count=2,
                agent_matched=False,
                selected_agent="",
                injection_latency_ms=15.0,
                cohort="treatment",
            )
        assert result is False

    def test_emit_returns_true_on_success(self) -> None:
        """When span creation succeeds, emit_injection_span returns True."""
        import phoenix_otel_exporter as mod

        mock_span = MagicMock()
        mock_span.__enter__ = MagicMock(return_value=mock_span)
        mock_span.__exit__ = MagicMock(return_value=False)

        mock_tracer = MagicMock()
        mock_tracer.start_as_current_span.return_value = mock_span

        with patch.object(mod, "_get_tracer", return_value=mock_tracer):
            result = mod.emit_injection_span(
                session_id="s3",
                correlation_id="c3",
                manifest_injected=True,
                injected_pattern_count=5,
                agent_matched=True,
                selected_agent="polymorphic-agent",
                injection_latency_ms=33.0,
                cohort="treatment",
            )
        assert result is True
        # Verify all required attributes were set
        set_calls = {call.args[0] for call in mock_span.set_attribute.call_args_list}
        assert "session_id" in set_calls
        assert "correlation_id" in set_calls
        assert "manifest_injected" in set_calls
        assert "injected_pattern_count" in set_calls
        assert "agent_matched" in set_calls
        assert "selected_agent" in set_calls
        assert "injection_latency_ms" in set_calls
        assert "cohort" in set_calls

    def test_required_span_attributes_present(self) -> None:
        """All 8 required span attributes from OMN-2734 contract must be set."""
        import phoenix_otel_exporter as mod

        mock_span = MagicMock()
        mock_span.__enter__ = MagicMock(return_value=mock_span)
        mock_span.__exit__ = MagicMock(return_value=False)
        mock_tracer = MagicMock()
        mock_tracer.start_as_current_span.return_value = mock_span

        with patch.object(mod, "_get_tracer", return_value=mock_tracer):
            mod.emit_injection_span(
                session_id="session-abc",
                correlation_id="corr-xyz",
                manifest_injected=True,
                injected_pattern_count=3,
                agent_matched=True,
                selected_agent="polymorphic-agent",
                injection_latency_ms=42.5,
                cohort="treatment",
            )

        # Collect all attribute names set on the span
        set_attrs = {
            call.args[0]: call.args[1]
            for call in mock_span.set_attribute.call_args_list
        }

        required_attrs = {
            "session_id",
            "correlation_id",
            "manifest_injected",
            "injected_pattern_count",
            "agent_matched",
            "selected_agent",
            "injection_latency_ms",
            "cohort",
        }
        assert required_attrs.issubset(set_attrs.keys()), (
            f"Missing required span attributes: {required_attrs - set_attrs.keys()}"
        )

        # Verify types match contract
        assert isinstance(set_attrs["manifest_injected"], bool)
        assert isinstance(set_attrs["injected_pattern_count"], int)
        assert isinstance(set_attrs["agent_matched"], bool)
        assert isinstance(set_attrs["injection_latency_ms"], float)
        assert isinstance(set_attrs["cohort"], str)
        assert set_attrs["cohort"] in ("control", "treatment")

    def test_reset_tracer_forces_reinitialization(self) -> None:
        """reset_tracer() clears singleton state set during a prior initialization."""
        import phoenix_otel_exporter as mod

        mock_span = MagicMock()
        mock_span.__enter__ = MagicMock(return_value=mock_span)
        mock_span.__exit__ = MagicMock(return_value=False)
        mock_tracer = MagicMock()
        mock_tracer.start_as_current_span.return_value = mock_span

        # Simulate a successful init by calling _get_tracer with a mock
        with patch.object(mod, "_get_tracer", return_value=mock_tracer):
            # Manually set state as if provider was initialized
            with mod._provider_lock:
                mod._provider_initialized = True
                mod._tracer = mock_tracer

            assert mod._provider_initialized is True
            assert mod._tracer is not None

        # Now reset should clear all state
        mod.reset_tracer()
        assert mod._provider_initialized is False
        assert mod._tracer is None
        assert mod._tracer_provider is None
