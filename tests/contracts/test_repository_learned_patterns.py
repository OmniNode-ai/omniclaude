# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Validation test for learned patterns repository contract.

This test ensures the repository_learned_patterns.yaml contract validates
against the canonical ModelDbRepositoryContract schema from omnibase_core.

If this test fails, it indicates schema drift between:
1. The contract YAML definition, OR
2. The omnibase_core ModelDbRepositoryContract schema

Purpose: Catch drift between contract definition and runtime usage EARLY.

Schema Reference: omnibase_core.models.contracts.ModelDbRepositoryContract
Ticket: OMN-1779 - Wire ManifestInjector to contract runtime
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
    """
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


# Contract path relative to repository root
# Use absolute path from test file location to find contract
LEARNED_PATTERNS_CONTRACT_PATH = (
    Path(__file__).parent.parent.parent
    / "src/omniclaude/hooks/contracts/repository_learned_patterns.yaml"
)


class TestLearnedPatternsRepositoryContract:
    """Tests for learned patterns repository contract validation.

    These tests validate that the repository_learned_patterns.yaml contract
    validates against ModelDbRepositoryContract from omnibase_core.
    """

    def test_contract_file_exists(self) -> None:
        """Repository contract file must exist."""
        assert LEARNED_PATTERNS_CONTRACT_PATH.exists(), (
            f"Repository contract not found at {LEARNED_PATTERNS_CONTRACT_PATH}. "
            "Did you forget to create it?"
        )

    def test_contract_is_valid_yaml(self) -> None:
        """Repository contract must be valid YAML."""
        contract = load_contract(LEARNED_PATTERNS_CONTRACT_PATH)
        assert isinstance(contract, dict), "Contract must be a dictionary"

    def test_contract_validates_against_model_db_repository_contract(self) -> None:
        """Contract YAML must validate against ModelDbRepositoryContract.

        This is the primary tripwire test. If this fails, the contract YAML
        has drifted from the canonical schema in omnibase_core.
        """
        from omnibase_core.models.contracts import ModelDbRepositoryContract

        contract_data = load_contract(LEARNED_PATTERNS_CONTRACT_PATH)

        # Should not raise ValidationError
        contract = ModelDbRepositoryContract.model_validate(contract_data)

        # Verify contract loaded successfully
        assert contract.name == "learned_patterns"
        assert contract.engine == "postgres"
        assert contract.database_ref == "omninode_bridge"

    def test_contract_has_expected_operations(self) -> None:
        """Contract must define the expected database operations.

        These operations are required for pattern injection functionality.
        """
        from omnibase_core.models.contracts import ModelDbRepositoryContract

        contract_data = load_contract(LEARNED_PATTERNS_CONTRACT_PATH)
        contract = ModelDbRepositoryContract.model_validate(contract_data)

        # Verify expected operations exist
        assert "list_validated_patterns" in contract.ops, (
            "Missing 'list_validated_patterns' operation - required for pattern injection"
        )
        assert "get_pattern_by_id" in contract.ops, (
            "Missing 'get_pattern_by_id' operation - required for pattern lookup"
        )
        assert "list_patterns_by_domain" in contract.ops, (
            "Missing 'list_patterns_by_domain' operation - required for domain filtering"
        )

    def test_list_validated_patterns_operation_structure(self) -> None:
        """list_validated_patterns operation must have correct structure."""
        from omnibase_core.models.contracts import ModelDbRepositoryContract

        contract_data = load_contract(LEARNED_PATTERNS_CONTRACT_PATH)
        contract = ModelDbRepositoryContract.model_validate(contract_data)

        op = contract.ops["list_validated_patterns"]
        assert op.mode == "read", "list_validated_patterns must be a read operation"
        assert op.returns is not None, "list_validated_patterns must have returns"
        assert op.returns.many is True, "list_validated_patterns returns multiple rows"

        # Verify limit parameter exists
        assert "limit" in op.params, "list_validated_patterns must have limit parameter"
        limit_param = op.params["limit"]
        assert limit_param.required is False, "limit should be optional"

    def test_get_pattern_by_id_operation_structure(self) -> None:
        """get_pattern_by_id operation must have correct structure."""
        from omnibase_core.models.contracts import ModelDbRepositoryContract

        contract_data = load_contract(LEARNED_PATTERNS_CONTRACT_PATH)
        contract = ModelDbRepositoryContract.model_validate(contract_data)

        op = contract.ops["get_pattern_by_id"]
        assert op.mode == "read", "get_pattern_by_id must be a read operation"
        assert op.returns is not None, "get_pattern_by_id must have returns"
        assert op.returns.many is False, "get_pattern_by_id returns single row"

        # Verify pattern_id parameter exists and is required
        assert "pattern_id" in op.params, (
            "get_pattern_by_id must have pattern_id parameter"
        )
        pattern_id_param = op.params["pattern_id"]
        assert pattern_id_param.required is True, "pattern_id should be required"
        assert pattern_id_param.param_type == "uuid", "pattern_id should be uuid type"

    def test_list_patterns_by_domain_operation_structure(self) -> None:
        """list_patterns_by_domain operation must have correct structure."""
        from omnibase_core.models.contracts import ModelDbRepositoryContract

        contract_data = load_contract(LEARNED_PATTERNS_CONTRACT_PATH)
        contract = ModelDbRepositoryContract.model_validate(contract_data)

        op = contract.ops["list_patterns_by_domain"]
        assert op.mode == "read", "list_patterns_by_domain must be a read operation"
        assert op.returns is not None, "list_patterns_by_domain must have returns"
        assert op.returns.many is True, "list_patterns_by_domain returns multiple rows"

        # Verify domain parameter exists and is required
        assert "domain" in op.params, (
            "list_patterns_by_domain must have domain parameter"
        )
        domain_param = op.params["domain"]
        assert domain_param.required is True, "domain should be required"

    def test_contract_specifies_tables(self) -> None:
        """Contract must specify tables for access control validation."""
        from omnibase_core.models.contracts import ModelDbRepositoryContract

        contract_data = load_contract(LEARNED_PATTERNS_CONTRACT_PATH)
        contract = ModelDbRepositoryContract.model_validate(contract_data)

        assert contract.tables is not None, "Contract must specify tables"
        assert "learned_patterns" in contract.tables, (
            "Contract must include 'learned_patterns' table"
        )

    def test_contract_specifies_model_mapping(self) -> None:
        """Contract must specify Pydantic models for row mapping."""
        from omnibase_core.models.contracts import ModelDbRepositoryContract

        contract_data = load_contract(LEARNED_PATTERNS_CONTRACT_PATH)
        contract = ModelDbRepositoryContract.model_validate(contract_data)

        assert contract.models is not None, "Contract must specify models"
        assert "PatternRow" in contract.models, (
            "Contract must define 'PatternRow' model mapping"
        )
        # Verify the model reference is fully qualified
        pattern_row_ref = contract.models["PatternRow"]
        assert ":" in pattern_row_ref, (
            "Model reference must be in 'module:class' format"
        )

    def test_all_operations_are_read_only(self) -> None:
        """All operations in this contract must be read-only.

        This contract is for pattern injection (reading patterns).
        Write operations should be in a separate contract.
        """
        from omnibase_core.models.contracts import ModelDbRepositoryContract

        contract_data = load_contract(LEARNED_PATTERNS_CONTRACT_PATH)
        contract = ModelDbRepositoryContract.model_validate(contract_data)

        for op_name, op in contract.ops.items():
            assert op.mode == "read", (
                f"Operation '{op_name}' must be read-only. "
                "Write operations should be in a separate contract."
            )
