#!/usr/bin/env python3
"""
Test script to validate environment variable handling improvements
in validated_task_architect.py

Verifies:
1. Configuration validation at startup
2. Clear error messages for missing variables
3. Type-safe config usage
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))


def test_config_import():
    """Test that config module can be imported"""
    print("Test 1: Config module import...")
    try:
        from config import settings

        print("  ✓ Config module imported successfully")
        return True
    except ImportError as e:
        print(f"  ✗ Failed to import config: {e}")
        return False


def test_api_keys_validation():
    """Test that API keys are validated"""
    print("\nTest 2: API key validation...")
    try:
        from config import settings

        # Check if keys are set
        has_gemini = bool(settings.gemini_api_key)
        has_zai = bool(settings.zai_api_key)

        print(f"  GEMINI_API_KEY: {'✓ SET' if has_gemini else '✗ NOT SET'}")
        print(f"  ZAI_API_KEY: {'✓ SET' if has_zai else '✗ NOT SET'}")

        if has_gemini and has_zai:
            print("  ✓ All required API keys are set")
            return True
        else:
            print("  ⚠ Some API keys are missing (validation should catch this)")
            return False
    except Exception as e:
        print(f"  ✗ Error checking API keys: {e}")
        return False


def test_quorum_validator_init():
    """Test that QuorumValidator can be initialized"""
    print("\nTest 3: QuorumValidator initialization...")
    try:
        # This import will fail if API keys are not set
        from agents.parallel_execution.quorum_validator import QuorumValidator

        validator = QuorumValidator()
        print("  ✓ QuorumValidator initialized successfully")
        print(f"    Configured models: {list(validator.models.keys())}")
        return True
    except ValueError as e:
        print(
            f"  ✗ QuorumValidator initialization failed (expected if keys not set): {e}"
        )
        return False
    except ImportError as e:
        print(f"  ✗ Failed to import QuorumValidator: {e}")
        return False


def test_validated_architect_import():
    """Test that ValidatedTaskArchitect can be imported"""
    print("\nTest 4: ValidatedTaskArchitect import...")
    try:
        from agents.parallel_execution.validated_task_architect import (
            ValidatedTaskArchitect,
        )

        print("  ✓ ValidatedTaskArchitect imported successfully")
        return True
    except SystemExit:
        print(
            "  ✗ ValidatedTaskArchitect exited during import (config validation failed)"
        )
        return False
    except ImportError as e:
        print(f"  ✗ Failed to import ValidatedTaskArchitect: {e}")
        return False


def test_config_values():
    """Test that config values are accessible and type-safe"""
    print("\nTest 5: Config values access...")
    try:
        from config import settings

        # Test various config values
        print(
            f"  postgres_host: {settings.postgres_host} (type: {type(settings.postgres_host).__name__})"
        )
        print(
            f"  postgres_port: {settings.postgres_port} (type: {type(settings.postgres_port).__name__})"
        )
        print(f"  kafka_bootstrap_servers: {settings.kafka_bootstrap_servers}")

        # Verify types
        assert isinstance(settings.postgres_host, str), "postgres_host should be str"
        assert isinstance(settings.postgres_port, int), "postgres_port should be int"
        assert isinstance(
            settings.kafka_bootstrap_servers, str
        ), "kafka_bootstrap_servers should be str"

        print("  ✓ All config values are type-safe and accessible")
        return True
    except Exception as e:
        print(f"  ✗ Error accessing config values: {e}")
        return False


def main():
    """Run all validation tests"""
    print("=" * 70)
    print("CONFIG VALIDATION TEST SUITE")
    print("=" * 70)
    print()

    tests = [
        test_config_import,
        test_api_keys_validation,
        test_config_values,
        test_quorum_validator_init,
        test_validated_architect_import,
    ]

    results = []
    for test in tests:
        try:
            result = test()
            results.append(result)
        except Exception as e:
            print(f"  ✗ Test failed with exception: {e}")
            results.append(False)

    # Summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    passed = sum(results)
    total = len(results)
    print(f"Passed: {passed}/{total}")

    if passed == total:
        print("\n✓ All tests passed!")
        return 0
    else:
        print(f"\n⚠ {total - passed} test(s) failed")
        print("\nNote: Some failures are expected if API keys are not configured.")
        print("See .env.example and SECURITY_KEY_ROTATION.md for setup instructions.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
