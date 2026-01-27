# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Integration tests for omniclaude.

These tests require real infrastructure (PostgreSQL, Kafka, etc.) and are
marked with appropriate pytest markers:

- pytest.mark.integration: All integration tests
- pytest.mark.requires_postgres: Tests requiring PostgreSQL connection

To run integration tests:
    pytest tests/integration/ -v -m "integration"

To run only PostgreSQL tests:
    pytest tests/integration/ -v -m "requires_postgres"

Note: These tests are optional and may be skipped in CI environments
without the required infrastructure.
"""
