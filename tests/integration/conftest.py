#!/usr/bin/env python3
"""
Pytest fixtures for integration tests.

Provides fixtures needed by Full Pipeline Integration Tests including:
- ContractValidator instance for validation testing
- Additional integration-specific fixtures as needed
"""

import pytest

from agents.lib.generation.contract_validator import ContractValidator


@pytest.fixture
def contract_validator() -> ContractValidator:
    """
    Provide ContractValidator instance for integration tests.

    This fixture is used by tests that need to validate contracts
    during integration testing, particularly in test_full_pipeline.py.

    Returns:
        ContractValidator: Initialized validator instance
    """
    return ContractValidator()
