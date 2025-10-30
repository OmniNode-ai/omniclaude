#!/usr/bin/env python3
"""
Simple schema validation test runner.

Run from project root:
    python3 test_routing_schemas.py

This validates the routing event schemas work correctly.
"""

import json
import sys
from pathlib import Path
from uuid import uuid4

# Add schemas directory to path
schemas_path = Path(__file__).parent / "services" / "routing_adapter" / "schemas"
sys.path.insert(0, str(schemas_path))

print("Testing routing event schemas...")
print(f"Schema path: {schemas_path}\n")

try:
    # Import schemas
    from model_routing_error import ErrorCodes, ModelRoutingError
    from model_routing_request import ModelRoutingRequest
    from model_routing_response import (
        ModelAgentRecommendation,
        ModelRoutingConfidence,
        ModelRoutingMetadata,
        ModelRoutingResponse,
    )

    print("✅ All schema imports successful\n")

    # Test 1: Create routing request
    print("Test 1: Create routing request...")
    correlation_id = str(uuid4())
    request = ModelRoutingRequest(
        user_request="optimize my database queries",
        correlation_id=correlation_id,
        context={"domain": "database_optimization"},
    )
    print(f"  ✅ Request created: {request.user_request[:30]}...")
    print(f"  ✅ Correlation ID: {request.correlation_id}")
    print(f"  ✅ Context: {request.context}")

    # Test 2: Create routing response
    print("\nTest 2: Create routing response...")
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
                    explanation="High confidence match on 'optimize' triggers",
                ),
                reason="Strong trigger match with 'optimize' keyword",
                definition_path="/Users/jonah/.claude/agent-definitions/agent-performance.yaml",
            )
        ],
        routing_metadata=ModelRoutingMetadata(
            routing_time_ms=45,
            cache_hit=False,
            candidates_evaluated=5,
            routing_strategy="enhanced_fuzzy_matching",
        ),
    )
    print(
        f"  ✅ Response created with {len(response.recommendations)} recommendation(s)"
    )
    print(f"  ✅ Selected agent: {response.recommendations[0].agent_name}")
    print(f"  ✅ Confidence: {response.recommendations[0].confidence.total:.2%}")
    print(f"  ✅ Routing time: {response.routing_metadata.routing_time_ms}ms")

    # Test 3: Create routing error
    print("\nTest 3: Create routing error...")
    error = ModelRoutingError(
        correlation_id=correlation_id,
        error_code=ErrorCodes.ROUTING_TIMEOUT,
        error_message="Routing decision exceeded 5000ms timeout",
        retry_after_ms=1000,
    )
    print(f"  ✅ Error created: {error.error_code}")
    print(f"  ✅ Error message: {error.error_message}")
    print(f"  ✅ Retry after: {error.retry_after_ms}ms")

    # Test 4: JSON serialization
    print("\nTest 4: JSON serialization...")
    request_json = request.model_dump_json()
    print(f"  ✅ Request serialized ({len(request_json)} bytes)")

    request_dict = json.loads(request_json)
    request_2 = ModelRoutingRequest(**request_dict)
    print("  ✅ Request deserialized successfully")
    assert request_2.user_request == request.user_request
    print("  ✅ Roundtrip verification passed")

    # Test 5: Validation
    print("\nTest 5: Validation tests...")
    try:
        bad_request = ModelRoutingRequest(
            user_request="",  # Empty user_request should fail
            correlation_id=correlation_id,
        )
        print("  ❌ Validation should have failed for empty user_request")
        sys.exit(1)
    except Exception:
        print("  ✅ Validation correctly rejected empty user_request")

    try:
        bad_request = ModelRoutingRequest(
            user_request="optimize",
            correlation_id="not-a-uuid",  # Invalid UUID should fail
        )
        print("  ❌ Validation should have failed for invalid UUID")
        sys.exit(1)
    except Exception:
        print("  ✅ Validation correctly rejected invalid UUID")

    # Summary
    print("\n" + "=" * 60)
    print("✅ ALL TESTS PASSED")
    print("=" * 60)
    print("\nSchemas are ready for use!")
    print("\nNext steps:")
    print("1. Create routing_event_client.py (Kafka client)")
    print("2. Create agent-router-service (routing service)")
    print("3. Integration tests")
    print("\nCorrelation ID: 50cc9c90-35e6-48cd-befd-91ee3ce4b2b1")

except Exception as e:
    print(f"\n❌ TEST FAILED: {e}")
    import traceback

    traceback.print_exc()
    sys.exit(1)
