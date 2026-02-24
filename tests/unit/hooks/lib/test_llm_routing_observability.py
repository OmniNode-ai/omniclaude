# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Unit tests for LLM routing observability events (OMN-2273).

Covers:
- ModelLlmRoutingDecisionPayload construction and field validation
- ModelLlmRoutingFallbackPayload construction and field validation
- _emit_llm_routing_decision() event construction (no Kafka interaction)
- _emit_llm_routing_fallback() event construction (no Kafka interaction)
- Event registry entries for llm.routing.decision and llm.routing.fallback
- Topics for LLM_ROUTING_DECISION and LLM_ROUTING_FALLBACK
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from omniclaude.hooks.event_registry import EVENT_REGISTRY
from omniclaude.hooks.schemas import (
    ModelLlmRoutingDecisionPayload,
    ModelLlmRoutingFallbackPayload,
)
from omniclaude.hooks.topics import TopicBase

# Plugin lib is on sys.path via tests/conftest.py; belt-and-suspenders for
# direct test invocation.
_LIB_PATH = str(
    Path(__file__).parent.parent.parent.parent.parent
    / "plugins"
    / "onex"
    / "hooks"
    / "lib"
)
if _LIB_PATH not in sys.path:
    sys.path.insert(0, _LIB_PATH)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_now() -> datetime:
    return datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)


def _valid_decision_kwargs(**overrides: Any) -> dict[str, Any]:
    """Return a dict of valid keyword arguments for ModelLlmRoutingDecisionPayload."""
    base: dict[str, Any] = {
        "session_id": "test-session-abc-123",
        "correlation_id": uuid4(),
        "emitted_at": _utc_now(),
        "selected_agent": "agent-api-architect",
        "llm_confidence": 0.87,
        "llm_latency_ms": 52,
        "fallback_used": False,
        "model_used": "Qwen2.5-14B",
        "fuzzy_top_candidate": "agent-api-architect",
        "llm_selected_candidate": "agent-api-architect",
        "agreement": True,
        "routing_prompt_version": "1.0.0",
    }
    base.update(overrides)
    return base


def _valid_fallback_kwargs(**overrides: Any) -> dict[str, Any]:
    """Return a dict of valid keyword arguments for ModelLlmRoutingFallbackPayload."""
    base: dict[str, Any] = {
        "session_id": "test-session-abc-123",
        "correlation_id": uuid4(),
        "emitted_at": _utc_now(),
        "fallback_reason": "LLM endpoint unhealthy",
        "llm_url": "http://test-llm-server:8200",
        "routing_prompt_version": "1.0.0",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# ModelLlmRoutingDecisionPayload
# ---------------------------------------------------------------------------


class TestModelLlmRoutingDecisionPayload:
    @pytest.mark.unit
    def test_valid_construction(self) -> None:
        payload = ModelLlmRoutingDecisionPayload(**_valid_decision_kwargs())
        assert payload.selected_agent == "agent-api-architect"
        assert payload.llm_confidence == 0.87
        assert payload.llm_latency_ms == 52
        assert payload.fallback_used is False
        assert payload.model_used == "Qwen2.5-14B"
        assert payload.fuzzy_top_candidate == "agent-api-architect"
        assert payload.llm_selected_candidate == "agent-api-architect"
        assert payload.agreement is True
        assert payload.routing_prompt_version == "1.0.0"

    @pytest.mark.unit
    def test_frozen_model(self) -> None:
        payload = ModelLlmRoutingDecisionPayload(**_valid_decision_kwargs())
        with pytest.raises(Exception):
            payload.selected_agent = "other-agent"  # type: ignore[misc]

    @pytest.mark.unit
    def test_confidence_clamp_lower(self) -> None:
        with pytest.raises(Exception):
            ModelLlmRoutingDecisionPayload(
                **_valid_decision_kwargs(llm_confidence=-0.1)
            )

    @pytest.mark.unit
    def test_confidence_clamp_upper(self) -> None:
        with pytest.raises(Exception):
            ModelLlmRoutingDecisionPayload(**_valid_decision_kwargs(llm_confidence=1.1))

    @pytest.mark.unit
    def test_confidence_boundary_values(self) -> None:
        p0 = ModelLlmRoutingDecisionPayload(
            **_valid_decision_kwargs(llm_confidence=0.0)
        )
        assert p0.llm_confidence == 0.0
        p1 = ModelLlmRoutingDecisionPayload(
            **_valid_decision_kwargs(llm_confidence=1.0)
        )
        assert p1.llm_confidence == 1.0

    @pytest.mark.unit
    def test_latency_ms_lower_bound(self) -> None:
        with pytest.raises(Exception):
            ModelLlmRoutingDecisionPayload(**_valid_decision_kwargs(llm_latency_ms=-1))

    @pytest.mark.unit
    def test_latency_ms_upper_bound(self) -> None:
        with pytest.raises(Exception):
            ModelLlmRoutingDecisionPayload(
                **_valid_decision_kwargs(llm_latency_ms=60001)
            )

    @pytest.mark.unit
    def test_latency_ms_zero_allowed(self) -> None:
        p = ModelLlmRoutingDecisionPayload(**_valid_decision_kwargs(llm_latency_ms=0))
        assert p.llm_latency_ms == 0

    @pytest.mark.unit
    def test_fuzzy_top_candidate_optional(self) -> None:
        p = ModelLlmRoutingDecisionPayload(
            **_valid_decision_kwargs(fuzzy_top_candidate=None)
        )
        assert p.fuzzy_top_candidate is None

    @pytest.mark.unit
    def test_llm_selected_candidate_optional(self) -> None:
        p = ModelLlmRoutingDecisionPayload(
            **_valid_decision_kwargs(llm_selected_candidate=None)
        )
        assert p.llm_selected_candidate is None

    @pytest.mark.unit
    def test_agreement_defaults_false(self) -> None:
        kwargs = _valid_decision_kwargs()
        kwargs.pop("agreement")
        p = ModelLlmRoutingDecisionPayload(**kwargs)
        assert p.agreement is False

    @pytest.mark.unit
    def test_selected_agent_required(self) -> None:
        kwargs = _valid_decision_kwargs()
        kwargs.pop("selected_agent")
        with pytest.raises(Exception):
            ModelLlmRoutingDecisionPayload(**kwargs)

    @pytest.mark.unit
    def test_routing_prompt_version_required(self) -> None:
        kwargs = _valid_decision_kwargs()
        kwargs.pop("routing_prompt_version")
        with pytest.raises(Exception):
            ModelLlmRoutingDecisionPayload(**kwargs)

    @pytest.mark.unit
    def test_extra_fields_ignored(self) -> None:
        # extra="ignore" — unknown fields must not raise
        p = ModelLlmRoutingDecisionPayload(
            **_valid_decision_kwargs(unknown_extra_field="should_be_ignored")
        )
        assert p.selected_agent == "agent-api-architect"
        assert not hasattr(p, "unknown_extra_field")

    @pytest.mark.unit
    def test_emitted_at_timezone_naive_converted_to_utc(self) -> None:
        """ensure_timezone_aware converts naive datetimes to UTC with a warning
        rather than rejecting them (consistent with omnibase_infra behavior).
        """
        import datetime as dt
        import warnings

        naive = dt.datetime(2025, 6, 1, 12, 0, 0)
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            p = ModelLlmRoutingDecisionPayload(
                **_valid_decision_kwargs(emitted_at=naive)
            )
        # The naive datetime is coerced to UTC — it must be timezone-aware
        assert p.emitted_at.tzinfo is not None

    @pytest.mark.unit
    def test_correlation_id_must_be_uuid(self) -> None:
        with pytest.raises(Exception):
            ModelLlmRoutingDecisionPayload(
                **_valid_decision_kwargs(correlation_id="not-a-uuid")
            )

    @pytest.mark.unit
    def test_fallback_used_true_scenario(self) -> None:
        p = ModelLlmRoutingDecisionPayload(
            **_valid_decision_kwargs(
                fallback_used=True,
                agreement=False,
                llm_selected_candidate=None,
            )
        )
        assert p.fallback_used is True
        assert p.agreement is False
        assert p.llm_selected_candidate is None


# ---------------------------------------------------------------------------
# ModelLlmRoutingFallbackPayload
# ---------------------------------------------------------------------------


class TestModelLlmRoutingFallbackPayload:
    @pytest.mark.unit
    def test_valid_construction(self) -> None:
        payload = ModelLlmRoutingFallbackPayload(**_valid_fallback_kwargs())
        assert payload.fallback_reason == "LLM endpoint unhealthy"
        assert payload.llm_url == "http://test-llm-server:8200"
        assert payload.routing_prompt_version == "1.0.0"

    @pytest.mark.unit
    def test_frozen_model(self) -> None:
        payload = ModelLlmRoutingFallbackPayload(**_valid_fallback_kwargs())
        with pytest.raises(Exception):
            payload.fallback_reason = "changed"  # type: ignore[misc]

    @pytest.mark.unit
    def test_llm_url_optional(self) -> None:
        p = ModelLlmRoutingFallbackPayload(**_valid_fallback_kwargs(llm_url=None))
        assert p.llm_url is None

    @pytest.mark.unit
    def test_fallback_reason_required(self) -> None:
        kwargs = _valid_fallback_kwargs()
        kwargs.pop("fallback_reason")
        with pytest.raises(Exception):
            ModelLlmRoutingFallbackPayload(**kwargs)

    @pytest.mark.unit
    def test_fallback_reason_max_length(self) -> None:
        long_reason = "x" * 501
        with pytest.raises(Exception):
            ModelLlmRoutingFallbackPayload(
                **_valid_fallback_kwargs(fallback_reason=long_reason)
            )

    @pytest.mark.unit
    def test_fallback_reason_exactly_500_chars(self) -> None:
        exact = "x" * 500
        p = ModelLlmRoutingFallbackPayload(
            **_valid_fallback_kwargs(fallback_reason=exact)
        )
        assert len(p.fallback_reason) == 500

    @pytest.mark.unit
    def test_routing_prompt_version_required(self) -> None:
        kwargs = _valid_fallback_kwargs()
        kwargs.pop("routing_prompt_version")
        with pytest.raises(Exception):
            ModelLlmRoutingFallbackPayload(**kwargs)

    @pytest.mark.unit
    def test_extra_fields_ignored(self) -> None:
        p = ModelLlmRoutingFallbackPayload(
            **_valid_fallback_kwargs(stray_key="ignored")
        )
        assert p.fallback_reason == "LLM endpoint unhealthy"
        assert not hasattr(p, "stray_key")

    @pytest.mark.unit
    def test_session_id_required(self) -> None:
        kwargs = _valid_fallback_kwargs()
        kwargs.pop("session_id")
        with pytest.raises(Exception):
            ModelLlmRoutingFallbackPayload(**kwargs)

    @pytest.mark.unit
    def test_timeout_reason(self) -> None:
        p = ModelLlmRoutingFallbackPayload(
            **_valid_fallback_kwargs(
                fallback_reason="LLM routing timed out after 100ms"
            )
        )
        assert "timed out" in p.fallback_reason


# ---------------------------------------------------------------------------
# Topics
# ---------------------------------------------------------------------------


class TestLlmRoutingTopics:
    @pytest.mark.unit
    def test_llm_routing_decision_topic_value(self) -> None:
        assert (
            TopicBase.LLM_ROUTING_DECISION
            == "onex.evt.omniclaude.llm-routing-decision.v1"
        )

    @pytest.mark.unit
    def test_llm_routing_fallback_topic_value(self) -> None:
        assert (
            TopicBase.LLM_ROUTING_FALLBACK
            == "onex.evt.omniclaude.llm-routing-fallback.v1"
        )

    @pytest.mark.unit
    def test_topics_follow_onex_naming_convention(self) -> None:
        # ONEX format: onex.{kind}.{producer}.{event-name}.v{n}
        for topic in (TopicBase.LLM_ROUTING_DECISION, TopicBase.LLM_ROUTING_FALLBACK):
            parts = topic.split(".")
            assert parts[0] == "onex", f"Must start with 'onex': {topic}"
            assert parts[1] == "evt", f"Must be 'evt' kind: {topic}"
            assert parts[2] == "omniclaude", f"Must have 'omniclaude' producer: {topic}"
            assert parts[-1].startswith("v"), f"Must end with version: {topic}"


# ---------------------------------------------------------------------------
# Event Registry
# ---------------------------------------------------------------------------


class TestLlmRoutingEventRegistry:
    @pytest.mark.unit
    def test_llm_routing_decision_registered(self) -> None:
        assert "llm.routing.decision" in EVENT_REGISTRY

    @pytest.mark.unit
    def test_llm_routing_fallback_registered(self) -> None:
        assert "llm.routing.fallback" in EVENT_REGISTRY

    @pytest.mark.unit
    def test_decision_fan_out_to_correct_topic(self) -> None:
        reg = EVENT_REGISTRY["llm.routing.decision"]
        topics = [r.topic_base for r in reg.fan_out]
        assert TopicBase.LLM_ROUTING_DECISION in topics

    @pytest.mark.unit
    def test_fallback_fan_out_to_correct_topic(self) -> None:
        reg = EVENT_REGISTRY["llm.routing.fallback"]
        topics = [r.topic_base for r in reg.fan_out]
        assert TopicBase.LLM_ROUTING_FALLBACK in topics

    @pytest.mark.unit
    def test_decision_required_fields(self) -> None:
        reg = EVENT_REGISTRY["llm.routing.decision"]
        for field in ("session_id", "selected_agent", "routing_prompt_version"):
            assert field in reg.required_fields

    @pytest.mark.unit
    def test_fallback_required_fields(self) -> None:
        reg = EVENT_REGISTRY["llm.routing.fallback"]
        for field in ("session_id", "fallback_reason", "routing_prompt_version"):
            assert field in reg.required_fields

    @pytest.mark.unit
    def test_decision_partition_key(self) -> None:
        reg = EVENT_REGISTRY["llm.routing.decision"]
        assert reg.partition_key_field == "session_id"

    @pytest.mark.unit
    def test_fallback_partition_key(self) -> None:
        reg = EVENT_REGISTRY["llm.routing.fallback"]
        assert reg.partition_key_field == "session_id"

    @pytest.mark.unit
    def test_decision_single_fan_out_rule(self) -> None:
        reg = EVENT_REGISTRY["llm.routing.decision"]
        assert len(reg.fan_out) == 1

    @pytest.mark.unit
    def test_fallback_single_fan_out_rule(self) -> None:
        reg = EVENT_REGISTRY["llm.routing.fallback"]
        assert len(reg.fan_out) == 1

    @pytest.mark.unit
    def test_decision_no_transform(self) -> None:
        reg = EVENT_REGISTRY["llm.routing.decision"]
        # Passthrough — no transform function needed
        assert reg.fan_out[0].transform is None

    @pytest.mark.unit
    def test_fallback_no_transform(self) -> None:
        reg = EVENT_REGISTRY["llm.routing.fallback"]
        assert reg.fan_out[0].transform is None


# ---------------------------------------------------------------------------
# Emission helpers (_emit_llm_routing_decision, _emit_llm_routing_fallback)
# ---------------------------------------------------------------------------


class TestEmitLlmRoutingDecision:
    """Tests for _emit_llm_routing_decision() in route_via_events_wrapper."""

    @pytest.mark.unit
    def test_emits_with_correct_event_type(self) -> None:
        import route_via_events_wrapper as wrapper

        captured: list[dict[str, Any]] = []

        def fake_emit(event_type: str, payload: dict[str, Any]) -> bool:
            captured.append({"event_type": event_type, "payload": payload})
            return True

        result = {
            "selected_agent": "agent-debug",
            "confidence": 0.75,
            "latency_ms": 40,
            "model_used": "Qwen2.5-14B",
            "llm_selected_candidate": "agent-debug",
            "fallback_used": False,
        }

        original = wrapper._emit_event_fn
        try:
            wrapper._emit_event_fn = fake_emit  # type: ignore[attr-defined]
            wrapper._emit_llm_routing_decision(
                result=result,
                correlation_id="test-corr-id",
                session_id="test-session-id",
                fuzzy_top_candidate="agent-debug",
                llm_selected_candidate="agent-debug",
                agreement=True,
                routing_prompt_version="1.0.0",
                model_used="Qwen2.5-14B",
            )
        finally:
            wrapper._emit_event_fn = original  # type: ignore[attr-defined]

        assert len(captured) == 1
        assert captured[0]["event_type"] == "llm.routing.decision"

    @pytest.mark.unit
    def test_emits_all_required_fields(self) -> None:
        import route_via_events_wrapper as wrapper

        captured: list[dict[str, Any]] = []

        def fake_emit(event_type: str, payload: dict[str, Any]) -> bool:
            captured.append(payload)
            return True

        result = {
            "selected_agent": "agent-api-architect",
            "confidence": 0.91,
            "latency_ms": 35,
            "model_used": "Qwen2.5-14B",
            "llm_selected_candidate": "agent-api-architect",
            "fallback_used": False,
        }

        original = wrapper._emit_event_fn
        try:
            wrapper._emit_event_fn = fake_emit  # type: ignore[attr-defined]
            wrapper._emit_llm_routing_decision(
                result=result,
                correlation_id="test-corr-id",
                session_id="test-session-id",
                fuzzy_top_candidate="agent-api-architect",
                llm_selected_candidate="agent-api-architect",
                agreement=True,
                routing_prompt_version="1.0.0",
                model_used="Qwen2.5-14B",
            )
        finally:
            wrapper._emit_event_fn = original  # type: ignore[attr-defined]

        assert len(captured) == 1
        p = captured[0]
        assert p["session_id"] == "test-session-id"
        assert p["correlation_id"] == "test-corr-id"
        assert p["selected_agent"] == "agent-api-architect"
        assert p["llm_confidence"] == 0.91
        assert p["llm_latency_ms"] == 35
        assert p["fallback_used"] is False
        assert p["model_used"] == "Qwen2.5-14B"
        assert p["fuzzy_top_candidate"] == "agent-api-architect"
        assert p["llm_selected_candidate"] == "agent-api-architect"
        assert p["agreement"] is True
        assert p["routing_prompt_version"] == "1.0.0"

    @pytest.mark.unit
    def test_no_emission_when_emit_fn_unavailable(self) -> None:
        import route_via_events_wrapper as wrapper

        original = wrapper._emit_event_fn
        try:
            wrapper._emit_event_fn = None  # type: ignore[attr-defined]
            # Must not raise
            wrapper._emit_llm_routing_decision(
                result={
                    "selected_agent": "agent-debug",
                    "confidence": 0.7,
                    "latency_ms": 10,
                },
                correlation_id="corr",
                session_id="sess",
                fuzzy_top_candidate=None,
                llm_selected_candidate=None,
                agreement=False,
                routing_prompt_version="1.0.0",
                model_used="unknown",
            )
        finally:
            wrapper._emit_event_fn = original  # type: ignore[attr-defined]

    @pytest.mark.unit
    def test_exception_in_emit_fn_is_non_blocking(self) -> None:
        import route_via_events_wrapper as wrapper

        def boom(event_type: str, payload: dict[str, Any]) -> bool:
            raise RuntimeError("Kafka unavailable")

        original = wrapper._emit_event_fn
        try:
            wrapper._emit_event_fn = boom  # type: ignore[attr-defined]
            # Must not raise
            wrapper._emit_llm_routing_decision(
                result={
                    "selected_agent": "agent-debug",
                    "confidence": 0.7,
                    "latency_ms": 10,
                },
                correlation_id="corr",
                session_id="sess",
                fuzzy_top_candidate=None,
                llm_selected_candidate=None,
                agreement=False,
                routing_prompt_version="1.0.0",
                model_used="Qwen2.5-14B",
            )
        finally:
            wrapper._emit_event_fn = original  # type: ignore[attr-defined]

    @pytest.mark.unit
    def test_session_id_none_falls_back_to_unknown(self) -> None:
        import route_via_events_wrapper as wrapper

        captured: list[dict[str, Any]] = []

        def fake_emit(event_type: str, payload: dict[str, Any]) -> bool:
            captured.append(payload)
            return True

        original = wrapper._emit_event_fn
        try:
            wrapper._emit_event_fn = fake_emit  # type: ignore[attr-defined]
            wrapper._emit_llm_routing_decision(
                result={
                    "selected_agent": "agent-debug",
                    "confidence": 0.7,
                    "latency_ms": 10,
                },
                correlation_id="corr",
                session_id=None,
                fuzzy_top_candidate=None,
                llm_selected_candidate=None,
                agreement=False,
                routing_prompt_version="1.0.0",
                model_used="Qwen2.5-14B",
            )
        finally:
            wrapper._emit_event_fn = original  # type: ignore[attr-defined]

        assert captured[0]["session_id"] == "unknown"


class TestEmitLlmRoutingFallback:
    """Tests for _emit_llm_routing_fallback() in route_via_events_wrapper."""

    @pytest.mark.unit
    def test_emits_with_correct_event_type(self) -> None:
        import route_via_events_wrapper as wrapper

        captured: list[dict[str, Any]] = []

        def fake_emit(event_type: str, payload: dict[str, Any]) -> bool:
            captured.append({"event_type": event_type, "payload": payload})
            return True

        original = wrapper._emit_event_fn
        try:
            wrapper._emit_event_fn = fake_emit  # type: ignore[attr-defined]
            wrapper._emit_llm_routing_fallback(
                correlation_id="test-corr",
                session_id="test-sess",
                fallback_reason="LLM endpoint unhealthy",
                llm_url="http://test-llm-server:8200",
                routing_prompt_version="1.0.0",
            )
        finally:
            wrapper._emit_event_fn = original  # type: ignore[attr-defined]

        assert len(captured) == 1
        assert captured[0]["event_type"] == "llm.routing.fallback"

    @pytest.mark.unit
    def test_emits_all_required_fields(self) -> None:
        import route_via_events_wrapper as wrapper

        captured: list[dict[str, Any]] = []

        def fake_emit(event_type: str, payload: dict[str, Any]) -> bool:
            captured.append(payload)
            return True

        original = wrapper._emit_event_fn
        try:
            wrapper._emit_event_fn = fake_emit  # type: ignore[attr-defined]
            wrapper._emit_llm_routing_fallback(
                correlation_id="corr-xyz",
                session_id="sess-abc",
                fallback_reason="Timeout",
                llm_url="http://test-llm-server:8200",
                routing_prompt_version="1.0.0",
            )
        finally:
            wrapper._emit_event_fn = original  # type: ignore[attr-defined]

        assert len(captured) == 1
        p = captured[0]
        assert p["session_id"] == "sess-abc"
        assert p["correlation_id"] == "corr-xyz"
        assert p["fallback_reason"] == "Timeout"
        assert p["llm_url"] == "http://test-llm-server:8200"
        assert p["routing_prompt_version"] == "1.0.0"

    @pytest.mark.unit
    def test_no_emission_when_emit_fn_unavailable(self) -> None:
        import route_via_events_wrapper as wrapper

        original = wrapper._emit_event_fn
        try:
            wrapper._emit_event_fn = None  # type: ignore[attr-defined]
            wrapper._emit_llm_routing_fallback(
                correlation_id="corr",
                session_id="sess",
                fallback_reason="unavailable",
                llm_url=None,
                routing_prompt_version="1.0.0",
            )
        finally:
            wrapper._emit_event_fn = original  # type: ignore[attr-defined]

    @pytest.mark.unit
    def test_exception_in_emit_fn_is_non_blocking(self) -> None:
        import route_via_events_wrapper as wrapper

        def boom(event_type: str, payload: dict[str, Any]) -> bool:
            raise RuntimeError("network down")

        original = wrapper._emit_event_fn
        try:
            wrapper._emit_event_fn = boom  # type: ignore[attr-defined]
            wrapper._emit_llm_routing_fallback(
                correlation_id="corr",
                session_id="sess",
                fallback_reason="test fallback",
                llm_url=None,
                routing_prompt_version="1.0.0",
            )
        finally:
            wrapper._emit_event_fn = original  # type: ignore[attr-defined]

    @pytest.mark.unit
    def test_session_id_none_falls_back_to_unknown(self) -> None:
        import route_via_events_wrapper as wrapper

        captured: list[dict[str, Any]] = []

        def fake_emit(event_type: str, payload: dict[str, Any]) -> bool:
            captured.append(payload)
            return True

        original = wrapper._emit_event_fn
        try:
            wrapper._emit_event_fn = fake_emit  # type: ignore[attr-defined]
            wrapper._emit_llm_routing_fallback(
                correlation_id="corr",
                session_id=None,
                fallback_reason="unhealthy",
                llm_url=None,
                routing_prompt_version="1.0.0",
            )
        finally:
            wrapper._emit_event_fn = original  # type: ignore[attr-defined]

        assert captured[0]["session_id"] == "unknown"

    @pytest.mark.unit
    def test_llm_url_none_included_in_payload(self) -> None:
        import route_via_events_wrapper as wrapper

        captured: list[dict[str, Any]] = []

        def fake_emit(event_type: str, payload: dict[str, Any]) -> bool:
            captured.append(payload)
            return True

        original = wrapper._emit_event_fn
        try:
            wrapper._emit_event_fn = fake_emit  # type: ignore[attr-defined]
            wrapper._emit_llm_routing_fallback(
                correlation_id="corr",
                session_id="sess",
                fallback_reason="no url",
                llm_url=None,
                routing_prompt_version="1.0.0",
            )
        finally:
            wrapper._emit_event_fn = original  # type: ignore[attr-defined]

        # llm_url=None should be preserved in payload for consumers
        assert "llm_url" in captured[0]
        assert captured[0]["llm_url"] is None
