#!/usr/bin/env python3
"""
Test script to validate production configuration enforcement.

This script tests that:
1. Production mode raises ValueError on invalid configuration
2. Development mode logs but continues on invalid configuration
3. Valid configuration works in all environments

Usage:
    python3 config/test_production_validation.py
"""

import os
import sys
from functools import lru_cache

# Import at module level for proper cache clearing
from config.settings import get_settings


# Clear the lru_cache before each test
def clear_settings_cache():
    """Clear the get_settings cache to allow fresh initialization."""
    get_settings.cache_clear()


def test_production_invalid_config():
    """Test that production mode raises ValueError with invalid config."""
    print("=" * 70)
    print("TEST 1: Production mode with invalid configuration")
    print("=" * 70)

    # Set environment to production with missing required config
    os.environ["ENVIRONMENT"] = "production"
    # Set password env vars to empty to trigger validation error
    # (must override .env file values with empty strings, not just unset)
    os.environ["POSTGRES_PASSWORD"] = ""
    os.environ["PG_PASSWORD"] = ""
    os.environ["DATABASE_PASSWORD"] = ""
    # Set Kafka to empty to trigger another validation error
    os.environ["KAFKA_BOOTSTRAP_SERVERS"] = ""

    clear_settings_cache()

    try:
        settings = get_settings()
        print("❌ FAILED: Expected ValueError but no exception was raised")
        print(f"   DEBUG: environment={settings.environment}")
        print(f"   DEBUG: postgres_password set={bool(settings.postgres_password)}")
        print(f"   DEBUG: kafka_bootstrap_servers={settings.kafka_bootstrap_servers}")
        errors = settings.validate_required_services()
        print(f"   DEBUG: validation errors={errors}")
        return False
    except ValueError as e:
        if "production mode" in str(e).lower():
            print(f"✅ PASSED: Production mode raised ValueError as expected")
            print(f"   Error message: {str(e)[:100]}...")
            return True
        else:
            print(f"❌ FAILED: ValueError raised but wrong message: {e}")
            return False
    except Exception as e:
        print(f"❌ FAILED: Wrong exception type: {type(e).__name__}: {e}")
        return False


def test_development_invalid_config():
    """Test that development mode logs but continues with invalid config."""
    print("\n" + "=" * 70)
    print("TEST 2: Development mode with invalid configuration")
    print("=" * 70)

    # Set environment to development with missing required config
    os.environ["ENVIRONMENT"] = "development"
    # Set password env vars to empty to trigger validation error
    # (must override .env file values with empty strings, not just unset)
    os.environ["POSTGRES_PASSWORD"] = ""
    os.environ["PG_PASSWORD"] = ""
    os.environ["DATABASE_PASSWORD"] = ""
    # Set Kafka to empty to trigger another validation error
    os.environ["KAFKA_BOOTSTRAP_SERVERS"] = ""

    clear_settings_cache()

    try:
        settings = get_settings()
        print("✅ PASSED: Development mode logged errors but continued")
        print(f"   Settings loaded: environment={settings.environment}")
        return True
    except ValueError as e:
        print(f"❌ FAILED: Development mode should not raise ValueError: {e}")
        return False
    except Exception as e:
        print(f"❌ FAILED: Unexpected exception: {type(e).__name__}: {e}")
        return False


def test_production_valid_config():
    """Test that production mode works with valid configuration."""
    print("\n" + "=" * 70)
    print("TEST 3: Production mode with valid configuration")
    print("=" * 70)

    # Set environment to production with valid config
    os.environ["ENVIRONMENT"] = "production"
    os.environ["POSTGRES_HOST"] = "192.168.86.200"
    os.environ["POSTGRES_PORT"] = "5436"
    os.environ["POSTGRES_DATABASE"] = "omninode_bridge"
    os.environ["POSTGRES_USER"] = "postgres"
    os.environ["POSTGRES_PASSWORD"] = "test_password"  # Required for validation
    os.environ["KAFKA_BOOTSTRAP_SERVERS"] = "omninode-bridge-redpanda:9092"

    clear_settings_cache()

    try:
        settings = get_settings()
        print("✅ PASSED: Production mode loaded valid configuration successfully")
        print(
            f"   Settings loaded: environment={settings.environment}, postgres_host={settings.postgres_host}"
        )
        return True
    except ValueError as e:
        print(f"❌ FAILED: Valid config should not raise ValueError: {e}")
        return False
    except Exception as e:
        print(f"❌ FAILED: Unexpected exception: {type(e).__name__}: {e}")
        return False


def main():
    """Run all validation tests."""
    print("\n" + "=" * 70)
    print("PRODUCTION CONFIGURATION VALIDATION TEST SUITE")
    print("=" * 70)
    print()

    # Store original environment
    original_env = os.environ.copy()

    try:
        results = []

        # Run tests
        results.append(("Production Invalid Config", test_production_invalid_config()))
        results.append(
            ("Development Invalid Config", test_development_invalid_config())
        )
        results.append(("Production Valid Config", test_production_valid_config()))

        # Summary
        print("\n" + "=" * 70)
        print("TEST SUMMARY")
        print("=" * 70)

        passed = sum(1 for _, result in results if result)
        total = len(results)

        for test_name, result in results:
            status = "✅ PASSED" if result else "❌ FAILED"
            print(f"{status}: {test_name}")

        print()
        print(f"Results: {passed}/{total} tests passed")

        if passed == total:
            print("\n🎉 All tests passed! Production validation is working correctly.")
            return 0
        else:
            print(f"\n⚠️  {total - passed} test(s) failed. Review output above.")
            return 1

    finally:
        # Restore original environment
        os.environ.clear()
        os.environ.update(original_env)
        clear_settings_cache()


if __name__ == "__main__":
    sys.exit(main())
