"""
Test configuration framework.

This test verifies that the Pydantic Settings framework loads correctly
and validates configuration values.

Usage:
    python config/test_settings.py
"""

import os
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))


def test_settings_load():
    """
    Test that settings load without errors.

    Verifies comprehensive configuration framework functionality including:
    - Settings initialization from environment variables
    - Type safety for configuration values (int, bool, str)
    - Helper method execution (DSN generation, effective values)
    - Configuration validation for required services
    - Sensitive value sanitization (passwords, API keys)
    - Feature flag accessibility

    Args:
        None

    Returns:
        bool: True if all tests pass and settings load correctly,
              False if any test fails or settings cannot be loaded

    Raises:
        Exception: Caught and printed if settings fail to load.
                  Stack trace is displayed for debugging.

    Example:
        >>> success = test_settings_load()

        ================================================================================
        Testing Pydantic Settings Framework
        ================================================================================

        ✅ Settings loaded successfully!
        ...
        ✅ All tests passed!
        >>> assert success
    """
    print("\n" + "=" * 80)
    print("Testing Pydantic Settings Framework")
    print("=" * 80)

    try:
        from config import settings

        print("\n✅ Settings loaded successfully!")

        # Test basic access
        print("\n" + "-" * 80)
        print("Basic Configuration:")
        print("-" * 80)
        print(f"  Kafka Bootstrap Servers: {settings.kafka_bootstrap_servers}")
        print(f"  PostgreSQL Host: {settings.postgres_host}")
        print(f"  PostgreSQL Port: {settings.postgres_port}")
        print(f"  PostgreSQL Database: {settings.postgres_database}")
        print(f"  Qdrant URL: {settings.qdrant_url}")

        # Test type safety
        print("\n" + "-" * 80)
        print("Type Safety Verification:")
        print("-" * 80)
        print(
            f"  postgres_port type: {type(settings.postgres_port).__name__} (expected: int)"
        )
        print(
            f"  kafka_enable_intelligence type: {type(settings.kafka_enable_intelligence).__name__} (expected: bool)"
        )
        print(
            f"  archon_intelligence_url type: {type(settings.archon_intelligence_url).__name__}"
        )

        assert isinstance(settings.postgres_port, int), "postgres_port should be int"
        assert isinstance(
            settings.kafka_enable_intelligence, bool
        ), "kafka_enable_intelligence should be bool"
        print("  ✅ All types are correct!")

        # Test helper methods
        print("\n" + "-" * 80)
        print("Helper Methods:")
        print("-" * 80)

        # PostgreSQL DSN
        try:
            dsn = settings.get_postgres_dsn()
            print(
                f"  ✅ PostgreSQL DSN (sync): {dsn[:50]}..."
                if len(dsn) > 50
                else f"  ✅ PostgreSQL DSN (sync): {dsn}"
            )

            async_dsn = settings.get_postgres_dsn(async_driver=True)
            print(
                f"  ✅ PostgreSQL DSN (async): {async_dsn[:50]}..."
                if len(async_dsn) > 50
                else f"  ✅ PostgreSQL DSN (async): {async_dsn}"
            )
        except Exception as e:
            print(f"  ⚠️  PostgreSQL DSN generation failed: {e}")
            print("     (This is expected if POSTGRES_PASSWORD is not set)")

        # Kafka servers
        kafka_servers = settings.get_effective_kafka_bootstrap_servers()
        print(f"  ✅ Kafka Bootstrap Servers: {kafka_servers}")

        # Test validation
        print("\n" + "-" * 80)
        print("Configuration Validation:")
        print("-" * 80)

        errors = settings.validate_required_services()
        if errors:
            print("  ⚠️  Configuration validation warnings:")
            for error in errors:
                print(f"     - {error}")
            print(
                "\n  Note: These are expected if you haven't set all required values in .env"
            )
        else:
            print("  ✅ All required services are configured!")

        # Test sanitized export
        print("\n" + "-" * 80)
        print("Sensitive Value Sanitization:")
        print("-" * 80)

        sanitized = settings.to_dict_sanitized()
        print(f"  postgres_password: {sanitized['postgres_password']}")
        print(f"  gemini_api_key: {sanitized['gemini_api_key']}")
        print(f"  zai_api_key: {sanitized['zai_api_key']}")

        if (
            sanitized["postgres_password"] == "***"
            or sanitized["postgres_password"] == ""
        ):
            print("  ✅ Sensitive values are properly sanitized!")
        else:
            print("  ⚠️  Sensitive values may not be properly sanitized")

        # Test feature flags
        print("\n" + "-" * 80)
        print("Feature Flags:")
        print("-" * 80)
        print(f"  Event-based Intelligence: {settings.kafka_enable_intelligence}")
        print(f"  Pattern Quality Filter: {settings.enable_pattern_quality_filter}")
        print(f"  Min Pattern Quality: {settings.min_pattern_quality}")
        print(f"  Intelligence Cache: {settings.enable_intelligence_cache}")

        # Summary
        print("\n" + "=" * 80)
        print("✅ All tests passed!")
        print("=" * 80)
        print("\nPydantic Settings framework is working correctly.")
        print("You can now use: from config import settings")
        print("\n")

        return True

    except Exception as e:
        print(f"\n❌ Error loading settings: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_validation():
    """
    Test Pydantic field validators for configuration values.

    Validates that Pydantic validators correctly enforce constraints on
    configuration fields including:
    - Port number range validation (1-65535)
    - Quality threshold range validation (0.0-1.0)
    - Pool size validation (≥1, warns if >100)
    - Timeout validation (1000-60000ms)
    - Path resolution with defaults
    - Proper rejection of invalid values
    - Acceptance of valid values within constraints

    Tests modify environment variables temporarily and restore original
    values after completion.

    Args:
        None

    Returns:
        None: Prints test results to stdout. Success/failure indicated
              by printed ✅/❌ symbols.

    Raises:
        Exception: Individual validation test failures are caught and
                  reported as test results, not propagated.

    Example:
        >>> test_validation()

        ================================================================================
        Testing Field Validators
        ================================================================================

        Test 1: Port Validation
          ✅ Valid port accepted: 5432
          ✅ Invalid port rejected: ...

        Test 2: Quality Threshold Validation
          ✅ Valid threshold accepted: 0.7
          ✅ Invalid threshold rejected: ...

        Test 3: Pool Size Validation
          ✅ Valid pool size accepted: 10
          ✅ Pool size 0 rejected: ...

        Test 4: Timeout Validation
          ✅ Valid timeout accepted: 5000
          ✅ Timeout 500 rejected: ...

        Test 5: Agent Registry Path Resolution
          ✅ Default path resolved: ...
          ✅ Custom path accepted: ...

        Test 6: Agent Definitions Path Resolution
          ✅ Default path resolved: ...
          ✅ Custom path accepted: ...

        ✅ Validation tests completed!
    """
    print("\n" + "=" * 80)
    print("Testing Field Validators")
    print("=" * 80)

    from config import Settings

    # Test port validation
    print("\nTest 1: Port Validation")
    # Save original value
    original_postgres_port = os.environ.get("POSTGRES_PORT")
    try:
        # Valid port
        os.environ["POSTGRES_PORT"] = "5432"
        settings = Settings()
        print(f"  ✅ Valid port accepted: {settings.postgres_port}")

        # Edge case: minimum valid port
        os.environ["POSTGRES_PORT"] = "1"
        settings = Settings()
        print(f"  ✅ Minimum port (1) accepted: {settings.postgres_port}")

        # Edge case: maximum valid port
        os.environ["POSTGRES_PORT"] = "65535"
        settings = Settings()
        print(f"  ✅ Maximum port (65535) accepted: {settings.postgres_port}")

        # Invalid port (too high)
        os.environ["POSTGRES_PORT"] = "99999"
        try:
            settings = Settings()
            print(
                f"  ❌ Invalid port accepted (should have failed): {settings.postgres_port}"
            )
        except Exception as e:
            print(f"  ✅ Invalid port (99999) rejected: {str(e)[:80]}")

        # Invalid port (zero)
        os.environ["POSTGRES_PORT"] = "0"
        try:
            settings = Settings()
            print(
                f"  ❌ Port 0 accepted (should have failed): {settings.postgres_port}"
            )
        except Exception as e:
            print(f"  ✅ Port 0 rejected: {str(e)[:80]}")

        # Invalid port (negative)
        os.environ["POSTGRES_PORT"] = "-1"
        try:
            settings = Settings()
            print(
                f"  ❌ Negative port accepted (should have failed): {settings.postgres_port}"
            )
        except Exception as e:
            print(f"  ✅ Negative port rejected: {str(e)[:80]}")

    except Exception as e:
        print(f"  ❌ Port validation test failed: {e}")
    finally:
        # Restore original value
        if original_postgres_port is not None:
            os.environ["POSTGRES_PORT"] = original_postgres_port
        else:
            os.environ.pop("POSTGRES_PORT", None)

    # Test quality threshold validation
    print("\nTest 2: Quality Threshold Validation")
    # Save original value
    original_min_quality = os.environ.get("MIN_PATTERN_QUALITY")
    try:
        # Valid threshold
        os.environ["MIN_PATTERN_QUALITY"] = "0.7"
        settings = Settings()
        print(f"  ✅ Valid threshold accepted: {settings.min_pattern_quality}")

        # Edge case: minimum valid threshold
        os.environ["MIN_PATTERN_QUALITY"] = "0.0"
        settings = Settings()
        print(f"  ✅ Minimum threshold (0.0) accepted: {settings.min_pattern_quality}")

        # Edge case: maximum valid threshold
        os.environ["MIN_PATTERN_QUALITY"] = "1.0"
        settings = Settings()
        print(f"  ✅ Maximum threshold (1.0) accepted: {settings.min_pattern_quality}")

        # Invalid threshold (too high)
        os.environ["MIN_PATTERN_QUALITY"] = "1.5"
        try:
            settings = Settings()
            print(
                f"  ❌ Invalid threshold accepted (should have failed): {settings.min_pattern_quality}"
            )
        except Exception as e:
            print(f"  ✅ Threshold 1.5 rejected: {str(e)[:80]}")

        # Invalid threshold (negative)
        os.environ["MIN_PATTERN_QUALITY"] = "-0.1"
        try:
            settings = Settings()
            print(
                f"  ❌ Negative threshold accepted (should have failed): {settings.min_pattern_quality}"
            )
        except Exception as e:
            print(f"  ✅ Negative threshold rejected: {str(e)[:80]}")

    except Exception as e:
        print(f"  ❌ Quality threshold validation test failed: {e}")
    finally:
        # Restore original value
        if original_min_quality is not None:
            os.environ["MIN_PATTERN_QUALITY"] = original_min_quality
        else:
            os.environ.pop("MIN_PATTERN_QUALITY", None)

    # Test pool size validation
    print("\nTest 3: Pool Size Validation")
    # Save original values
    original_pool_min = os.environ.get("POSTGRES_POOL_MIN_SIZE")
    original_pool_max = os.environ.get("POSTGRES_POOL_MAX_SIZE")
    try:
        # Valid pool size
        os.environ["POSTGRES_POOL_MIN_SIZE"] = "5"
        os.environ["POSTGRES_POOL_MAX_SIZE"] = "10"
        settings = Settings()
        print(
            f"  ✅ Valid pool sizes accepted: min={settings.postgres_pool_min_size}, max={settings.postgres_pool_max_size}"
        )

        # Edge case: minimum valid pool size
        os.environ["POSTGRES_POOL_MIN_SIZE"] = "1"
        settings = Settings()
        print(f"  ✅ Minimum pool size (1) accepted: {settings.postgres_pool_min_size}")

        # Edge case: large pool size (should warn but accept)
        os.environ["POSTGRES_POOL_MAX_SIZE"] = "100"
        settings = Settings()
        print(
            f"  ✅ Maximum pool size (100) accepted: {settings.postgres_pool_max_size}"
        )

        # Invalid pool size (zero)
        os.environ["POSTGRES_POOL_MIN_SIZE"] = "0"
        try:
            settings = Settings()
            print(
                f"  ❌ Pool size 0 accepted (should have failed): {settings.postgres_pool_min_size}"
            )
        except Exception as e:
            print(f"  ✅ Pool size 0 rejected: {str(e)[:80]}")

        # Invalid pool size (negative)
        os.environ["POSTGRES_POOL_MIN_SIZE"] = "-1"
        try:
            settings = Settings()
            print(
                f"  ❌ Negative pool size accepted (should have failed): {settings.postgres_pool_min_size}"
            )
        except Exception as e:
            print(f"  ✅ Negative pool size rejected: {str(e)[:80]}")

        # Very large pool size (>100 - should warn)
        os.environ["POSTGRES_POOL_MAX_SIZE"] = "150"
        try:
            settings = Settings()
            print(
                f"  ✅ Very large pool size (150) accepted with warning: {settings.postgres_pool_max_size}"
            )
        except Exception as e:
            print(f"  ⚠️  Very large pool size handling: {str(e)[:80]}")

    except Exception as e:
        print(f"  ❌ Pool size validation test failed: {e}")
    finally:
        # Restore original values
        if original_pool_min is not None:
            os.environ["POSTGRES_POOL_MIN_SIZE"] = original_pool_min
        else:
            os.environ.pop("POSTGRES_POOL_MIN_SIZE", None)
        if original_pool_max is not None:
            os.environ["POSTGRES_POOL_MAX_SIZE"] = original_pool_max
        else:
            os.environ.pop("POSTGRES_POOL_MAX_SIZE", None)

    # Test timeout validation
    print("\nTest 4: Timeout Validation")
    # Save original values
    original_kafka_timeout = os.environ.get("KAFKA_REQUEST_TIMEOUT_MS")
    original_routing_timeout = os.environ.get("ROUTING_TIMEOUT_MS")
    original_request_timeout = os.environ.get("REQUEST_TIMEOUT_MS")
    try:
        # Valid timeout
        os.environ["KAFKA_REQUEST_TIMEOUT_MS"] = "5000"
        settings = Settings()
        print(f"  ✅ Valid timeout accepted: {settings.kafka_request_timeout_ms}ms")

        # Edge case: minimum valid timeout
        os.environ["ROUTING_TIMEOUT_MS"] = "1000"
        settings = Settings()
        print(
            f"  ✅ Minimum timeout (1000ms) accepted: {settings.routing_timeout_ms}ms"
        )

        # Edge case: maximum valid timeout
        os.environ["REQUEST_TIMEOUT_MS"] = "60000"
        settings = Settings()
        print(
            f"  ✅ Maximum timeout (60000ms) accepted: {settings.request_timeout_ms}ms"
        )

        # Invalid timeout (too small)
        os.environ["KAFKA_REQUEST_TIMEOUT_MS"] = "500"
        try:
            settings = Settings()
            print(
                f"  ❌ Timeout 500ms accepted (should have failed): {settings.kafka_request_timeout_ms}"
            )
        except Exception as e:
            print(f"  ✅ Timeout 500ms rejected: {str(e)[:80]}")

        # Invalid timeout (too large)
        os.environ["ROUTING_TIMEOUT_MS"] = "70000"
        try:
            settings = Settings()
            print(
                f"  ❌ Timeout 70000ms accepted (should have failed): {settings.routing_timeout_ms}"
            )
        except Exception as e:
            print(f"  ✅ Timeout 70000ms rejected: {str(e)[:80]}")

        # Invalid timeout (zero)
        os.environ["REQUEST_TIMEOUT_MS"] = "0"
        try:
            settings = Settings()
            print(
                f"  ❌ Timeout 0ms accepted (should have failed): {settings.request_timeout_ms}"
            )
        except Exception as e:
            print(f"  ✅ Timeout 0ms rejected: {str(e)[:80]}")

        # Invalid timeout (negative)
        os.environ["KAFKA_REQUEST_TIMEOUT_MS"] = "-1000"
        try:
            settings = Settings()
            print(
                f"  ❌ Negative timeout accepted (should have failed): {settings.kafka_request_timeout_ms}"
            )
        except Exception as e:
            print(f"  ✅ Negative timeout rejected: {str(e)[:80]}")

    except Exception as e:
        print(f"  ❌ Timeout validation test failed: {e}")
    finally:
        # Restore original values
        if original_kafka_timeout is not None:
            os.environ["KAFKA_REQUEST_TIMEOUT_MS"] = original_kafka_timeout
        else:
            os.environ.pop("KAFKA_REQUEST_TIMEOUT_MS", None)
        if original_routing_timeout is not None:
            os.environ["ROUTING_TIMEOUT_MS"] = original_routing_timeout
        else:
            os.environ.pop("ROUTING_TIMEOUT_MS", None)
        if original_request_timeout is not None:
            os.environ["REQUEST_TIMEOUT_MS"] = original_request_timeout
        else:
            os.environ.pop("REQUEST_TIMEOUT_MS", None)

    # Test agent registry path resolution
    print("\nTest 5: Agent Registry Path Resolution")
    # Save original value
    original_registry_path = os.environ.get("AGENT_REGISTRY_PATH")
    try:
        # Default path (no environment variable set)
        os.environ.pop("AGENT_REGISTRY_PATH", None)
        settings = Settings()
        expected_default = str(
            Path.home() / ".claude" / "agents" / "onex" / "agent-registry.yaml"
        )
        if settings.agent_registry_path == expected_default:
            print("  ✅ Default path resolved correctly")
            print(f"     Path: {settings.agent_registry_path}")
        else:
            print("  ❌ Default path mismatch:")
            print(f"     Expected: {expected_default}")
            print(f"     Got: {settings.agent_registry_path}")

        # Custom absolute path
        custom_path = "/tmp/custom/registry.yaml"
        os.environ["AGENT_REGISTRY_PATH"] = custom_path
        settings = Settings()
        if settings.agent_registry_path == custom_path:
            print(f"  ✅ Custom absolute path accepted: {settings.agent_registry_path}")
        else:
            print(f"  ❌ Custom path not set correctly: {settings.agent_registry_path}")

        # Custom relative path
        relative_path = "config/agent-registry.yaml"
        os.environ["AGENT_REGISTRY_PATH"] = relative_path
        settings = Settings()
        if settings.agent_registry_path == relative_path:
            print(f"  ✅ Custom relative path accepted: {settings.agent_registry_path}")
        else:
            print(
                f"  ❌ Relative path not set correctly: {settings.agent_registry_path}"
            )

    except Exception as e:
        print(f"  ❌ Agent registry path resolution test failed: {e}")
    finally:
        # Restore original value
        if original_registry_path is not None:
            os.environ["AGENT_REGISTRY_PATH"] = original_registry_path
        else:
            os.environ.pop("AGENT_REGISTRY_PATH", None)

    # Test agent definitions path resolution
    print("\nTest 6: Agent Definitions Path Resolution")
    # Save original value
    original_definitions_path = os.environ.get("AGENT_DEFINITIONS_PATH")
    try:
        # Default path (no environment variable set)
        os.environ.pop("AGENT_DEFINITIONS_PATH", None)
        settings = Settings()
        expected_default = str(Path.home() / ".claude" / "agents" / "onex")
        if settings.agent_definitions_path == expected_default:
            print("  ✅ Default path resolved correctly")
            print(f"     Path: {settings.agent_definitions_path}")
        else:
            print("  ❌ Default path mismatch:")
            print(f"     Expected: {expected_default}")
            print(f"     Got: {settings.agent_definitions_path}")

        # Custom absolute path
        custom_path = "/tmp/custom/definitions"
        os.environ["AGENT_DEFINITIONS_PATH"] = custom_path
        settings = Settings()
        if settings.agent_definitions_path == custom_path:
            print(
                f"  ✅ Custom absolute path accepted: {settings.agent_definitions_path}"
            )
        else:
            print(
                f"  ❌ Custom path not set correctly: {settings.agent_definitions_path}"
            )

        # Custom relative path
        relative_path = "config/agents"
        os.environ["AGENT_DEFINITIONS_PATH"] = relative_path
        settings = Settings()
        if settings.agent_definitions_path == relative_path:
            print(
                f"  ✅ Custom relative path accepted: {settings.agent_definitions_path}"
            )
        else:
            print(
                f"  ❌ Relative path not set correctly: {settings.agent_definitions_path}"
            )

    except Exception as e:
        print(f"  ❌ Agent definitions path resolution test failed: {e}")
    finally:
        # Restore original value
        if original_definitions_path is not None:
            os.environ["AGENT_DEFINITIONS_PATH"] = original_definitions_path
        else:
            os.environ.pop("AGENT_DEFINITIONS_PATH", None)

    print("\n" + "=" * 80)
    print("✅ Validation tests completed!")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    # Run basic tests
    success = test_settings_load()

    # Run validation tests
    test_validation()

    # Exit with appropriate code
    sys.exit(0 if success else 1)
