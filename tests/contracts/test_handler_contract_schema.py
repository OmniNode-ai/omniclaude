# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Contract schema validation - tripwire test to catch schema drift.

This test ensures the handler contract YAML matches the expected runtime schema.
If this test fails, it indicates:
1. Contract YAML was modified without updating expectations, OR
2. Runtime expectations changed without updating contract

Purpose: Catch drift between contract definition and runtime usage EARLY.

NOTE: When omnibase_core.contracts.load_contract becomes available, this module
should be updated to use that instead of the local yaml.safe_load approach.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

# Mark all tests in this module as unit tests
pytestmark = pytest.mark.unit


def load_contract(path: Path) -> dict[str, Any]:
    """Load and parse a contract YAML file.

    Args:
        path: Path to the contract YAML file.

    Returns:
        Parsed contract as a dictionary.

    Raises:
        FileNotFoundError: If the contract file does not exist.
        yaml.YAMLError: If the YAML is invalid.

    NOTE: Replace with `from omnibase_core.contracts import load_contract`
    when that dependency is available.
    """
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


# Contract path relative to repository root
HANDLER_CONTRACT_PATH = Path(
    "contracts/handlers/pattern_storage_postgres/contract.yaml"
)


class TestHandlerContractSchema:
    """Tripwire tests for handler contract schema validation."""

    def test_contract_file_exists(self) -> None:
        """Handler contract file must exist."""
        assert HANDLER_CONTRACT_PATH.exists(), (
            f"Handler contract not found at {HANDLER_CONTRACT_PATH}. "
            "Did you forget to create it?"
        )

    def test_contract_is_valid_yaml(self) -> None:
        """Handler contract must be valid YAML."""
        # Should not raise yaml.YAMLError
        contract = load_contract(HANDLER_CONTRACT_PATH)
        assert isinstance(contract, dict), "Contract must be a dictionary"

    def test_handler_contract_parses_into_expected_schema(self) -> None:
        """Ensure handler contract matches runtime schema exactly.

        This is the primary tripwire test. If any of these assertions fail,
        it means the contract has drifted from runtime expectations.
        """
        contract = load_contract(HANDLER_CONTRACT_PATH)

        # Required top-level fields exist with expected values
        assert contract["handler_id"] == "effect.learned_pattern.storage.postgres", (
            "handler_id mismatch - contract may have drifted"
        )
        assert contract["name"] == "Learned Pattern Storage Handler (PostgreSQL)", (
            "name mismatch - contract may have drifted"
        )

        # Descriptor exists and has correct handler_kind
        assert "descriptor" in contract, "Missing 'descriptor' section in contract"
        assert contract["descriptor"]["handler_kind"] == "effect", (
            "handler_kind must be 'effect' for this handler"
        )

        # Capability outputs are standardized with learned_pattern.storage prefix
        assert "capability_outputs" in contract, "Missing 'capability_outputs' section"
        capability_outputs = contract["capability_outputs"]
        assert "learned_pattern.storage.query" in capability_outputs, (
            "Missing 'learned_pattern.storage.query' capability"
        )
        assert "learned_pattern.storage.upsert" in capability_outputs, (
            "Missing 'learned_pattern.storage.upsert' capability"
        )

        # Handler binding info
        assert contract["handler_key"] == "postgresql", (
            "handler_key must be 'postgresql' for PostgreSQL backend"
        )
        assert "HandlerPatternStoragePostgres" in contract["handler_class"], (
            "handler_class must reference HandlerPatternStoragePostgres"
        )
        assert "ProtocolPatternPersistence" in contract["protocol"], (
            "protocol must reference ProtocolPatternPersistence"
        )

    def test_contract_version_is_valid(self) -> None:
        """Contract version must have major, minor, patch components."""
        contract = load_contract(HANDLER_CONTRACT_PATH)

        assert "contract_version" in contract, "Missing 'contract_version' section"
        version = contract["contract_version"]
        assert "major" in version, "Missing major version"
        assert "minor" in version, "Missing minor version"
        assert "patch" in version, "Missing patch version"
        assert isinstance(version["major"], int), "major must be an integer"
        assert isinstance(version["minor"], int), "minor must be an integer"
        assert isinstance(version["patch"], int), "patch must be an integer"

    def test_descriptor_has_required_fields(self) -> None:
        """Descriptor section must have required handler metadata."""
        contract = load_contract(HANDLER_CONTRACT_PATH)
        descriptor = contract["descriptor"]

        # Required descriptor fields for effect handlers
        assert "handler_kind" in descriptor
        assert "purity" in descriptor
        assert "idempotent" in descriptor
        assert "timeout_ms" in descriptor

        # Verify expected values for this specific handler
        assert descriptor["purity"] == "side_effecting", (
            "Effect handlers should be side_effecting"
        )
        assert descriptor["idempotent"] is True, (
            "Pattern storage should be idempotent (ON CONFLICT UPDATE)"
        )

    def test_input_output_models_are_specified(self) -> None:
        """Input and output models must be fully qualified."""
        contract = load_contract(HANDLER_CONTRACT_PATH)

        assert "input_model" in contract, "Missing 'input_model'"
        assert "output_model" in contract, "Missing 'output_model'"

        # Models should be fully qualified paths
        assert "omniclaude" in contract["input_model"], (
            "input_model must be fully qualified"
        )
        assert "omniclaude" in contract["output_model"], (
            "output_model must be fully qualified"
        )

    def test_metadata_contains_ticket_reference(self) -> None:
        """Metadata must contain ticket reference for traceability."""
        contract = load_contract(HANDLER_CONTRACT_PATH)

        assert "metadata" in contract, "Missing 'metadata' section"
        metadata = contract["metadata"]
        assert "ticket" in metadata, "Missing 'ticket' in metadata"
        assert metadata["ticket"] == "OMN-1403", "Ticket reference should be OMN-1403"
