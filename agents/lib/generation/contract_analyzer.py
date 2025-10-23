"""
Contract Analyzer Utility for ONEX Contract Generation.

Handles loading, validation, and analysis of contract documents.
Provides consistent contract processing across all ONEX tools.

Adapted from omnibase_3 for omniclaude/omnibase_core compatibility.
Simplified version focusing on core functionality.
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import yaml

logger = logging.getLogger(__name__)


@dataclass
class ContractInfo:
    """Information about a loaded contract."""

    node_name: str
    node_version: str
    has_input_state: bool
    has_output_state: bool
    has_definitions: bool
    definition_count: int
    field_count: int
    reference_count: int
    enum_count: int


@dataclass
class ReferenceInfo:
    """Information about a discovered reference."""

    ref_string: str
    ref_type: str  # "internal", "external", "subcontract"
    resolved_type: str
    source_location: str
    target_file: Optional[str] = None


@dataclass
class ContractValidationResult:
    """Result of contract validation."""

    is_valid: bool
    errors: List[str]
    warnings: List[str]
    info: List[str]


class ContractAnalyzer:
    """
    Utility for analyzing and validating contract documents.

    Handles:
    - Contract loading and parsing from YAML
    - Contract validation (structure and required fields)
    - Reference discovery and analysis
    - Dependency analysis
    - Schema structure analysis
    - Enum discovery
    """

    def __init__(self, reference_resolver=None, enum_generator=None):
        """
        Initialize the contract analyzer.

        Args:
            reference_resolver: Optional reference resolver for $ref handling
            enum_generator: Optional enum generator for enum discovery
        """
        self.reference_resolver = reference_resolver
        self.enum_generator = enum_generator
        self.logger = logger
        self._contract_cache: Dict[str, Dict[str, Any]] = {}

    def load_contract(self, contract_path: Path) -> Dict[str, Any]:
        """
        Load and parse a contract.yaml file.

        Args:
            contract_path: Path to contract.yaml file

        Returns:
            Contract dictionary

        Raises:
            FileNotFoundError: If contract file doesn't exist
            yaml.YAMLError: If contract YAML is invalid
            ValueError: If contract structure is invalid
        """
        if not contract_path.exists():
            raise FileNotFoundError(f"Contract file not found: {contract_path}")

        # Check cache first
        cache_key = str(contract_path.resolve())
        if cache_key in self._contract_cache:
            logger.debug(
                f"Using cached contract for {contract_path}",
                extra={"path": str(contract_path)},
            )
            return self._contract_cache[cache_key]

        # Load from file
        logger.info(
            f"Loading contract from {contract_path}", extra={"path": str(contract_path)}
        )

        try:
            with open(contract_path, "r") as f:
                contract_data = yaml.safe_load(f)

            if not isinstance(contract_data, dict):
                raise ValueError(
                    f"Contract must be a YAML dictionary, got {type(contract_data)}"
                )

            # Validate basic structure
            validation_result = self.validate_contract(contract_data)
            if not validation_result.is_valid:
                error_msg = "\n".join(validation_result.errors)
                raise ValueError(f"Contract validation failed:\n{error_msg}")

            # Cache the contract
            self._contract_cache[cache_key] = contract_data

            logger.info(
                f"Successfully loaded contract: {contract_data.get('name', 'unknown')}",
                extra={
                    "name": contract_data.get("name"),
                    "version": contract_data.get("version"),
                    "has_definitions": "definitions" in contract_data,
                },
            )

            return contract_data

        except yaml.YAMLError as e:
            logger.error(
                f"Failed to parse YAML contract: {e}",
                extra={"path": str(contract_path), "error": str(e)},
            )
            raise

    def validate_contract(
        self, contract_data: Dict[str, Any]
    ) -> ContractValidationResult:
        """
        Validate contract structure and required fields.

        Args:
            contract_data: Contract dictionary to validate

        Returns:
            Validation result with errors, warnings, and info
        """
        errors: List[str] = []
        warnings: List[str] = []
        info: List[str] = []

        # Check required top-level fields
        required_fields = ["name", "version"]
        for field in required_fields:
            if field not in contract_data:
                errors.append(f"Missing required field: {field}")

        # Validate name format
        if "name" in contract_data:
            name = contract_data["name"]
            if not isinstance(name, str) or not name:
                errors.append("Contract 'name' must be a non-empty string")

        # Validate version format
        if "version" in contract_data:
            version = contract_data["version"]
            if not isinstance(version, str) or not version:
                errors.append("Contract 'version' must be a non-empty string")

        # Check for either input_state or output_state
        has_input = "input_state" in contract_data
        has_output = "output_state" in contract_data
        if not has_input and not has_output:
            warnings.append("Contract has neither input_state nor output_state")

        # Validate state schemas if present
        if has_input:
            input_state = contract_data["input_state"]
            if not isinstance(input_state, dict):
                errors.append("input_state must be a dictionary")
            else:
                # Check for required vs full_schema pattern
                if "required" in input_state and "full_schema" in input_state:
                    info.append("input_state uses required + full_schema pattern")
                elif "type" not in input_state and "properties" not in input_state:
                    warnings.append("input_state has unclear schema structure")

        if has_output:
            output_state = contract_data["output_state"]
            if not isinstance(output_state, dict):
                errors.append("output_state must be a dictionary")

        # Validate definitions if present
        if "definitions" in contract_data:
            definitions = contract_data["definitions"]
            if not isinstance(definitions, dict):
                errors.append("definitions must be a dictionary")
            else:
                info.append(f"Contract has {len(definitions)} definitions")

        is_valid = len(errors) == 0

        return ContractValidationResult(
            is_valid=is_valid, errors=errors, warnings=warnings, info=info
        )

    def analyze_contract(self, contract_data: Dict[str, Any]) -> ContractInfo:
        """
        Analyze contract and extract metadata.

        Args:
            contract_data: Contract dictionary

        Returns:
            Contract information summary
        """
        # Count fields
        field_count = 0
        if "input_state" in contract_data:
            field_count += self._count_fields(contract_data["input_state"])
        if "output_state" in contract_data:
            field_count += self._count_fields(contract_data["output_state"])

        # Count definitions
        definition_count = 0
        if "definitions" in contract_data:
            definition_count = len(contract_data["definitions"])
            # Add fields in definitions
            for def_schema in contract_data["definitions"].values():
                if isinstance(def_schema, dict):
                    field_count += self._count_fields(def_schema)

        # Count references
        reference_count = self._count_references(contract_data)

        # Count enums
        enum_count = self._count_enums(contract_data)

        return ContractInfo(
            node_name=contract_data.get("name", "unknown"),
            node_version=contract_data.get("version", "0.0.0"),
            has_input_state="input_state" in contract_data,
            has_output_state="output_state" in contract_data,
            has_definitions="definitions" in contract_data,
            definition_count=definition_count,
            field_count=field_count,
            reference_count=reference_count,
            enum_count=enum_count,
        )

    def discover_references(
        self, contract_data: Dict[str, Any], source_location: str = "root"
    ) -> List[ReferenceInfo]:
        """
        Discover all $ref references in contract.

        Args:
            contract_data: Contract or schema dictionary
            source_location: Location identifier for debugging

        Returns:
            List of discovered references
        """
        references: List[ReferenceInfo] = []
        self._collect_references(contract_data, references, source_location)
        return references

    def extract_definitions(
        self, contract_data: Dict[str, Any]
    ) -> Dict[str, Dict[str, Any]]:
        """
        Extract all definitions from contract.

        Args:
            contract_data: Contract dictionary

        Returns:
            Dictionary of definition schemas
        """
        return contract_data.get("definitions", {})

    def clear_cache(self) -> None:
        """Clear the contract cache."""
        self._contract_cache.clear()
        logger.debug("Cleared contract cache")

    # Private helper methods

    def _count_fields(self, schema: Any) -> int:
        """Count fields in a schema recursively."""
        if not isinstance(schema, dict):
            return 0

        count = 0

        # Count properties
        if "properties" in schema:
            properties = schema["properties"]
            if isinstance(properties, dict):
                count += len(properties)
                # Recursively count nested object fields
                for prop_schema in properties.values():
                    if (
                        isinstance(prop_schema, dict)
                        and prop_schema.get("type") == "object"
                    ):
                        count += self._count_fields(prop_schema)

        return count

    def _count_references(self, data: Any, visited: Optional[Set[int]] = None) -> int:
        """Count $ref references recursively."""
        if visited is None:
            visited = set()

        # Avoid infinite recursion
        data_id = id(data)
        if data_id in visited:
            return 0
        visited.add(data_id)

        count = 0

        if isinstance(data, dict):
            if "$ref" in data:
                count += 1
            for value in data.values():
                count += self._count_references(value, visited)
        elif isinstance(data, list):
            for item in data:
                count += self._count_references(item, visited)

        return count

    def _count_enums(self, data: Any, visited: Optional[Set[int]] = None) -> int:
        """Count enum definitions recursively."""
        if visited is None:
            visited = set()

        # Avoid infinite recursion
        data_id = id(data)
        if data_id in visited:
            return 0
        visited.add(data_id)

        count = 0

        if isinstance(data, dict):
            # Check if this is an enum definition
            if data.get("type") == "string" and "enum" in data:
                count += 1

            # Recursively check nested structures
            for value in data.values():
                count += self._count_enums(value, visited)
        elif isinstance(data, list):
            for item in data:
                count += self._count_enums(item, visited)

        return count

    def _collect_references(
        self, data: Any, references: List[ReferenceInfo], source_location: str
    ) -> None:
        """Collect all $ref references from data structure."""
        if isinstance(data, dict):
            if "$ref" in data:
                ref_string = data["$ref"]

                # Determine reference type
                if ref_string.startswith("#/definitions/"):
                    ref_type = "internal"
                    target_file = None
                elif ref_string.startswith("contracts/"):
                    ref_type = "subcontract"
                    target_file = (
                        ref_string.split("#")[0] if "#" in ref_string else ref_string
                    )
                else:
                    ref_type = "external"
                    target_file = (
                        ref_string.split("#")[0] if "#" in ref_string else None
                    )

                # Resolve type if resolver available
                if self.reference_resolver:
                    resolved_type = self.reference_resolver.resolve_ref(ref_string)
                else:
                    resolved_type = ref_string.split("/")[-1]

                references.append(
                    ReferenceInfo(
                        ref_string=ref_string,
                        ref_type=ref_type,
                        resolved_type=resolved_type,
                        source_location=source_location,
                        target_file=target_file,
                    )
                )

            # Recursively search nested dicts
            for key, value in data.items():
                self._collect_references(value, references, f"{source_location}.{key}")

        elif isinstance(data, list):
            for i, item in enumerate(data):
                self._collect_references(item, references, f"{source_location}[{i}]")
