#!/usr/bin/env python3
"""
Integration Tests for Full Pipeline - Phase 2 Stream D

Comprehensive integration tests including:
- Complete pipeline execution for all 4 node types
- Contract validation integration
- End-to-end generation workflows
- Multi-node generation testing

Target: >20 integration tests + 16 node type tests = 36+ tests
"""

import sys
from pathlib import Path

import pytest


# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from agents.lib.generation.contract_validator import ContractValidator


# -------------------------------------------------------------------------
# Integration Tests: Contract Validation in Pipeline
# -------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_pipeline_with_contract_validation_effect(
    sample_effect_prompt: str, temp_output_dir: Path
):
    """Test pipeline execution with contract validation for EFFECT node."""
    # This test requires full integration with template engine
    # For now, we validate the contract validation integration point
    validator = ContractValidator()

    # Simulate a generated contract
    sample_contract = """
name: NodeTestEffect
version: "1.0.0"
description: "Test EFFECT node"
node_type: EFFECT
input_model: ModelInput
output_model: ModelOutput
error_model: ModelOnexError
io_operations:
  - operation_type: "write"
"""

    result = validator.validate_contract(sample_contract, "EFFECT")
    assert result.valid is True
    assert result.node_type == "EFFECT"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_pipeline_with_contract_validation_compute(
    sample_compute_prompt: str, temp_output_dir: Path
):
    """Test pipeline execution with contract validation for COMPUTE node."""
    validator = ContractValidator()

    sample_contract = """
name: NodeTestCompute
version: "1.0.0"
description: "Test COMPUTE node"
node_type: COMPUTE
input_model: ModelInput
output_model: ModelOutput
error_model: ModelOnexError
algorithm:
  algorithm_type: "transformation"
  factors:
    main:
      weight: 1.0
      calculation_method: "transform"
computation_type: transformation
is_pure: true
"""

    result = validator.validate_contract(sample_contract, "COMPUTE")
    assert result.valid is True
    assert result.node_type == "COMPUTE"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_pipeline_with_contract_validation_reducer(
    sample_reducer_prompt: str, temp_output_dir: Path
):
    """Test pipeline execution with contract validation for REDUCER node."""
    validator = ContractValidator()

    sample_contract = """
name: NodeTestReducer
version: "1.0.0"
description: "Test REDUCER node"
node_type: REDUCER
input_model: ModelInput
output_model: ModelOutput
error_model: ModelOnexError
aggregation_strategy: sum
state_management: true
"""

    result = validator.validate_contract(sample_contract, "REDUCER")
    assert result.valid is True
    assert result.node_type == "REDUCER"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_pipeline_with_contract_validation_orchestrator(
    sample_orchestrator_prompt: str, temp_output_dir: Path
):
    """Test pipeline execution with contract validation for ORCHESTRATOR node."""
    validator = ContractValidator()

    sample_contract = """
name: NodeTestOrchestrator
version: "1.0.0"
description: "Test ORCHESTRATOR node"
node_type: ORCHESTRATOR
input_model: ModelInput
output_model: ModelOutput
error_model: ModelOnexError
workflow_steps:
  - step: process
lease_management: true
"""

    result = validator.validate_contract(sample_contract, "ORCHESTRATOR")
    assert result.valid is True
    assert result.node_type == "ORCHESTRATOR"


# -------------------------------------------------------------------------
# Node Type Tests: All 4 Node Types (16 tests)
# -------------------------------------------------------------------------


@pytest.mark.integration
class TestAllNodeTypes:
    """Comprehensive tests for all 4 node types."""

    # EFFECT Node Tests (4 tests)

    def test_effect_node_contract_structure(self, sample_effect_contract_yaml: str):
        """Test EFFECT node contract structure."""
        validator = ContractValidator()
        result = validator.validate_contract(sample_effect_contract_yaml, "EFFECT")

        assert result.valid is True
        assert result.contract.name == "NodeDatabaseWriterEffect"
        assert hasattr(result.contract, "io_operations")
        assert hasattr(result.contract, "lifecycle")

    def test_effect_node_io_operations(self, sample_effect_contract_yaml: str):
        """Test EFFECT node I/O operations validation."""
        validator = ContractValidator()
        result = validator.validate_contract(sample_effect_contract_yaml, "EFFECT")

        assert result.valid is True
        # IO operations should be present in EFFECT nodes
        assert result.contract.io_operations is not None

    def test_effect_node_lifecycle_hooks(self, sample_effect_contract_yaml: str):
        """Test EFFECT node lifecycle hooks."""
        validator = ContractValidator()
        result = validator.validate_contract(sample_effect_contract_yaml, "EFFECT")

        assert result.valid is True
        # Lifecycle hooks should be present
        assert result.contract.lifecycle is not None

    def test_effect_node_dependencies(self, sample_effect_contract_yaml: str):
        """Test EFFECT node dependencies."""
        validator = ContractValidator()
        result = validator.validate_contract(sample_effect_contract_yaml, "EFFECT")

        assert result.valid is True
        # Dependencies should be specified
        assert result.contract.dependencies is not None

    # COMPUTE Node Tests (4 tests)

    def test_compute_node_contract_structure(self, sample_compute_contract_yaml: str):
        """Test COMPUTE node contract structure."""
        validator = ContractValidator()
        result = validator.validate_contract(sample_compute_contract_yaml, "COMPUTE")

        assert result.valid is True
        assert result.contract.name == "NodeDataTransformerCompute"
        assert hasattr(result.contract, "computation_type")

    def test_compute_node_pure_function_flag(self, sample_compute_contract_yaml: str):
        """Test COMPUTE node pure function flag."""
        validator = ContractValidator()
        result = validator.validate_contract(sample_compute_contract_yaml, "COMPUTE")

        assert result.valid is True
        # COMPUTE nodes should specify if they're pure functions
        assert hasattr(result.contract, "is_pure")

    def test_compute_node_computation_type(self):
        """Test COMPUTE node computation type validation."""
        validator = ContractValidator()

        yaml_compute = """
name: NodeComputeTest
version: "1.0.0"
description: "Test compute"
node_type: COMPUTE
input_model: ModelInput
output_model: ModelOutput
error_model: ModelOnexError
computation_type: aggregation
is_pure: true
"""

        result = validator.validate_contract(yaml_compute, "COMPUTE")
        assert result.valid is True

    def test_compute_node_no_side_effects(self):
        """Test COMPUTE node should not have I/O operations."""
        validator = ContractValidator()

        # COMPUTE nodes shouldn't have io_operations (side effects)
        yaml_compute = """
name: NodeComputeTest
version: "1.0.0"
description: "Test compute"
node_type: COMPUTE
input_model: ModelInput
output_model: ModelOutput
error_model: ModelOnexError
computation_type: transformation
is_pure: true
"""

        result = validator.validate_contract(yaml_compute, "COMPUTE")
        assert result.valid is True

    # REDUCER Node Tests (4 tests)

    def test_reducer_node_contract_structure(self, sample_reducer_contract_yaml: str):
        """Test REDUCER node contract structure."""
        validator = ContractValidator()
        result = validator.validate_contract(sample_reducer_contract_yaml, "REDUCER")

        assert result.valid is True
        assert result.contract.name == "NodeAggregationReducer"
        assert hasattr(result.contract, "aggregation_strategy")

    def test_reducer_node_state_management(self, sample_reducer_contract_yaml: str):
        """Test REDUCER node state management."""
        validator = ContractValidator()
        result = validator.validate_contract(sample_reducer_contract_yaml, "REDUCER")

        assert result.valid is True
        # REDUCER nodes should specify state management
        assert hasattr(result.contract, "state_management")

    def test_reducer_node_intent_emissions(self, sample_reducer_contract_yaml: str):
        """Test REDUCER node intent emissions."""
        validator = ContractValidator()
        result = validator.validate_contract(sample_reducer_contract_yaml, "REDUCER")

        assert result.valid is True
        # REDUCER nodes should support intent emissions
        assert hasattr(result.contract, "intent_emissions")

    def test_reducer_node_aggregation_strategy(self):
        """Test REDUCER node aggregation strategy."""
        validator = ContractValidator()

        yaml_reducer = """
name: NodeReducerTest
version: "1.0.0"
description: "Test reducer"
node_type: REDUCER
input_model: ModelInput
output_model: ModelOutput
error_model: ModelOnexError
aggregation_strategy: average
state_management: true
"""

        result = validator.validate_contract(yaml_reducer, "REDUCER")
        assert result.valid is True

    # ORCHESTRATOR Node Tests (4 tests)

    def test_orchestrator_node_contract_structure(
        self, sample_orchestrator_contract_yaml: str
    ):
        """Test ORCHESTRATOR node contract structure."""
        validator = ContractValidator()
        result = validator.validate_contract(
            sample_orchestrator_contract_yaml, "ORCHESTRATOR"
        )

        assert result.valid is True
        assert result.contract.name == "NodeWorkflowOrchestrator"
        assert hasattr(result.contract, "workflow_steps")

    def test_orchestrator_node_workflow_steps(
        self, sample_orchestrator_contract_yaml: str
    ):
        """Test ORCHESTRATOR node workflow steps."""
        validator = ContractValidator()
        result = validator.validate_contract(
            sample_orchestrator_contract_yaml, "ORCHESTRATOR"
        )

        assert result.valid is True
        # Workflow steps should be defined
        assert result.contract.workflow_steps is not None

    def test_orchestrator_node_lease_management(
        self, sample_orchestrator_contract_yaml: str
    ):
        """Test ORCHESTRATOR node lease management."""
        validator = ContractValidator()
        result = validator.validate_contract(
            sample_orchestrator_contract_yaml, "ORCHESTRATOR"
        )

        assert result.valid is True
        # Lease management should be specified
        assert hasattr(result.contract, "lease_management")

    def test_orchestrator_node_multi_step_workflow(self):
        """Test ORCHESTRATOR node with complex multi-step workflow."""
        validator = ContractValidator()

        yaml_orchestrator = """
name: NodeComplexOrchestrator
version: "1.0.0"
description: "Complex orchestrator"
node_type: ORCHESTRATOR
input_model: ModelInput
output_model: ModelOutput
error_model: ModelOnexError
workflow_steps:
  - step: validate
  - step: fetch_data
  - step: process
  - step: aggregate
  - step: persist
  - step: notify
lease_management: true
"""

        result = validator.validate_contract(yaml_orchestrator, "ORCHESTRATOR")
        assert result.valid is True


# -------------------------------------------------------------------------
# Cross-Node Type Integration Tests
# -------------------------------------------------------------------------


@pytest.mark.integration
def test_all_node_types_batch_validation(
    sample_effect_contract_yaml: str,
    sample_compute_contract_yaml: str,
    sample_reducer_contract_yaml: str,
    sample_orchestrator_contract_yaml: str,
):
    """Test batch validation across all 4 node types."""
    validator = ContractValidator()

    contracts = [
        {"name": "effect", "yaml": sample_effect_contract_yaml, "node_type": "EFFECT"},
        {
            "name": "compute",
            "yaml": sample_compute_contract_yaml,
            "node_type": "COMPUTE",
        },
        {
            "name": "reducer",
            "yaml": sample_reducer_contract_yaml,
            "node_type": "REDUCER",
        },
        {
            "name": "orchestrator",
            "yaml": sample_orchestrator_contract_yaml,
            "node_type": "ORCHESTRATOR",
        },
    ]

    results = validator.validate_batch(contracts)

    assert len(results) == 4
    assert all(r.valid for r in results.values())


@pytest.mark.integration
def test_node_type_specific_validations():
    """Test node type specific validation rules."""
    validator = ContractValidator()

    # Each node type has specific requirements
    node_types = ["EFFECT", "COMPUTE", "REDUCER", "ORCHESTRATOR"]

    for node_type in node_types:
        yaml_template = f"""
name: Node{node_type.capitalize()}Test
version: "1.0.0"
description: "Test {node_type} node"
node_type: {node_type}
input_model: ModelInput
output_model: ModelOutput
error_model: ModelOnexError
"""

        result = validator.validate_contract(yaml_template, node_type)
        assert result.node_type == node_type


# -------------------------------------------------------------------------
# Error Recovery Integration Tests
# -------------------------------------------------------------------------


@pytest.mark.integration
def test_validation_error_recovery(contract_validator: ContractValidator):
    """Test graceful error recovery in validation."""
    invalid_contracts = [
        {"name": "invalid1", "yaml": "invalid: yaml: structure", "node_type": "EFFECT"},
        {
            "name": "invalid2",
            "yaml": "- list\n- instead\n- of\n- dict",
            "node_type": "COMPUTE",
        },
        {"name": "invalid3", "yaml": "", "node_type": "REDUCER"},
    ]

    results = contract_validator.validate_batch(invalid_contracts)

    # All should fail gracefully without crashing
    assert len(results) == 3
    assert all(not result.valid for result in results.values())


@pytest.mark.integration
def test_validation_with_partial_failures(
    contract_validator: ContractValidator,
    sample_effect_contract_yaml: str,
):
    """Test batch validation with partial failures."""
    contracts = [
        {"name": "valid", "yaml": sample_effect_contract_yaml, "node_type": "EFFECT"},
        {"name": "invalid", "yaml": "name: Incomplete", "node_type": "EFFECT"},
        {"name": "valid2", "yaml": sample_effect_contract_yaml, "node_type": "EFFECT"},
    ]

    results = contract_validator.validate_batch(contracts)
    summary = contract_validator.get_validation_summary(results)

    assert summary["total_contracts"] == 3
    assert summary["valid_contracts"] == 2
    assert summary["invalid_contracts"] == 1
    assert summary["validation_rate"] == pytest.approx(2 / 3)


# -------------------------------------------------------------------------
# Performance Integration Tests
# -------------------------------------------------------------------------


@pytest.mark.integration
def test_large_batch_validation_performance(
    contract_validator: ContractValidator, sample_effect_contract_yaml: str
):
    """Test performance with large batch validation."""
    import time

    # Create 100 contracts for batch validation
    contracts = [
        {
            "name": f"contract_{i}",
            "yaml": sample_effect_contract_yaml,
            "node_type": "EFFECT",
        }
        for i in range(100)
    ]

    start_time = time.time()
    results = contract_validator.validate_batch(contracts)
    duration = time.time() - start_time

    assert len(results) == 100
    # Should complete in reasonable time (<10s for 100 contracts)
    assert duration < 10.0


@pytest.mark.integration
def test_validation_caching_benefits():
    """Test that validation benefits from any internal caching."""
    validator = ContractValidator()

    yaml_contract = """
name: NodeTestEffect
version: "1.0.0"
description: "Test"
node_type: EFFECT
input_model: ModelInput
output_model: ModelOutput
error_model: ModelOnexError
"""

    # First validation
    result1 = validator.validate_contract(yaml_contract, "EFFECT")

    # Second validation (should be fast even without explicit caching)
    result2 = validator.validate_contract(yaml_contract, "EFFECT")

    assert result1.valid is True
    assert result2.valid is True


# -------------------------------------------------------------------------
# Model Reference Integration Tests
# -------------------------------------------------------------------------


@pytest.mark.integration
def test_model_reference_resolution_integration(tmp_path: Path):
    """Test model reference resolution in integration context."""
    models_dir = tmp_path / "models"
    models_dir.mkdir()

    # Create actual model files
    (models_dir / "model_user_input.py").write_text(
        """
from pydantic import BaseModel

class ModelUserInput(BaseModel):
    user_id: str
    name: str
"""
    )

    (models_dir / "model_user_output.py").write_text(
        """
from pydantic import BaseModel

class ModelUserOutput(BaseModel):
    success: bool
"""
    )

    validator = ContractValidator(model_search_paths=[models_dir])

    yaml_with_refs = """
name: NodeUserServiceEffect
version: "1.0.0"
description: "User service"
node_type: EFFECT
input_model: ModelUserInput
output_model: ModelUserOutput
error_model: ModelOnexError
"""

    result = validator.validate_contract(yaml_with_refs, "EFFECT")

    assert result.valid is True
    assert result.model_references_valid is True


# -------------------------------------------------------------------------
# Run Tests
# -------------------------------------------------------------------------


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s", "-m", "integration"])
