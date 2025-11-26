#!/usr/bin/env python3
"""
Contract Schema Validator - Phase 2 Stream D

Validates generated contracts against omnibase_core Pydantic schemas.
Ensures 100% schema compliance and proper model reference resolution.

Features:
- Pydantic model validation for all 4 node types
- Schema compliance checking
- Subcontract reference validation
- Model reference validation
- Contract structure validation
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

# Import omnibase_core contracts
from omnibase_core.models.contracts import (
    ModelContractBase,
    ModelContractCompute,
    ModelContractEffect,
    ModelContractOrchestrator,
    ModelContractReducer,
)
from pydantic import BaseModel, Field, ValidationError


logger = logging.getLogger(__name__)


class ModelReferenceError(Exception):
    """Raised when model reference validation fails."""

    pass


class ValidationResult(BaseModel):
    """
    Contract validation result.

    Tracks validation status, contract object (if valid),
    and detailed error information.
    """

    valid: bool = Field(..., description="Whether contract is valid")
    contract: Optional[ModelContractBase] = Field(
        default=None, description="Validated contract object (if valid)"
    )
    errors: List[Dict[str, Any]] = Field(
        default_factory=list, description="Validation errors"
    )
    warnings: List[str] = Field(default_factory=list, description="Validation warnings")
    node_type: Optional[str] = Field(
        default=None, description="Validated node type (EFFECT, COMPUTE, etc.)"
    )
    model_references_valid: bool = Field(
        default=True, description="Whether all model references are valid"
    )
    schema_compliance: bool = Field(
        default=True, description="Whether contract complies with schema"
    )

    class Config:
        """Pydantic configuration."""

        arbitrary_types_allowed = True

    def get_error_summary(self) -> str:
        """Generate human-readable error summary."""
        if self.valid:
            return "Contract is valid"

        lines = ["Contract validation failed:"]
        for error in self.errors:
            loc = " -> ".join(str(loc_item) for loc_item in error.get("loc", []))
            msg = error.get("msg", "Unknown error")
            lines.append(f"  - {loc}: {msg}")

        if self.warnings:
            lines.append("\nWarnings:")
            for warning in self.warnings:
                lines.append(f"  - {warning}")

        return "\n".join(lines)


class ContractValidator:
    """
    Validates contracts against omnibase_core schemas.

    Provides comprehensive validation including:
    - Pydantic model validation
    - Schema compliance checking
    - Model reference resolution
    - Subcontract validation
    """

    # Mapping of node types to contract models
    CONTRACT_MODELS = {
        "EFFECT": ModelContractEffect,
        "COMPUTE": ModelContractCompute,
        "REDUCER": ModelContractReducer,
        "ORCHESTRATOR": ModelContractOrchestrator,
    }

    def __init__(self, model_search_paths: Optional[List[Path]] = None):
        """
        Initialize contract validator.

        Args:
            model_search_paths: Optional list of paths to search for model files
        """
        self.logger = logging.getLogger(__name__)
        self.model_search_paths = model_search_paths or []

    def validate_contract(self, contract_yaml: str, node_type: str) -> ValidationResult:
        """
        Validate contract YAML against schema.

        Args:
            contract_yaml: YAML string containing contract definition
            node_type: Node type (EFFECT, COMPUTE, REDUCER, ORCHESTRATOR)

        Returns:
            ValidationResult with validation status and details

        Raises:
            ValueError: If node_type is invalid
        """
        if node_type not in self.CONTRACT_MODELS:
            raise ValueError(
                f"Invalid node type: {node_type}. "
                f"Must be one of {list(self.CONTRACT_MODELS.keys())}"
            )

        result = ValidationResult(valid=False, node_type=node_type)

        try:
            # Parse YAML to dict
            contract_dict = yaml.safe_load(contract_yaml)

            if not isinstance(contract_dict, dict):
                result.errors.append(
                    {
                        "loc": ["root"],
                        "msg": "Contract YAML must be a dictionary",
                        "type": "type_error",
                    }
                )
                result.schema_compliance = False
                return result

            # Convert string types to proper objects BEFORE Pydantic validation
            contract_dict = self._convert_yaml_types(contract_dict)

            # Get appropriate contract model
            contract_model = self._get_contract_model(node_type)

            # Validate using Pydantic
            try:
                # NOTE: ModelContractCompute has a known upstream bug where __init__
                # doesn't pass the 'algorithm' field to the parent constructor.
                # This causes validation failures for COMPUTE contracts.
                # Additionally, model_post_init() expects all nested dicts (algorithm,
                # performance, dependencies) to be converted to proper Pydantic models.
                #
                # Bug Location: omnibase_core.models.contracts.ModelContractCompute.__init__
                # Workaround: See tests/generation/test_contract_validator.py::test_validate_compute_contract_success
                # Reference: omninode_bridge adapter pattern in src/omninode_bridge/nodes/conftest.py
                # Status: No upstream issue filed - this should be reported to omnibase_core maintainers
                # FIXME: Remove this workaround when upstream bug is fixed in omnibase_core
                contract = contract_model(**contract_dict)
                result.contract = contract
                result.valid = True
                result.schema_compliance = True

                # Validate model references
                model_errors = self._validate_model_references(contract)
                if model_errors:
                    result.model_references_valid = False
                    result.warnings.extend(model_errors)
                    # Don't fail validation for reference errors, just warn
                    self.logger.warning(
                        f"Model reference warnings: {', '.join(model_errors)}"
                    )

                self.logger.info(
                    f"Contract validation passed for {node_type} node: {contract.name}"
                )

            except ValidationError as e:
                result.errors = e.errors()
                result.schema_compliance = False
                self.logger.error(
                    f"Contract validation failed for {node_type}: {e.error_count()} errors"
                )

        except yaml.YAMLError as e:
            result.errors.append(
                {
                    "loc": ["yaml"],
                    "msg": f"YAML parsing error: {str(e)}",
                    "type": "yaml_error",
                }
            )
            result.schema_compliance = False
            self.logger.error(f"YAML parsing error: {e}")

        except Exception as e:
            result.errors.append(
                {
                    "loc": ["unknown"],
                    "msg": f"Unexpected error: {str(e)}",
                    "type": "unexpected_error",
                }
            )
            result.schema_compliance = False
            self.logger.exception("Unexpected error during contract validation")

        return result

    def validate_contract_file(
        self, contract_path: Path, node_type: str
    ) -> ValidationResult:
        """
        Validate contract from file.

        Args:
            contract_path: Path to contract YAML file
            node_type: Node type (EFFECT, COMPUTE, REDUCER, ORCHESTRATOR)

        Returns:
            ValidationResult with validation status and details
        """
        if not contract_path.exists():
            result = ValidationResult(valid=False, node_type=node_type)
            result.errors.append(
                {
                    "loc": ["file"],
                    "msg": f"Contract file not found: {contract_path}",
                    "type": "file_not_found",
                }
            )
            return result

        contract_yaml = contract_path.read_text(encoding="utf-8")
        return self.validate_contract(contract_yaml, node_type)

    def _get_contract_model(self, node_type: str):
        """
        Get contract model class for node type.

        Args:
            node_type: Node type (EFFECT, COMPUTE, REDUCER, ORCHESTRATOR)

        Returns:
            Contract model class
        """
        return self.CONTRACT_MODELS[node_type]

    def _validate_model_references(self, contract: ModelContractBase) -> List[str]:
        """
        Verify all model references exist.

        Args:
            contract: Validated contract object

        Returns:
            List of error messages (empty if all references valid)
        """
        errors = []

        # Check input_model reference
        if hasattr(contract, "input_model") and contract.input_model:
            if not self._model_exists(contract.input_model):
                errors.append(f"Input model not found: {contract.input_model}")

        # Check output_model reference
        if hasattr(contract, "output_model") and contract.output_model:
            if not self._model_exists(contract.output_model):
                errors.append(f"Output model not found: {contract.output_model}")

        # Check error_model reference
        if hasattr(contract, "error_model") and contract.error_model:
            if not self._model_exists(contract.error_model):
                errors.append(f"Error model not found: {contract.error_model}")

        return errors

    def _model_exists(self, model_name: str) -> bool:
        """
        Check if model file exists.

        Args:
            model_name: Model name (e.g., ModelDatabaseInput)

        Returns:
            True if model file found, False otherwise
        """
        # Convert ModelDatabaseInput -> model_database_input.py
        model_file_name = self._model_name_to_filename(model_name)

        # Search in configured paths
        for search_path in self.model_search_paths:
            model_path = search_path / model_file_name
            if model_path.exists():
                return True

        # If no search paths configured or file not found, return True
        # to avoid false positives (models might be in omnibase_core)
        if not self.model_search_paths:
            return True

        return False

    def _model_name_to_filename(self, model_name: str) -> str:
        """
        Convert model name to filename.

        Args:
            model_name: Model name (e.g., ModelDatabaseInput)

        Returns:
            Filename (e.g., model_database_input.py)
        """
        # ModelDatabaseInput -> database_input
        name = model_name.replace("Model", "")

        # Convert PascalCase to snake_case
        name = "".join(["_" + c.lower() if c.isupper() else c for c in name]).lstrip(
            "_"
        )

        return f"model_{name}.py"

    def _convert_yaml_types(self, contract_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert YAML string types to proper Python objects for Pydantic validation.

        This method handles the conversion of string values from YAML contracts
        into the typed objects expected by omnibase_core contract models:
        - String node_type → EnumNodeType enum
        - String version → ModelSemVer object
        - Dict dependencies → List[ModelDependency]
        - Dict algorithm → ModelAlgorithmConfig (for COMPUTE nodes)

        Args:
            contract_dict: Raw contract dictionary from YAML parsing

        Returns:
            Dictionary with converted types ready for Pydantic validation
        """
        # Import here to avoid circular dependencies and handle missing omnibase_core gracefully
        try:
            from omnibase_core.enums import EnumNodeType
            from omnibase_core.models.contracts.model_algorithm_config import (
                ModelAlgorithmConfig,
            )
            from omnibase_core.models.contracts.model_dependency import ModelDependency
            from omnibase_core.primitives.model_semver import ModelSemVer
        except ImportError:
            # If omnibase_core is not available, log warning and return unchanged
            # This allows tests to run in environments without full omnibase_core installation
            self.logger.warning(
                "omnibase_core not available, skipping type conversion. "
                "Contract validation may fail with type errors."
            )
            return contract_dict

        # Create a copy to avoid modifying the original
        converted = contract_dict.copy()

        # Convert string node_type to EnumNodeType enum
        if "node_type" in converted and isinstance(converted["node_type"], str):
            try:
                # Convert string to lowercase and create enum
                # e.g., "EFFECT" → EnumNodeType.EFFECT
                node_type_str = converted["node_type"].upper()
                converted["node_type"] = EnumNodeType[node_type_str]
                self.logger.debug(
                    f"Converted node_type from string '{contract_dict['node_type']}' "
                    f"to EnumNodeType.{node_type_str}"
                )
            except KeyError:
                # Invalid node_type value - let Pydantic validation catch it
                self.logger.warning(
                    f"Invalid node_type value: {converted['node_type']}. "
                    "Pydantic validation will report this error."
                )

        # Convert string version to ModelSemVer object
        if "version" in converted and isinstance(converted["version"], str):
            try:
                # Parse version string into ModelSemVer object
                # e.g., "1.0.0" → ModelSemVer(major=1, minor=0, patch=0)
                version_str = converted["version"]
                converted["version"] = ModelSemVer.parse(version_str)
                self.logger.debug(
                    f"Converted version from string '{version_str}' to ModelSemVer object"
                )
            except Exception as e:
                # Invalid version format - let Pydantic validation catch it
                self.logger.warning(
                    f"Failed to parse version '{converted['version']}': {e}. "
                    "Pydantic validation will report this error."
                )

        # Convert dict dependencies to List[ModelDependency]
        dependencies_raw = converted.get("dependencies")
        if dependencies_raw is not None:
            try:
                # Validate that dependencies is iterable (list or tuple)
                if isinstance(dependencies_raw, (list, tuple)):
                    converted_deps: List[Any] = []
                    for dep in dependencies_raw:
                        if isinstance(dep, dict):
                            converted_deps.append(ModelDependency(**dep))
                        else:
                            converted_deps.append(dep)  # Already converted
                    converted["dependencies"] = converted_deps
                    self.logger.debug(
                        f"Converted {len(converted_deps)} dependencies to ModelDependency objects"
                    )
                else:
                    self.logger.warning(
                        f"Dependencies must be a list or tuple, got {type(dependencies_raw).__name__}. "
                        "Pydantic validation will report this error."
                    )
            except Exception as e:
                self.logger.warning(
                    f"Failed to convert dependencies: {e}. "
                    "Pydantic validation will report this error."
                )

        # Convert dict algorithm to ModelAlgorithmConfig (for COMPUTE nodes)
        if "algorithm" in converted and isinstance(converted["algorithm"], dict):
            try:
                # Pydantic will handle nested ModelAlgorithmFactorConfig conversion
                converted["algorithm"] = ModelAlgorithmConfig(**converted["algorithm"])
                self.logger.debug("Converted algorithm to ModelAlgorithmConfig object")
            except Exception as e:
                self.logger.warning(
                    f"Failed to convert algorithm: {e}. "
                    "Pydantic validation will report this error."
                )

        return converted

    def validate_batch(
        self, contracts: List[Dict[str, Any]]
    ) -> Dict[str, ValidationResult]:
        """
        Validate multiple contracts.

        Args:
            contracts: List of dicts with 'yaml' and 'node_type' keys

        Returns:
            Dict mapping contract names to validation results
        """
        results = {}

        for contract_data in contracts:
            contract_yaml = contract_data["yaml"]
            node_type = contract_data["node_type"]
            contract_name = contract_data.get("name", f"contract_{len(results)}")

            result = self.validate_contract(contract_yaml, node_type)
            results[contract_name] = result

        return results

    def get_validation_summary(
        self, results: Dict[str, ValidationResult]
    ) -> Dict[str, Any]:
        """
        Generate validation summary for batch results.

        Args:
            results: Dict mapping contract names to validation results

        Returns:
            Summary dict with statistics
        """
        total = len(results)
        valid = sum(1 for r in results.values() if r.valid)
        invalid = total - valid

        return {
            "total_contracts": total,
            "valid_contracts": valid,
            "invalid_contracts": invalid,
            "validation_rate": valid / total if total > 0 else 0.0,
            "failed_contracts": [
                name for name, result in results.items() if not result.valid
            ],
        }
