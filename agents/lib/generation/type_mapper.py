"""
Type Mapper Utility for ONEX Contract Generation.

Handles mapping of JSON Schema types to Python type annotations.
Provides consistent type string generation across all ONEX tools.

Adapted from omnibase_3 for omniclaude/omnibase_core compatibility.
"""

import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class TypeMapper:
    """
    Utility for mapping schema types to Python type strings.

    Handles:
    - Basic type mapping (string -> str, etc.)
    - Array type generation (List[T])
    - Object type mapping (Dict or custom models)
    - Reference resolution
    - Enum name generation
    - Format-based type mapping (datetime, uuid, etc.)
    """

    # Basic type mappings
    BASIC_TYPE_MAPPING = {
        "string": "str",
        "integer": "int",
        "number": "float",
        "boolean": "bool",
        "null": "None",
    }

    # Format-based type mappings
    FORMAT_MAPPINGS = {
        "date-time": "datetime",
        "datetime": "datetime",
        "date": "date",
        "time": "time",
        "uuid": "UUID",
        "email": "str",  # Could use pydantic.EmailStr
        "uri": "str",
        "hostname": "str",
    }

    # omnibase_core-specific type mappings
    OMNIBASE_CORE_TYPES = {
        "ModelONEXContainer": "omnibase_core.models.container.model_onex_container.ModelONEXContainer",
        "ModelOnexError": "omnibase_core.errors.model_onex_error.ModelOnexError",
        "EnumCoreErrorCode": "omnibase_core.errors.error_codes.EnumCoreErrorCode",
        "ModelContractBase": "omnibase_core.models.contracts.model_contract_base.ModelContractBase",
        "ModelContractEffect": "omnibase_core.models.contracts.model_contract_effect.ModelContractEffect",
        "ModelContractCompute": "omnibase_core.models.contracts.model_contract_compute.ModelContractCompute",
        "ModelContractReducer": "omnibase_core.models.contracts.model_contract_reducer.ModelContractReducer",
        "ModelContractOrchestrator": "omnibase_core.models.contracts.model_contract_orchestrator.ModelContractOrchestrator",
    }

    def __init__(self, reference_resolver=None):
        """
        Initialize the type mapper.

        Args:
            reference_resolver: Optional reference resolver for handling $refs
        """
        self.reference_resolver = reference_resolver
        self.logger = logger

    def get_type_string_from_schema(self, schema: Dict[str, Any]) -> str:
        """
        Get type string representation from schema.

        Args:
            schema: Schema dictionary to convert to type string

        Returns:
            Python type string (e.g., "str", "List[int]", "ModelUser")

        Raises:
            ValueError: If schema type cannot be mapped (zero tolerance for 'Any')
        """
        if not isinstance(schema, dict):
            raise ValueError(
                f"Expected dict schema, got {type(schema)}. "
                f"Schema must be a dictionary with at least a 'type' key."
            )

        # Handle references
        if "$ref" in schema:
            return self._resolve_ref_name(schema["$ref"])

        schema_type = schema.get("type", "string")

        # Handle enums
        if schema_type == "string" and "enum" in schema:
            return self.generate_enum_name_from_values(schema["enum"])

        # Handle arrays
        if schema_type == "array":
            return self.get_array_type_string(schema)

        # Handle objects
        if schema_type == "object":
            return self.get_object_type_string(schema)

        # Handle string with format specifiers
        if schema_type == "string" and "format" in schema:
            schema_format = schema["format"]
            if schema_format in self.FORMAT_MAPPINGS:
                return self.FORMAT_MAPPINGS[schema_format]
            else:
                logger.warning(
                    f"Unknown format '{schema_format}' for string type, using 'str'",
                    extra={"schema_type": schema_type, "format": schema_format},
                )

        # Handle basic types
        python_type = self.BASIC_TYPE_MAPPING.get(schema_type, None)

        if python_type is None:
            # Zero tolerance for 'Any' - fail explicitly
            raise ValueError(
                f"Cannot map schema type '{schema_type}' to Python type. "
                f"Zero tolerance for 'Any' types. Add explicit type mapping."
            )

        return python_type

    def get_array_type_string(self, schema: Dict[str, Any]) -> str:
        """
        Get array type string from schema.

        Args:
            schema: Schema dictionary with array type

        Returns:
            Array type string (e.g., "List[str]", "List[ModelUser]")
        """
        if "items" not in schema:
            raise ValueError(
                "Array schema missing 'items' field. "
                "Cannot generate List type without item type specification."
            )

        items = schema["items"]

        # Handle $ref in items
        if isinstance(items, dict) and "$ref" in items:
            ref_name = self._resolve_ref_name(items["$ref"])
            return f"List[{ref_name}]"

        # Handle typed items
        if isinstance(items, dict) and "type" in items:
            item_type = self.get_type_string_from_schema(items)
            return f"List[{item_type}]"

        # Should never reach here due to validation above
        raise ValueError(f"Invalid array items schema: {items}")

    def get_object_type_string(self, schema: Dict[str, Any]) -> str:
        """
        Get object type string from schema.

        Args:
            schema: Schema dictionary with object type

        Returns:
            Object type string (e.g., "Dict[str, int]", "ModelObjectData")
        """
        # Check if this is a dictionary with additionalProperties
        if "additionalProperties" in schema:
            additional_props = schema["additionalProperties"]

            # additionalProperties: true
            if additional_props is True:
                # ONEX COMPLIANCE: Never use Dict[str, Any]
                # Use generic structured data model instead
                return "Dict[str, Any]"  # TODO: Replace with ModelObjectData when available

            # additionalProperties: {type: "string"}
            if isinstance(additional_props, dict) and "type" in additional_props:
                value_type = self.get_type_string_from_schema(additional_props)
                return f"Dict[str, {value_type}]"

        # Has defined properties - use structured model
        if "properties" in schema:
            # This should be a named model, not a dict
            # The calling code should handle this case
            return "Dict[str, Any]"  # Placeholder - should be replaced by model name

        # Generic object - use structured type per ONEX standards
        return "Dict[str, Any]"  # TODO: Replace with ModelObjectData when available

    def generate_enum_name_from_values(self, enum_values: List[str]) -> str:
        """
        Generate enum class name from enum values.

        Args:
            enum_values: List of enum string values

        Returns:
            Generated enum class name with "Enum" prefix (e.g., "EnumStatus")
        """
        if not enum_values:
            return "EnumGeneric"

        # Use first value to generate name
        first_value = enum_values[0]

        if not first_value:
            return "EnumGeneric"

        logger.debug(
            "Generating enum name from values",
            extra={"input_values": enum_values, "first_value": first_value},
        )

        # Replace hyphens with underscores first
        clean_value = first_value.replace("-", "_")

        # Handle snake_case values (including those that had hyphens)
        if "_" in clean_value:
            parts = clean_value.split("_")
            generated_name = "Enum" + "".join(word.capitalize() for word in parts)
            logger.debug(
                "Snake case enum name generated",
                extra={"snake_case_parts": parts, "generated_name": generated_name},
            )
            return generated_name
        else:
            # Handle single word values
            generated_name = f"Enum{clean_value.capitalize()}"
            logger.debug(
                "Single word enum name generated",
                extra={"generated_name": generated_name},
            )
            return generated_name

    def _resolve_ref_name(self, ref: str) -> str:
        """
        Resolve a $ref to a type name.

        Args:
            ref: Reference string (e.g., "#/definitions/ModelUser")

        Returns:
            Resolved type name (e.g., "ModelUser")

        Raises:
            ValueError: If reference cannot be resolved
        """
        if self.reference_resolver:
            # Use injected resolver if available
            return self.reference_resolver.resolve_ref(ref)

        # Simple fallback resolution for local references
        if ref.startswith("#/definitions/"):
            name = ref.split("/")[-1]
            return name if name.startswith("Model") else f"Model{name}"

        # For external refs, just use the last part
        if "#/" in ref:
            _, type_part = ref.split("#/", 1)
            name = type_part.split("/")[-1]
            return name if name.startswith("Model") else f"Model{name}"

        # No fallbacks - fail if we can't resolve the reference
        raise ValueError(
            f"Unable to resolve reference: {ref}. "
            f"Provide a reference_resolver or use local #/definitions/ references."
        )

    def resolve_ref_name(self, ref: str) -> str:
        """
        Public method to resolve reference names.

        This allows the type mapper to be used as a reference resolver
        by other components.

        Args:
            ref: Reference string (e.g., "#/definitions/ModelUser")

        Returns:
            Resolved type name (e.g., "ModelUser")
        """
        return self._resolve_ref_name(ref)

    def get_import_for_type(self, type_string: str) -> Optional[str]:
        """
        Get the import statement needed for a type string.

        Args:
            type_string: Python type string

        Returns:
            Import statement if needed, None otherwise
        """
        if type_string.startswith("List["):
            return "from typing import List"
        elif type_string.startswith("Dict["):
            return "from typing import Dict"
        elif type_string == "Any":
            return "from typing import Any"
        elif type_string.startswith("Optional["):
            return "from typing import Optional"
        elif type_string.startswith("Union["):
            return "from typing import Union"
        elif type_string == "datetime":
            return "from datetime import datetime"
        elif type_string == "date":
            return "from datetime import date"
        elif type_string == "time":
            return "from datetime import time"
        elif type_string == "UUID":
            return "from uuid import UUID"
        elif type_string in self.OMNIBASE_CORE_TYPES:
            # Return the full import path for omnibase_core types
            return f"from {self.OMNIBASE_CORE_TYPES[type_string].rsplit('.', 1)[0]} import {type_string}"

        return None

    def is_model_type(self, type_string: str) -> bool:
        """
        Check if a type string represents a model type.

        Args:
            type_string: Python type string

        Returns:
            True if this is a model type that needs importing
        """
        # Check if it's a model type
        if type_string.startswith("Model"):
            return True

        # Check if it's an enum type
        if type_string.startswith("Enum"):
            return True

        # Check if it's inside a generic
        if "[" in type_string:
            # Extract inner type(s)
            inner = re.search(r"\[(.*)\]", type_string)
            if inner:
                inner_types = inner.group(1).split(",")
                return any(self.is_model_type(t.strip()) for t in inner_types)

        return False

    def get_python_type(
        self, schema_type: str, schema_format: Optional[str] = None
    ) -> str:
        """
        Get Python type from schema type and optional format.

        This is a convenience method for simple type mapping without full schema.

        Args:
            schema_type: Schema type (string, integer, etc.)
            schema_format: Optional format specifier (date-time, uuid, etc.)

        Returns:
            Python type string

        Raises:
            ValueError: If type cannot be mapped
        """
        # Check format first
        if schema_format and schema_format in self.FORMAT_MAPPINGS:
            return self.FORMAT_MAPPINGS[schema_format]

        # Check omnibase_core types
        if schema_type in self.OMNIBASE_CORE_TYPES:
            return schema_type

        # Check standard mappings
        python_type = self.BASIC_TYPE_MAPPING.get(schema_type, None)

        if python_type is None:
            raise ValueError(
                f"Cannot map schema type '{schema_type}' to Python type. "
                f"Zero tolerance for 'Any' types."
            )

        return python_type
