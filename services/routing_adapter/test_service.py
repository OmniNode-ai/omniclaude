"""
Test script for Routing Adapter Service.

Validates that the service can be imported and initialized without errors.
Does NOT start the actual Kafka consumer (requires Kafka to be running).

Usage:
    python3 test_service.py
"""

import asyncio
import sys
from pathlib import Path


# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))


async def test_service():
    """Test service initialization."""
    print("=" * 60)
    print("Routing Adapter Service - Initialization Test")
    print("=" * 60)

    # Test 1: Import modules
    print("\n1. Testing imports...")
    try:
        from services.routing_adapter import (
            RoutingAdapterService,
            RoutingHandler,
            get_config,
        )

        print("   ✅ All modules imported successfully")
    except Exception as e:
        print(f"   ❌ Import failed: {e}")
        return False

    # Test 2: Load configuration
    print("\n2. Testing configuration...")
    try:
        config = get_config()
        print("   ✅ Configuration loaded")
        print(f"      - Kafka: {config.kafka_bootstrap_servers}")
        print(f"      - PostgreSQL: {config.postgres_host}:{config.postgres_port}")
        print(f"      - Service: http://{config.service_host}:{config.service_port}")
    except Exception as e:
        print(f"   ❌ Configuration failed: {e}")
        return False

    # Test 3: Initialize RoutingHandler
    print("\n3. Testing RoutingHandler...")
    try:
        handler = RoutingHandler()
        await handler.initialize()
        print("   ✅ RoutingHandler initialized")

        # Test routing
        test_event = {
            "correlation_id": "test-init-123",
            "user_request": "Create a database schema for user management",
            "context": {},
        }
        response = await handler.handle_routing_request(test_event)
        print("   ✅ Test routing request succeeded")
        print(f"      - Selected: {response['selected_agent']}")
        print(f"      - Confidence: {response['confidence']:.2%}")
        print(f"      - Time: {response['routing_time_ms']}ms")

        await handler.shutdown()
    except Exception as e:
        print(f"   ❌ RoutingHandler failed: {e}")
        import traceback

        traceback.print_exc()
        return False

    # Test 4: Create service instance (without starting Kafka)
    print("\n4. Testing service instantiation...")
    try:
        service = RoutingAdapterService()
        print("   ✅ Service instance created")
        print(f"      - Config loaded: {service.config is not None}")
        print(f"      - Initial status: {service._health_status['status']}")
    except Exception as e:
        print(f"   ❌ Service instantiation failed: {e}")
        import traceback

        traceback.print_exc()
        return False

    # Summary
    print("\n" + "=" * 60)
    print("✅ All tests passed!")
    print("=" * 60)
    print("\nService is ready to run. To start the service:")
    print("  python3 -m services.routing_adapter.routing_adapter_service")
    print("\nNote: Requires Kafka to be running at", config.kafka_bootstrap_servers)
    print("=" * 60)

    return True


if __name__ == "__main__":
    import os

    # Ensure required environment variables are set
    required_vars = ["POSTGRES_PASSWORD", "KAFKA_BOOTSTRAP_SERVERS"]
    missing_vars = [var for var in required_vars if not os.getenv(var)]

    if missing_vars:
        print("❌ Missing required environment variables:")
        for var in missing_vars:
            print(f"   - {var}")
        print("\nPlease set these variables or run: source .env")
        sys.exit(1)

    # Run tests
    success = asyncio.run(test_service())
    sys.exit(0 if success else 1)
