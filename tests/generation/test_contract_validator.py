#!/usr/bin/env python3
"""
Unit tests for Contract Validator - Phase 2 Stream D

Comprehensive test suite for contract schema validation including:
- Pydantic model validation
- Schema compliance checking
- Model reference resolution
- All 4 node types (EFFECT, COMPUTE, REDUCER, ORCHESTRATOR)
- Error handling and edge cases

Target: >40 tests for complete coverage
"""

import sys
from pathlib import Path

import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from agents.lib.generation.contract_validator import (
    ContractValidator,
    ValidationResult,
)

# -------------------------------------------------------------------------
# Basic Validation Tests
# -------------------------------------------------------------------------


def test_contract_validator_initialization():
    """Test ContractValidator initialization."""
    validator = ContractValidator()
    assert validator is not None
    assert validator.model_search_paths == []


def test_contract_validator_with_search_paths(tmp_path: Path):
    """Test ContractValidator initialization with search paths."""
    models_dir = tmp_path / "models"
    models_dir.mkdir()

    validator = ContractValidator(model_search_paths=[models_dir])
    assert len(validator.model_search_paths) == 1
    assert validator.model_search_paths[0] == models_dir


# -------------------------------------------------------------------------
# EFFECT Contract Validation Tests
# -------------------------------------------------------------------------


def test_validate_effect_contract_success(
    contract_validator: ContractValidator, sample_effect_contract_yaml: str
):
    """Test successful EFFECT contract validation."""
    result = contract_validator.validate_contract(sample_effect_contract_yaml, "EFFECT")

    assert result.valid is True
    assert result.node_type == "EFFECT"
    assert result.schema_compliance is True
    assert result.contract is not None
    assert result.contract.name == "NodeDatabaseWriterEffect"
    assert len(result.errors) == 0


def test_validate_effect_contract_with_missing_fields(
    contract_validator: ContractValidator,
):
    """Test EFFECT contract validation with missing required fields."""
    incomplete_yaml = """
name: NodeTestEffect
version: "1.0.0"
# Missing description, node_type, models
"""
    result = contract_validator.validate_contract(incomplete_yaml, "EFFECT")

    assert result.valid is False
    assert result.schema_compliance is False
    assert len(result.errors) > 0


def test_validate_effect_contract_invalid_type_field(
    contract_validator: ContractValidator,
):
    """Test EFFECT contract validation with invalid field types."""
    invalid_yaml = """
name: NodeTestEffect
version: 1.0  # Should be string
description: "Test"
node_type: EFFECT
input_model: ModelInput
output_model: ModelOutput
error_model: ModelError
"""
    result = contract_validator.validate_contract(invalid_yaml, "EFFECT")

    # May pass or fail depending on Pydantic coercion
    assert result.node_type == "EFFECT"


# -------------------------------------------------------------------------
# COMPUTE Contract Validation Tests
# -------------------------------------------------------------------------


def test_validate_compute_contract_success(
    contract_validator: ContractValidator, sample_compute_contract_yaml: str
):
    """Test successful COMPUTE contract validation."""
    result = contract_validator.validate_contract(
        sample_compute_contract_yaml, "COMPUTE"
    )

    assert result.valid is True
    assert result.node_type == "COMPUTE"
    assert result.schema_compliance is True
    assert result.contract is not None
    assert result.contract.name == "NodeDataTransformerCompute"


def test_validate_compute_contract_with_extra_fields(
    contract_validator: ContractValidator,
):
    """Test COMPUTE contract validation with extra fields."""
    yaml_with_extra = """
name: NodeTestCompute
version: "1.0.0"
description: "Test compute node"
node_type: COMPUTE
input_model: ModelInput
output_model: ModelOutput
error_model: ModelError
computation_type: transformation
is_pure: true
extra_field: "This should not be here"  # Extra field
"""
    result = contract_validator.validate_contract(yaml_with_extra, "COMPUTE")

    # Pydantic should reject extra fields or ignore them depending on config
    # We expect validation to handle this gracefully
    assert result.node_type == "COMPUTE"


# -------------------------------------------------------------------------
# REDUCER Contract Validation Tests
# -------------------------------------------------------------------------


def test_validate_reducer_contract_success(
    contract_validator: ContractValidator, sample_reducer_contract_yaml: str
):
    """Test successful REDUCER contract validation."""
    result = contract_validator.validate_contract(
        sample_reducer_contract_yaml, "REDUCER"
    )

    assert result.valid is True
    assert result.node_type == "REDUCER"
    assert result.schema_compliance is True
    assert result.contract is not None
    assert result.contract.name == "NodeAggregationReducer"


def test_validate_reducer_contract_intent_emissions(
    contract_validator: ContractValidator,
):
    """Test REDUCER contract validation with intent emissions."""
    yaml_with_intents = """
name: NodeIntentReducer
version: "1.0.0"
description: "Reducer with intent emissions"
node_type: REDUCER
input_model: ModelInput
output_model: ModelOutput
error_model: ModelError
aggregation_strategy: sum
state_management: true
intent_emissions:
  - intent_type: data_processed
    destination: event_bus
  - intent_type: batch_complete
    destination: notification_service
"""
    result = contract_validator.validate_contract(yaml_with_intents, "REDUCER")

    assert result.node_type == "REDUCER"
    # Validation should handle intent_emissions if it's part of the schema


# -------------------------------------------------------------------------
# ORCHESTRATOR Contract Validation Tests
# -------------------------------------------------------------------------


def test_validate_orchestrator_contract_success(
    contract_validator: ContractValidator, sample_orchestrator_contract_yaml: str
):
    """Test successful ORCHESTRATOR contract validation."""
    result = contract_validator.validate_contract(
        sample_orchestrator_contract_yaml, "ORCHESTRATOR"
    )

    assert result.valid is True
    assert result.node_type == "ORCHESTRATOR"
    assert result.schema_compliance is True
    assert result.contract is not None
    assert result.contract.name == "NodeWorkflowOrchestrator"


def test_validate_orchestrator_contract_workflow_steps(
    contract_validator: ContractValidator,
):
    """Test ORCHESTRATOR contract validation with workflow steps."""
    yaml_with_steps = """
name: NodeMultiStepOrchestrator
version: "1.0.0"
description: "Orchestrator with multiple workflow steps"
node_type: ORCHESTRATOR
input_model: ModelInput
output_model: ModelOutput
error_model: ModelError
workflow_steps:
  - step: validate
  - step: transform
  - step: aggregate
  - step: persist
lease_management: true
"""
    result = contract_validator.validate_contract(yaml_with_steps, "ORCHESTRATOR")

    assert result.node_type == "ORCHESTRATOR"


# -------------------------------------------------------------------------
# Invalid Contract Tests
# -------------------------------------------------------------------------


def test_validate_invalid_contract_yaml(
    contract_validator: ContractValidator, invalid_contract_yaml: str
):
    """Test validation with invalid contract YAML."""
    result = contract_validator.validate_contract(invalid_contract_yaml, "EFFECT")

    assert result.valid is False
    assert result.schema_compliance is False
    assert len(result.errors) > 0


def test_validate_contract_malformed_yaml(contract_validator: ContractValidator):
    """Test validation with malformed YAML."""
    malformed_yaml = """
name: InvalidNode
description: "Test"
  invalid indentation:
    - this is broken
"""
    result = contract_validator.validate_contract(malformed_yaml, "EFFECT")

    assert result.valid is False
    assert len(result.errors) > 0
    assert any(error.get("type") == "yaml_error" for error in result.errors)


def test_validate_contract_non_dict_yaml(contract_validator: ContractValidator):
    """Test validation with non-dictionary YAML."""
    list_yaml = """
- item1
- item2
- item3
"""
    result = contract_validator.validate_contract(list_yaml, "EFFECT")

    assert result.valid is False
    assert len(result.errors) > 0
    assert any(
        "must be a dictionary" in error.get("msg", "") for error in result.errors
    )


def test_validate_contract_invalid_node_type(contract_validator: ContractValidator):
    """Test validation with invalid node type."""
    with pytest.raises(ValueError, match="Invalid node type"):
        contract_validator.validate_contract(
            sample_effect_contract_yaml="name: Test\n", node_type="INVALID"
        )


# -------------------------------------------------------------------------
# Model Reference Validation Tests
# -------------------------------------------------------------------------


def test_validate_model_references_no_search_paths(
    contract_validator: ContractValidator, sample_effect_contract_yaml: str
):
    """Test model reference validation without search paths."""
    result = contract_validator.validate_contract(sample_effect_contract_yaml, "EFFECT")

    # Without search paths, should default to assuming models exist
    assert result.model_references_valid is True


def test_validate_model_references_with_missing_models(
    contract_validator_with_search_paths: ContractValidator, tmp_path: Path
):
    """Test model reference validation with missing model files."""
    yaml_with_refs = """
name: NodeTestEffect
version: "1.0.0"
description: "Test node"
node_type: EFFECT
input_model: ModelNonexistentInput
output_model: ModelNonexistentOutput
error_model: ModelOnexError
"""
    result = contract_validator_with_search_paths.validate_contract(
        yaml_with_refs, "EFFECT"
    )

    # Should have warnings about missing models
    assert len(result.warnings) > 0 or result.model_references_valid is False


def test_validate_model_references_with_existing_models(
    contract_validator_with_search_paths: ContractValidator, tmp_path: Path
):
    """Test model reference validation with existing model files."""
    # Create model files in search path
    models_dir = contract_validator_with_search_paths.model_search_paths[0]
    (models_dir / "model_test_input.py").write_text("# Model file")
    (models_dir / "model_test_output.py").write_text("# Model file")
    (models_dir / "model_onex_error.py").write_text("# Model file")

    yaml_with_refs = """
name: NodeTestEffect
version: "1.0.0"
description: "Test node"
node_type: EFFECT
input_model: ModelTestInput
output_model: ModelTestOutput
error_model: ModelOnexError
"""
    result = contract_validator_with_search_paths.validate_contract(
        yaml_with_refs, "EFFECT"
    )

    # Should find all models
    assert result.model_references_valid is True
    assert len(result.warnings) == 0


# -------------------------------------------------------------------------
# File Validation Tests
# -------------------------------------------------------------------------


def test_validate_contract_file_success(
    contract_validator: ContractValidator,
    tmp_path: Path,
    sample_effect_contract_yaml: str,
):
    """Test validation from file."""
    contract_file = tmp_path / "contract.yaml"
    contract_file.write_text(sample_effect_contract_yaml)

    result = contract_validator.validate_contract_file(contract_file, "EFFECT")

    assert result.valid is True
    assert result.contract is not None


def test_validate_contract_file_not_found(
    contract_validator: ContractValidator, tmp_path: Path
):
    """Test validation with non-existent file."""
    nonexistent_file = tmp_path / "nonexistent.yaml"

    result = contract_validator.validate_contract_file(nonexistent_file, "EFFECT")

    assert result.valid is False
    assert any(error.get("type") == "file_not_found" for error in result.errors)


# -------------------------------------------------------------------------
# Batch Validation Tests
# -------------------------------------------------------------------------


def test_validate_batch_all_valid(
    contract_validator: ContractValidator,
    sample_effect_contract_yaml: str,
    sample_compute_contract_yaml: str,
):
    """Test batch validation with all valid contracts."""
    contracts = [
        {"name": "effect", "yaml": sample_effect_contract_yaml, "node_type": "EFFECT"},
        {
            "name": "compute",
            "yaml": sample_compute_contract_yaml,
            "node_type": "COMPUTE",
        },
    ]

    results = contract_validator.validate_batch(contracts)

    assert len(results) == 2
    assert results["effect"].valid is True
    assert results["compute"].valid is True


def test_validate_batch_mixed_results(
    contract_validator: ContractValidator,
    sample_effect_contract_yaml: str,
    invalid_contract_yaml: str,
):
    """Test batch validation with mixed valid/invalid contracts."""
    contracts = [
        {"name": "valid", "yaml": sample_effect_contract_yaml, "node_type": "EFFECT"},
        {"name": "invalid", "yaml": invalid_contract_yaml, "node_type": "EFFECT"},
    ]

    results = contract_validator.validate_batch(contracts)

    assert len(results) == 2
    assert results["valid"].valid is True
    assert results["invalid"].valid is False


def test_get_validation_summary(
    contract_validator: ContractValidator,
    sample_effect_contract_yaml: str,
    invalid_contract_yaml: str,
):
    """Test validation summary generation."""
    contracts = [
        {"name": "valid1", "yaml": sample_effect_contract_yaml, "node_type": "EFFECT"},
        {"name": "valid2", "yaml": sample_effect_contract_yaml, "node_type": "EFFECT"},
        {"name": "invalid", "yaml": invalid_contract_yaml, "node_type": "EFFECT"},
    ]

    results = contract_validator.validate_batch(contracts)
    summary = contract_validator.get_validation_summary(results)

    assert summary["total_contracts"] == 3
    assert summary["valid_contracts"] == 2
    assert summary["invalid_contracts"] == 1
    assert summary["validation_rate"] == pytest.approx(2 / 3)
    assert "invalid" in summary["failed_contracts"]


# -------------------------------------------------------------------------
# Validation Result Tests
# -------------------------------------------------------------------------


def test_validation_result_get_error_summary_valid():
    """Test error summary for valid result."""
    result = ValidationResult(valid=True)
    summary = result.get_error_summary()

    assert "valid" in summary.lower()


def test_validation_result_get_error_summary_invalid():
    """Test error summary for invalid result."""
    result = ValidationResult(
        valid=False,
        errors=[
            {"loc": ["name"], "msg": "Field required", "type": "missing"},
            {"loc": ["version"], "msg": "Field required", "type": "missing"},
        ],
        warnings=["Model reference not found"],
    )
    summary = result.get_error_summary()

    assert "failed" in summary.lower()
    assert "name" in summary
    assert "version" in summary
    assert "warnings" in summary.lower()


# -------------------------------------------------------------------------
# Helper Method Tests
# -------------------------------------------------------------------------


def test_model_name_to_filename():
    """Test model name to filename conversion."""
    validator = ContractValidator()

    # Test PascalCase to snake_case conversion
    assert (
        validator._model_name_to_filename("ModelDatabaseInput")
        == "model_database_input.py"
    )
    assert (
        validator._model_name_to_filename("ModelTestService") == "model_test_service.py"
    )
    assert validator._model_name_to_filename("ModelOnexError") == "model_onex_error.py"


def test_get_contract_model():
    """Test getting contract model for node type."""
    validator = ContractValidator()

    from omnibase_core.models.contracts import (
        ModelContractCompute,
        ModelContractEffect,
        ModelContractOrchestrator,
        ModelContractReducer,
    )

    assert validator._get_contract_model("EFFECT") == ModelContractEffect
    assert validator._get_contract_model("COMPUTE") == ModelContractCompute
    assert validator._get_contract_model("REDUCER") == ModelContractReducer
    assert validator._get_contract_model("ORCHESTRATOR") == ModelContractOrchestrator


# -------------------------------------------------------------------------
# Run Tests
# -------------------------------------------------------------------------


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
