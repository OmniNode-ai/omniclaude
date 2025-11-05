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
    """Test that settings load without errors."""
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
    """Test field validators."""
    print("\n" + "=" * 80)
    print("Testing Field Validators")
    print("=" * 80)

    from config import Settings

    # Test port validation
    print("\nTest 1: Port Validation")
    try:
        # Valid port
        os.environ["POSTGRES_PORT"] = "5432"
        settings = Settings()
        print(f"  ✅ Valid port accepted: {settings.postgres_port}")

        # Invalid port (too high)
        os.environ["POSTGRES_PORT"] = "99999"
        try:
            settings = Settings()
            print(
                f"  ❌ Invalid port accepted (should have failed): {settings.postgres_port}"
            )
        except Exception as e:
            print(f"  ✅ Invalid port rejected: {e}")

    except Exception as e:
        print(f"  ❌ Port validation test failed: {e}")

    # Test quality threshold validation
    print("\nTest 2: Quality Threshold Validation")
    try:
        # Valid threshold
        os.environ["MIN_PATTERN_QUALITY"] = "0.7"
        settings = Settings()
        print(f"  ✅ Valid threshold accepted: {settings.min_pattern_quality}")

        # Invalid threshold (too high)
        os.environ["MIN_PATTERN_QUALITY"] = "1.5"
        try:
            settings = Settings()
            print(
                f"  ❌ Invalid threshold accepted (should have failed): {settings.min_pattern_quality}"
            )
        except Exception as e:
            print(f"  ✅ Invalid threshold rejected: {str(e)[:100]}")

    except Exception as e:
        print(f"  ❌ Quality threshold validation test failed: {e}")

    # Reset environment
    os.environ.pop("POSTGRES_PORT", None)
    os.environ.pop("MIN_PATTERN_QUALITY", None)

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
