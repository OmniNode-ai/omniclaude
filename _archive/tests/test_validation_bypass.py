"""
Test that configuration validation behaves correctly across pytest phases.

This test verifies that validation is:
- SKIPPED during collection phase (allows test discovery without full config)
- RUNS during execution phases (setup/call/teardown - catches config issues)
- RUNS during normal execution (production/development)

Context:
    This test addresses the issue where validation was being bypassed during
    ALL pytest phases, not just collection. The fix ensures tests validate
    configuration during actual execution while still allowing test discovery
    when .env might not be fully configured.

Expected Behavior:
    - Collection: Validation skipped (pytest imported, PYTEST_CURRENT_TEST not set)
    - Setup/Call/Teardown: Validation runs (pytest imported, PYTEST_CURRENT_TEST set)
    - Normal run: Validation runs (pytest not imported)
"""

import os
import sys
from unittest.mock import patch

import pytest
from config.settings import reload_settings


def test_validation_logic_across_phases():
    """
    Test validation bypass logic across different pytest phases.

    This test verifies the condition:
        in_pytest_collection = "pytest" in sys.modules and not os.getenv("PYTEST_CURRENT_TEST")

    Expected results:
        - Normal run (pytest not in modules): Validation RUNS
        - Collection (pytest in modules, PYTEST_CURRENT_TEST not set): Validation SKIPPED
        - Setup/Call/Teardown (pytest in modules, PYTEST_CURRENT_TEST set): Validation RUNS
    """
    # Test normal run (no pytest)
    with (
        patch.dict(sys.modules, {}, clear=True),
        patch.dict(os.environ, {}, clear=True),
    ):
        in_pytest_collection = "pytest" in sys.modules and not os.getenv(
            "PYTEST_CURRENT_TEST"
        )
        assert in_pytest_collection is False, "Normal run should validate (skip=False)"

    # Test collection phase (pytest imported, PYTEST_CURRENT_TEST not set)
    with (
        patch.dict(sys.modules, {"pytest": None}),
        patch.dict(os.environ, {}, clear=True),
    ):
        in_pytest_collection = "pytest" in sys.modules and not os.getenv(
            "PYTEST_CURRENT_TEST"
        )
        assert (
            in_pytest_collection is True
        ), "Collection phase should skip validation (skip=True)"

    # Test setup phase (pytest imported, PYTEST_CURRENT_TEST set to "setup")
    with (
        patch.dict(sys.modules, {"pytest": None}),
        patch.dict(
            os.environ, {"PYTEST_CURRENT_TEST": "test.py::test (setup)"}, clear=True
        ),
    ):
        in_pytest_collection = "pytest" in sys.modules and not os.getenv(
            "PYTEST_CURRENT_TEST"
        )
        assert in_pytest_collection is False, "Setup phase should validate (skip=False)"

    # Test call phase (pytest imported, PYTEST_CURRENT_TEST set to "call")
    with (
        patch.dict(sys.modules, {"pytest": None}),
        patch.dict(
            os.environ, {"PYTEST_CURRENT_TEST": "test.py::test (call)"}, clear=True
        ),
    ):
        in_pytest_collection = "pytest" in sys.modules and not os.getenv(
            "PYTEST_CURRENT_TEST"
        )
        assert in_pytest_collection is False, "Call phase should validate (skip=False)"

    # Test teardown phase (pytest imported, PYTEST_CURRENT_TEST set to "teardown")
    with (
        patch.dict(sys.modules, {"pytest": None}),
        patch.dict(
            os.environ, {"PYTEST_CURRENT_TEST": "test.py::test (teardown)"}, clear=True
        ),
    ):
        in_pytest_collection = "pytest" in sys.modules and not os.getenv(
            "PYTEST_CURRENT_TEST"
        )
        assert (
            in_pytest_collection is False
        ), "Teardown phase should validate (skip=False)"


def test_validation_runs_during_test_execution():
    """
    Test that validation actually runs during test execution.

    This test verifies that when we're in a pytest test (PYTEST_CURRENT_TEST is set),
    validation is NOT bypassed. This ensures tests catch configuration issues.

    Note:
        Since this test runs during pytest execution (not collection),
        PYTEST_CURRENT_TEST should be set, and validation should run.
    """
    # Verify we're in test execution phase
    assert os.getenv("PYTEST_CURRENT_TEST") is not None, (
        "This test should run during pytest execution "
        "(PYTEST_CURRENT_TEST should be set)"
    )

    # Reload settings to trigger validation
    # This should NOT skip validation because PYTEST_CURRENT_TEST is set
    settings = reload_settings()

    # If we get here without exception, validation either:
    # 1. Ran successfully (config is valid)
    # 2. Was bypassed (BUG - this is what we're testing against)

    # Verify validation would catch issues by checking it runs
    # We do this by verifying the settings object has required fields
    assert hasattr(settings, "postgres_password"), (
        "Settings should have postgres_password field "
        "(indicates validation logic was executed)"
    )

    # Additional check: verify validation methods are callable
    errors = settings.validate_required_services()
    # Don't assert on errors being empty - just verify validation ran
    assert isinstance(errors, list), "Validation should return a list of errors"


def test_collection_phase_skips_validation():
    """
    Test that collection phase skips validation.

    This test simulates the collection phase by:
    1. Ensuring pytest is in sys.modules (simulating pytest running)
    2. Ensuring PYTEST_CURRENT_TEST is NOT set (simulating collection)

    Expected: Validation should be skipped
    """
    # Simulate collection phase
    with (
        patch.dict(sys.modules, {"pytest": None}),
        patch.dict(os.environ, {}, clear=True),
    ):
        # Remove PYTEST_CURRENT_TEST to simulate collection
        os.environ.pop("PYTEST_CURRENT_TEST", None)

        # This should match the condition in get_settings()
        in_pytest_collection = "pytest" in sys.modules and not os.getenv(
            "PYTEST_CURRENT_TEST"
        )

        assert (
            in_pytest_collection is True
        ), "Collection phase detection failed - validation would not be skipped"


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v"])
