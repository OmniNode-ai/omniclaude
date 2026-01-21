#!/usr/bin/env python3
"""
Test script for Environment Variable Configuration Validator.

This script verifies that:
1. validate_required_env_vars() detects all missing variables
2. validate_required_env_vars() passes when all variables are set
3. validate_env_var_format() validates format correctly
4. get_env_var_with_validation() handles required and optional variables
5. Error messages are helpful and guide users to fix configuration
6. Additional variables can be validated alongside required ones
7. Non-strict mode provides warnings instead of errors

Usage:
    python3 agents/lib/test_config_validator.py
    python3 agents/lib/test_config_validator.py -v  # Verbose output
"""

import logging
import os
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from config_validator import (
    REQUIRED_ENV_VARS,
    get_env_var_with_validation,
    validate_env_var_format,
    validate_required_env_vars,
    validate_with_diagnostics,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger(__name__)


# =============================================================================
# Test Functions
# =============================================================================


def test_missing_variables():
    """Test 1: Detect all missing environment variables."""
    logger.info("=" * 70)
    logger.info("Test 1: Detect all missing environment variables")
    logger.info("=" * 70)

    # Save current environment
    saved_env = {}
    for var in REQUIRED_ENV_VARS:
        saved_env[var] = os.environ.pop(var, None)

    try:
        # Should raise EnvironmentError with all missing variables
        validate_required_env_vars()
        logger.error("❌ FAILED: Should have raised EnvironmentError")
        return False
    except OSError as e:
        error_msg = str(e)

        # Check that all variables are listed in error
        all_listed = all(var in error_msg for var in REQUIRED_ENV_VARS)

        if all_listed:
            logger.info("✅ PASSED: All missing variables detected")
            logger.info(f"Error message preview:\n{error_msg[:200]}...")
            return True
        else:
            logger.error("❌ FAILED: Not all variables listed in error")
            missing = [var for var in REQUIRED_ENV_VARS if var not in error_msg]
            logger.error(f"Missing from error: {missing}")
            return False
    finally:
        # Restore environment
        for var, value in saved_env.items():
            if value is not None:
                os.environ[var] = value


def test_all_variables_set():
    """Test 2: Validation passes when all variables are set."""
    logger.info("=" * 70)
    logger.info("Test 2: Validation passes when all variables are set")
    logger.info("=" * 70)

    # Save current environment
    saved_env = {}
    for var in REQUIRED_ENV_VARS:
        saved_env[var] = os.environ.get(var)

    # Set all required variables
    test_values = {
        "POSTGRES_HOST": "192.168.86.200",
        "POSTGRES_PORT": "5436",
        "POSTGRES_PASSWORD": "test_password",
        "KAFKA_BOOTSTRAP_SERVERS": "192.168.86.200:9092",
        "QDRANT_URL": "http://localhost:6333",
    }

    for var, value in test_values.items():
        os.environ[var] = value

    try:
        # Should not raise any errors
        validate_required_env_vars()
        logger.info("✅ PASSED: Validation succeeded with all variables set")
        return True
    except OSError as e:
        logger.error(f"❌ FAILED: Unexpected error: {e}")
        return False
    finally:
        # Restore environment
        for var, value in saved_env.items():
            if value is not None:
                os.environ[var] = value
            else:
                os.environ.pop(var, None)


def test_format_validation():
    """Test 3: Format validation for host:port pattern."""
    logger.info("=" * 70)
    logger.info("Test 3: Format validation for host:port pattern")
    logger.info("=" * 70)

    test_cases = [
        # (value, expected_format, should_pass)
        ("192.168.86.200:9092", "host:port", True),
        ("localhost:6333", "host:port", True),
        ("invalid_no_port", "host:port", False),
        ("http://localhost:6333", "http://host:port", True),
        ("localhost:6333", "http://host:port", False),
    ]

    all_passed = True

    for value, expected_format, should_pass in test_cases:
        # Save current value
        saved_value = os.environ.get("TEST_VAR")

        os.environ["TEST_VAR"] = value

        try:
            validate_env_var_format("TEST_VAR", expected_format)

            if should_pass:
                logger.info(f"✅ PASSED: '{value}' validated as '{expected_format}'")
            else:
                logger.error(f"❌ FAILED: '{value}' should have failed validation")
                all_passed = False

        except OSError as e:
            if not should_pass:
                logger.info(f"✅ PASSED: '{value}' correctly rejected")
            else:
                logger.error(f"❌ FAILED: '{value}' should have passed validation")
                logger.error(f"Error: {e}")
                all_passed = False

        finally:
            # Restore environment
            if saved_value is not None:
                os.environ["TEST_VAR"] = saved_value
            else:
                os.environ.pop("TEST_VAR", None)

    return all_passed


def test_get_with_validation():
    """Test 4: get_env_var_with_validation() handles required and optional variables."""
    logger.info("=" * 70)
    logger.info("Test 4: get_env_var_with_validation() function")
    logger.info("=" * 70)

    all_passed = True

    # Test 4a: Required variable that exists
    os.environ["TEST_VAR"] = "test_value"
    try:
        value = get_env_var_with_validation("TEST_VAR", required=True)
        if value == "test_value":
            logger.info("✅ PASSED: Required variable retrieved successfully")
        else:
            logger.error(f"❌ FAILED: Got wrong value: {value}")
            all_passed = False
    except OSError as e:
        logger.error(f"❌ FAILED: Should not raise error: {e}")
        all_passed = False
    finally:
        os.environ.pop("TEST_VAR", None)

    # Test 4b: Required variable with default
    try:
        value = get_env_var_with_validation(
            "NONEXISTENT_VAR", default="default_value", required=True
        )
        if value == "default_value":
            logger.info("✅ PASSED: Default value used for required variable")
        else:
            logger.error(f"❌ FAILED: Got wrong value: {value}")
            all_passed = False
    except OSError as e:
        logger.error(f"❌ FAILED: Should not raise error with default: {e}")
        all_passed = False

    # Test 4c: Required variable that doesn't exist (should fail)
    try:
        value = get_env_var_with_validation("NONEXISTENT_VAR", required=True)
        logger.error("❌ FAILED: Should have raised error for missing required var")
        all_passed = False
    except OSError:
        logger.info("✅ PASSED: Missing required variable raises error")

    # Test 4d: Optional variable that doesn't exist
    try:
        value = get_env_var_with_validation("NONEXISTENT_VAR", required=False)
        if value is None:
            logger.info("✅ PASSED: Optional missing variable returns None")
        else:
            logger.error(f"❌ FAILED: Expected None, got: {value}")
            all_passed = False
    except OSError as e:
        logger.error(f"❌ FAILED: Should not raise error for optional: {e}")
        all_passed = False

    return all_passed


def test_additional_variables():
    """Test 5: Additional variables can be validated alongside required ones."""
    logger.info("=" * 70)
    logger.info("Test 5: Validate additional custom variables")
    logger.info("=" * 70)

    # Save current environment
    saved_env = {}
    for var in REQUIRED_ENV_VARS + ["CUSTOM_VAR_1", "CUSTOM_VAR_2"]:
        saved_env[var] = os.environ.pop(var, None)

    # Set all required variables
    test_values = {
        "POSTGRES_HOST": "192.168.86.200",
        "POSTGRES_PORT": "5436",
        "POSTGRES_PASSWORD": "test_password",
        "KAFKA_BOOTSTRAP_SERVERS": "192.168.86.200:9092",
        "QDRANT_URL": "http://localhost:6333",
        "CUSTOM_VAR_1": "value1",
        # CUSTOM_VAR_2 intentionally missing
    }

    for var, value in test_values.items():
        os.environ[var] = value

    try:
        # Should fail because CUSTOM_VAR_2 is missing
        validate_required_env_vars(additional_vars=["CUSTOM_VAR_1", "CUSTOM_VAR_2"])
        logger.error("❌ FAILED: Should have raised EnvironmentError")
        return False
    except OSError as e:
        error_msg = str(e)

        if "CUSTOM_VAR_2" in error_msg and "CUSTOM_VAR_1" not in error_msg:
            logger.info("✅ PASSED: Additional variable validation works correctly")
            logger.info(f"Error message preview:\n{error_msg[:200]}...")
            return True
        else:
            logger.error(
                "❌ FAILED: Error message doesn't correctly identify missing additional vars"
            )
            logger.error(f"Error: {error_msg}")
            return False
    finally:
        # Restore environment
        for var, value in saved_env.items():
            if value is not None:
                os.environ[var] = value


def test_non_strict_mode():
    """Test 6: Non-strict mode provides warnings instead of errors."""
    logger.info("=" * 70)
    logger.info("Test 6: Non-strict mode validation")
    logger.info("=" * 70)

    # Save current environment
    saved_env = {}
    for var in REQUIRED_ENV_VARS:
        saved_env[var] = os.environ.pop(var, None)

    try:
        # Should not raise error in non-strict mode
        validate_required_env_vars(strict=False)
        logger.info("✅ PASSED: Non-strict mode doesn't raise errors")
        return True
    except OSError as e:
        logger.error(f"❌ FAILED: Non-strict mode should not raise errors: {e}")
        return False
    finally:
        # Restore environment
        for var, value in saved_env.items():
            if value is not None:
                os.environ[var] = value


def test_diagnostics_mode():
    """Test 7: Diagnostics mode provides enhanced warnings."""
    logger.info("=" * 70)
    logger.info("Test 7: Enhanced diagnostics mode")
    logger.info("=" * 70)

    # Save current environment
    saved_env = {}
    for var in REQUIRED_ENV_VARS:
        saved_env[var] = os.environ.get(var)

    # Set all required variables
    test_values = {
        "POSTGRES_HOST": "192.168.86.200",
        "POSTGRES_PORT": "5436",
        "POSTGRES_PASSWORD": "test_password",
        "KAFKA_BOOTSTRAP_SERVERS": "192.168.86.200:9092",
        "QDRANT_URL": "http://localhost:6333",
    }

    for var, value in test_values.items():
        os.environ[var] = value

    try:
        # Should not raise any errors
        validate_with_diagnostics()
        logger.info("✅ PASSED: Diagnostics mode completed successfully")
        return True
    except OSError as e:
        logger.error(f"❌ FAILED: Unexpected error: {e}")
        return False
    finally:
        # Restore environment
        for var, value in saved_env.items():
            if value is not None:
                os.environ[var] = value
            else:
                os.environ.pop(var, None)


# =============================================================================
# Main Test Runner
# =============================================================================


def main():
    """Run all tests and report results."""
    logger.info("=" * 70)
    logger.info("ENVIRONMENT VARIABLE CONFIGURATION VALIDATOR - TEST SUITE")
    logger.info("=" * 70)

    tests = [
        ("Missing Variables Detection", test_missing_variables),
        ("All Variables Set", test_all_variables_set),
        ("Format Validation", test_format_validation),
        ("Get with Validation", test_get_with_validation),
        ("Additional Variables", test_additional_variables),
        ("Non-Strict Mode", test_non_strict_mode),
        ("Diagnostics Mode", test_diagnostics_mode),
    ]

    results = []

    for test_name, test_func in tests:
        try:
            passed = test_func()
            results.append((test_name, passed))
        except Exception as e:
            logger.error(f"❌ Test '{test_name}' crashed: {e}")
            import traceback

            traceback.print_exc()
            results.append((test_name, False))

    # Print summary
    logger.info("=" * 70)
    logger.info("TEST SUMMARY")
    logger.info("=" * 70)

    passed_count = sum(1 for _, passed in results if passed)
    total_count = len(results)

    for test_name, passed in results:
        status = "✅ PASSED" if passed else "❌ FAILED"
        logger.info(f"{status}: {test_name}")

    logger.info("=" * 70)
    logger.info(f"Results: {passed_count}/{total_count} tests passed")
    logger.info("=" * 70)

    if passed_count == total_count:
        logger.info("🎉 All tests passed!")
        return 0
    else:
        logger.error(f"⚠️  {total_count - passed_count} test(s) failed")
        return 1


if __name__ == "__main__":
    # Check for verbose flag
    if "-v" in sys.argv or "--verbose" in sys.argv:
        logging.getLogger().setLevel(logging.DEBUG)

    sys.exit(main())
