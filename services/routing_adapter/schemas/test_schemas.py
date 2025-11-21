#!/usr/bin/env python3
"""
Schema Validation Tests

Unit tests for routing event schemas.
Validates Pydantic models, validation rules, and serialization.

Run:
    python3 test_schemas.py

Expected Output:
    ✅ All tests pass
    ✅ Schemas are ready for use

Created: 2025-10-30
"""

import json
import sys
from pathlib import Path
from uuid import uuid4


# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

# Import envelope after fixing relative imports in it
import importlib.util

import pytest
from model_routing_error import (
    ErrorCodes,
    ModelFallbackRecommendation,
    ModelRoutingError,
)
from model_routing_request import ModelRoutingRequest
from model_routing_response import (
    ModelAgentRecommendation,
    ModelRoutingConfidence,
    ModelRoutingMetadata,
    ModelRoutingResponse,
)
from pydantic import ValidationError


spec = importlib.util.spec_from_file_location(
    "model_routing_event_envelope",
    Path(__file__).parent / "model_routing_event_envelope.py",
)
envelope_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(envelope_module)
ModelRoutingEventEnvelope = envelope_module.ModelRoutingEventEnvelope


class TestRoutingRequest:
    """Test ModelRoutingRequest validation."""

    def test_valid_request(self):
        """Test valid routing request."""
        request = ModelRoutingRequest(
            user_request="optimize my database queries",
            correlation_id=str(uuid4()),
        )
        assert request.user_request == "optimize my database queries"
        assert request.timeout_ms == 5000  # Default

    def test_valid_request_with_context(self):
        """Test routing request with context."""
        correlation_id = str(uuid4())
        request = ModelRoutingRequest(
            user_request="optimize my database queries",
            correlation_id=correlation_id,
            context={"domain": "database_optimization"},
            timeout_ms=3000,
        )
        assert request.context["domain"] == "database_optimization"
        assert request.timeout_ms == 3000

    def test_invalid_empty_user_request(self):
        """Test validation fails for empty user_request."""
        with pytest.raises(ValidationError) as exc_info:
            ModelRoutingRequest(
                user_request="",
                correlation_id=str(uuid4()),
            )
        assert "user_request" in str(exc_info.value)

    def test_invalid_whitespace_only_user_request(self):
        """Test validation fails for whitespace-only user_request."""
        with pytest.raises(ValidationError) as exc_info:
            ModelRoutingRequest(
                user_request="   ",
                correlation_id=str(uuid4()),
            )
        assert "user_request" in str(exc_info.value)

    def test_invalid_correlation_id(self):
        """Test validation fails for invalid UUID."""
        with pytest.raises(ValidationError) as exc_info:
            ModelRoutingRequest(
                user_request="optimize queries",
                correlation_id="not-a-uuid",
            )
        assert "correlation_id" in str(exc_info.value)

    def test_invalid_timeout_too_low(self):
        """Test validation fails for timeout < 1000ms."""
        with pytest.raises(ValidationError) as exc_info:
            ModelRoutingRequest(
                user_request="optimize queries",
                correlation_id=str(uuid4()),
                timeout_ms=500,
            )
        assert "timeout_ms" in str(exc_info.value)

    def test_invalid_timeout_too_high(self):
        """Test validation fails for timeout > 30000ms."""
        with pytest.raises(ValidationError) as exc_info:
            ModelRoutingRequest(
                user_request="optimize queries",
                correlation_id=str(uuid4()),
                timeout_ms=50000,
            )
        assert "timeout_ms" in str(exc_info.value)


class TestRoutingResponse:
    """Test ModelRoutingResponse validation."""

    def test_valid_response(self):
        """Test valid routing response."""
        correlation_id = str(uuid4())
        response = ModelRoutingResponse(
            correlation_id=correlation_id,
            recommendations=[
                ModelAgentRecommendation(
                    agent_name="agent-performance",
                    agent_title="Performance Optimization Specialist",
                    confidence=ModelRoutingConfidence(
                        total=0.92,
                        trigger_score=0.95,
                        context_score=0.90,
                        capability_score=0.88,
                        historical_score=0.95,
                        explanation="High confidence match",
                    ),
                    reason="Strong trigger match",
                    definition_path="/path/to/agent.yaml",
                )
            ],
            routing_metadata=ModelRoutingMetadata(
                routing_time_ms=45,
                cache_hit=False,
                candidates_evaluated=5,
                routing_strategy="enhanced_fuzzy_matching",
            ),
        )
        assert len(response.recommendations) == 1
        assert response.recommendations[0].agent_name == "agent-performance"
        assert response.routing_metadata.routing_time_ms == 45

    def test_invalid_empty_recommendations(self):
        """Test validation fails for empty recommendations list."""
        with pytest.raises(ValidationError) as exc_info:
            ModelRoutingResponse(
                correlation_id=str(uuid4()),
                recommendations=[],
                routing_metadata=ModelRoutingMetadata(
                    routing_time_ms=45,
                    cache_hit=False,
                    candidates_evaluated=0,
                    routing_strategy="enhanced_fuzzy_matching",
                ),
            )
        assert "recommendations" in str(exc_info.value)

    def test_invalid_unsorted_recommendations(self):
        """Test validation fails for unsorted recommendations."""
        with pytest.raises(ValidationError) as exc_info:
            ModelRoutingResponse(
                correlation_id=str(uuid4()),
                recommendations=[
                    ModelAgentRecommendation(
                        agent_name="agent-1",
                        agent_title="Agent 1",
                        confidence=ModelRoutingConfidence(
                            total=0.70,  # Lower confidence
                            trigger_score=0.70,
                            context_score=0.70,
                            capability_score=0.70,
                            historical_score=0.70,
                            explanation="Lower confidence",
                        ),
                        reason="Reason 1",
                        definition_path="/path/1",
                    ),
                    ModelAgentRecommendation(
                        agent_name="agent-2",
                        agent_title="Agent 2",
                        confidence=ModelRoutingConfidence(
                            total=0.92,  # Higher confidence (should be first!)
                            trigger_score=0.92,
                            context_score=0.92,
                            capability_score=0.92,
                            historical_score=0.92,
                            explanation="Higher confidence",
                        ),
                        reason="Reason 2",
                        definition_path="/path/2",
                    ),
                ],
                routing_metadata=ModelRoutingMetadata(
                    routing_time_ms=45,
                    cache_hit=False,
                    candidates_evaluated=2,
                    routing_strategy="enhanced_fuzzy_matching",
                ),
            )
        assert "sorted by confidence" in str(exc_info.value)


class TestRoutingError:
    """Test ModelRoutingError validation."""

    def test_valid_error(self):
        """Test valid routing error."""
        error = ModelRoutingError(
            correlation_id=str(uuid4()),
            error_code="ROUTING_TIMEOUT",
            error_message="Routing decision exceeded timeout",
        )
        assert error.error_code == "ROUTING_TIMEOUT"
        assert error.error_message == "Routing decision exceeded timeout"

    def test_valid_error_with_fallback(self):
        """Test routing error with fallback recommendation."""
        error = ModelRoutingError(
            correlation_id=str(uuid4()),
            error_code="NO_AGENTS_AVAILABLE",
            error_message="No agents match criteria",
            fallback_recommendation=ModelFallbackRecommendation(
                agent_name="polymorphic-agent",
                reason="Fallback to polymorphic agent",
            ),
        )
        assert error.fallback_recommendation.agent_name == "polymorphic-agent"

    def test_error_codes_constants(self):
        """Test error code constants."""
        assert ErrorCodes.REGISTRY_LOAD_FAILED == "REGISTRY_LOAD_FAILED"
        assert ErrorCodes.ROUTING_TIMEOUT == "ROUTING_TIMEOUT"
        assert ErrorCodes.NO_AGENTS_AVAILABLE == "NO_AGENTS_AVAILABLE"

    def test_invalid_lowercase_error_code(self):
        """Test validation fails for lowercase error code."""
        with pytest.raises(ValidationError) as exc_info:
            ModelRoutingError(
                correlation_id=str(uuid4()),
                error_code="routing_timeout",  # Should be uppercase
                error_message="Routing timeout",
            )
        assert "error_code" in str(exc_info.value)


class TestRoutingEventEnvelope:
    """Test ModelRoutingEventEnvelope validation."""

    def test_create_request_envelope(self):
        """Test request envelope creation."""
        correlation_id = str(uuid4())
        envelope = ModelRoutingEventEnvelope.create_request(
            user_request="optimize my database queries",
            correlation_id=correlation_id,
        )
        assert envelope.event_type == "AGENT_ROUTING_REQUESTED"
        assert envelope.correlation_id == correlation_id
        assert envelope.service == "polymorphic-agent"
        assert isinstance(envelope.payload, ModelRoutingRequest)

    def test_create_response_envelope(self):
        """Test response envelope creation."""
        correlation_id = str(uuid4())
        envelope = ModelRoutingEventEnvelope.create_response(
            correlation_id=correlation_id,
            recommendations=[
                {
                    "agent_name": "agent-performance",
                    "agent_title": "Performance Optimization Specialist",
                    "confidence": {
                        "total": 0.92,
                        "trigger_score": 0.95,
                        "context_score": 0.90,
                        "capability_score": 0.88,
                        "historical_score": 0.95,
                        "explanation": "High confidence match",
                    },
                    "reason": "Strong trigger match",
                    "definition_path": "/path/to/agent.yaml",
                }
            ],
            routing_metadata={
                "routing_time_ms": 45,
                "cache_hit": False,
                "candidates_evaluated": 5,
                "routing_strategy": "enhanced_fuzzy_matching",
            },
        )
        assert envelope.event_type == "AGENT_ROUTING_COMPLETED"
        assert envelope.correlation_id == correlation_id
        assert isinstance(envelope.payload, ModelRoutingResponse)

    def test_create_error_envelope(self):
        """Test error envelope creation."""
        correlation_id = str(uuid4())
        envelope = ModelRoutingEventEnvelope.create_error(
            correlation_id=correlation_id,
            error_code="ROUTING_TIMEOUT",
            error_message="Routing decision exceeded timeout",
        )
        assert envelope.event_type == "AGENT_ROUTING_FAILED"
        assert envelope.correlation_id == correlation_id
        assert isinstance(envelope.payload, ModelRoutingError)

    def test_invalid_event_type(self):
        """Test validation fails for invalid event type."""
        with pytest.raises(ValidationError) as exc_info:
            ModelRoutingEventEnvelope(
                event_type="INVALID_EVENT_TYPE",
                correlation_id=str(uuid4()),
                service="test",
                payload={},
            )
        assert "event_type" in str(exc_info.value)

    def test_serialization(self):
        """Test JSON serialization."""
        correlation_id = str(uuid4())
        envelope = ModelRoutingEventEnvelope.create_request(
            user_request="optimize my database queries",
            correlation_id=correlation_id,
        )

        # Serialize to JSON
        json_str = envelope.model_dump_json()
        assert isinstance(json_str, str)

        # Deserialize from JSON
        data = json.loads(json_str)
        envelope_2 = ModelRoutingEventEnvelope(**data)
        assert envelope_2.correlation_id == correlation_id


class TestIntegration:
    """Integration tests for complete event flow."""

    def test_request_response_flow(self):
        """Test complete request-response flow."""
        correlation_id = str(uuid4())

        # 1. Create request envelope
        request_envelope = ModelRoutingEventEnvelope.create_request(
            user_request="optimize my database queries",
            correlation_id=correlation_id,
            context={"domain": "database_optimization"},
        )
        assert request_envelope.event_type == "AGENT_ROUTING_REQUESTED"

        # Simulate Kafka publish (serialize to JSON)
        request_json = request_envelope.model_dump_json()

        # 2. Service receives request (deserialize from JSON)
        request_data = json.loads(request_json)
        received_envelope = ModelRoutingEventEnvelope(**request_data)
        assert received_envelope.correlation_id == correlation_id
        request = received_envelope.payload
        assert request.user_request == "optimize my database queries"

        # 3. Service creates response envelope
        response_envelope = ModelRoutingEventEnvelope.create_response(
            correlation_id=correlation_id,
            recommendations=[
                {
                    "agent_name": "agent-performance",
                    "agent_title": "Performance Optimization Specialist",
                    "confidence": {
                        "total": 0.92,
                        "trigger_score": 0.95,
                        "context_score": 0.90,
                        "capability_score": 0.88,
                        "historical_score": 0.95,
                        "explanation": "High confidence match",
                    },
                    "reason": "Strong trigger match",
                    "definition_path": "/path/to/agent.yaml",
                }
            ],
            routing_metadata={
                "routing_time_ms": 45,
                "cache_hit": False,
                "candidates_evaluated": 5,
                "routing_strategy": "enhanced_fuzzy_matching",
            },
        )
        assert response_envelope.event_type == "AGENT_ROUTING_COMPLETED"

        # Simulate Kafka publish (serialize to JSON)
        response_json = response_envelope.model_dump_json()

        # 4. Agent receives response (deserialize from JSON)
        response_data = json.loads(response_json)
        received_response = ModelRoutingEventEnvelope(**response_data)
        assert received_response.correlation_id == correlation_id
        response = received_response.payload
        assert response.recommendations[0].agent_name == "agent-performance"


if __name__ == "__main__":
    """Run tests directly."""
    import sys

    print("Running routing event schema validation tests...\n")

    # Run all test classes
    test_classes = [
        TestRoutingRequest,
        TestRoutingResponse,
        TestRoutingError,
        TestRoutingEventEnvelope,
        TestIntegration,
    ]

    total_tests = 0
    passed_tests = 0
    failed_tests = 0

    for test_class in test_classes:
        print(f"Testing {test_class.__name__}...")
        instance = test_class()
        methods = [m for m in dir(instance) if m.startswith("test_")]

        for method_name in methods:
            total_tests += 1
            try:
                method = getattr(instance, method_name)
                method()
                print(f"  ✅ {method_name}")
                passed_tests += 1
            except Exception as e:
                print(f"  ❌ {method_name}: {e}")
                failed_tests += 1

        print()

    # Summary
    print("=" * 60)
    print(f"Total Tests: {total_tests}")
    print(f"Passed: {passed_tests}")
    print(f"Failed: {failed_tests}")
    print("=" * 60)

    if failed_tests == 0:
        print("\n✅ All tests passed! Schemas are ready for use.")
        sys.exit(0)
    else:
        print(f"\n❌ {failed_tests} test(s) failed. Please fix validation errors.")
        sys.exit(1)
