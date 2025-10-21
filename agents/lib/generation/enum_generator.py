"""
Enum Generator Utility for ONEX Contract Generation.

Handles discovery and generation of enum classes from JSON Schema definitions.
Provides consistent enum generation with ONEX naming conventions (Enum prefix).

Adapted from omnibase_3 for omniclaude/omnibase_core compatibility.
"""

import ast
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class EnumInfo:
    """Information about a discovered enum."""

    name: str
    values: List[str]
    source_field: str
    source_schema: Optional[str] = None


class EnumGenerator:
    """
    Utility for discovering and generating enum classes from schemas.

    Handles:
    - Recursive discovery of enum fields in schemas
    - Generation of enum class names from values (with Enum prefix)
    - Creation of enum AST nodes
    - Deduplication of enum definitions
    - ONEX naming convention enforcement
    """

    def __init__(self, type_mapper=None):
        """
        Initialize the enum generator.

        Args:
            type_mapper: Optional type mapper utility for name generation
        """
        self.type_mapper = type_mapper
        self.logger = logger

    def discover_enums_from_contract(
        self, contract_data: Dict[str, Any]
    ) -> List[EnumInfo]:
        """
        Discover all enum definitions from a contract document.

        Args:
            contract_data: Contract document dictionary

        Returns:
            List of discovered enum information
        """
        if not isinstance(contract_data, dict):
            raise ValueError(f"Expected dict contract_data, got {type(contract_data)}")

        enum_schemas: Dict[str, Dict[str, Any]] = {}

        # Check input_state
        if "input_state" in contract_data:
            self._collect_enum_schemas_from_dict(
                contract_data["input_state"],
                enum_schemas,
                source_schema="input_state",
            )

        # Check output_state
        if "output_state" in contract_data:
            self._collect_enum_schemas_from_dict(
                contract_data["output_state"],
                enum_schemas,
                source_schema="output_state",
            )

        # Check definitions
        if "definitions" in contract_data:
            logger.info(
                f"Checking {len(contract_data['definitions'])} definitions for enums",
                extra={"definition_count": len(contract_data["definitions"])},
            )
            for def_name, def_schema in contract_data["definitions"].items():
                logger.debug(
                    f"Checking definition '{def_name}' for enum patterns",
                    extra={
                        "definition_name": def_name,
                        "has_enum": (
                            "enum" in def_schema
                            if isinstance(def_schema, dict)
                            else False
                        ),
                        "schema_type": (
                            def_schema.get("type", "unknown")
                            if isinstance(def_schema, dict)
                            else "none"
                        ),
                    },
                )
                self._collect_enum_schemas_from_dict(
                    def_schema,
                    enum_schemas,
                    source_schema=f"definitions.{def_name}",
                )

        # Convert to EnumInfo objects
        enums = []
        for enum_name, info in enum_schemas.items():
            enum_info = EnumInfo(
                name=enum_name,
                values=info["values"],
                source_field=info["source_field"],
                source_schema=info["source_schema"],
            )
            enums.append(enum_info)

        logger.info(
            f"Discovered {len(enums)} enum definitions",
            extra={"enum_count": len(enums)},
        )

        return enums

    def generate_enum_class(
        self,
        class_name: str,
        enum_values: List[str],
        enum_type: str = "str",
    ) -> ast.ClassDef:
        """
        Generate enum class AST node.

        Args:
            class_name: Name of the enum class (must start with "Enum")
            enum_values: List of enum values
            enum_type: Base enum type ("str" or "int")

        Returns:
            AST ClassDef node for the enum

        Raises:
            ValueError: If class_name doesn't start with "Enum"
        """
        if not class_name.startswith("Enum"):
            raise ValueError(
                f"Enum class name must start with 'Enum' (ONEX naming convention). "
                f"Got: {class_name}"
            )

        # Create class with str/int and Enum as bases
        bases = [
            ast.Name(id=enum_type, ctx=ast.Load()),
            ast.Name(id="Enum", ctx=ast.Load()),
        ]

        body = []

        # Add docstring
        docstring = f"{class_name} enumeration from contract definitions."
        body.append(ast.Expr(value=ast.Constant(value=docstring)))

        # Add enum values
        for enum_value in enum_values:
            # Convert value to UPPER_SNAKE_CASE for member name
            attr_name = enum_value.upper().replace("-", "_").replace(" ", "_")
            assignment = ast.Assign(
                targets=[ast.Name(id=attr_name, ctx=ast.Store())],
                value=ast.Constant(value=enum_value),
            )
            body.append(assignment)

        # If no values, add pass
        if len(body) == 1:  # Only docstring
            body.append(ast.Pass())

        class_def = ast.ClassDef(
            name=class_name,
            bases=bases,
            keywords=[],
            decorator_list=[],
            body=body,
        )

        # Fix missing locations for proper AST
        ast.fix_missing_locations(class_def)

        logger.debug(
            f"Generated enum class {class_name}",
            extra={
                "enum_name": class_name,
                "value_count": len(enum_values),
                "enum_type": enum_type,
            },
        )

        return class_def

    def generate_enum_classes(self, enum_infos: List[EnumInfo]) -> List[ast.ClassDef]:
        """
        Generate AST class definitions for enum info objects.

        Args:
            enum_infos: List of enum information objects

        Returns:
            List of AST ClassDef nodes for enum classes
        """
        enum_classes = []

        for enum_info in enum_infos:
            enum_class = self.generate_enum_class(enum_info.name, enum_info.values)
            enum_classes.append(enum_class)

            logger.debug(
                f"Generated enum class {enum_info.name}",
                extra={
                    "enum_name": enum_info.name,
                    "value_count": len(enum_info.values),
                    "source": enum_info.source_schema,
                },
            )

        return enum_classes

    def generate_enum_name_from_values(self, enum_values: List[str]) -> str:
        """
        Generate an enum class name from enum values.

        Uses ONEX naming convention: Enum prefix + PascalCase.

        Args:
            enum_values: List of enum string values

        Returns:
            Generated enum class name (e.g., "EnumStatus", "EnumProcessingMode")
        """
        if self.type_mapper:
            return self.type_mapper.generate_enum_name_from_values(enum_values)

        # Fallback name generation
        if not enum_values:
            return "EnumGeneric"

        first_value = enum_values[0]
        if not isinstance(first_value, str):
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

    def generate_enum_name_from_schema(self, schema: Dict[str, Any]) -> str:
        """
        Generate enum class name from schema context.

        Args:
            schema: Schema definition dict

        Returns:
            Generated enum class name
        """
        if not isinstance(schema, dict):
            return "EnumGeneric"

        enum_values = schema.get("enum", [])
        return self.generate_enum_name_from_values(enum_values)

    def deduplicate_enums(self, enum_infos: List[EnumInfo]) -> List[EnumInfo]:
        """
        Remove duplicate enum definitions based on values.

        Args:
            enum_infos: List of enum information objects

        Returns:
            Deduplicated list of enum information objects
        """
        seen_values: Dict[tuple, EnumInfo] = {}
        deduplicated = []

        for enum_info in enum_infos:
            # Create a hashable key from sorted values
            values_key = tuple(sorted(enum_info.values))

            if values_key not in seen_values:
                seen_values[values_key] = enum_info
                deduplicated.append(enum_info)
            else:
                # Log duplicate found
                existing = seen_values[values_key]
                logger.debug(
                    f"Duplicate enum found: {enum_info.name} matches {existing.name}",
                    extra={
                        "duplicate_name": enum_info.name,
                        "existing_name": existing.name,
                        "values": enum_info.values,
                    },
                )

        logger.info(
            f"Deduplicated {len(enum_infos) - len(deduplicated)} enum definitions",
            extra={
                "original_count": len(enum_infos),
                "deduplicated_count": len(deduplicated),
                "removed_count": len(enum_infos) - len(deduplicated),
            },
        )

        return deduplicated

    # Private helper methods

    def _collect_enum_schemas_from_dict(
        self,
        schema: Any,
        enum_schemas: Dict[str, Dict[str, Any]],
        source_schema: str = "unknown",
    ) -> None:
        """
        Collect enum schemas from a dict-based schema definition.

        Args:
            schema: Schema definition (dict or other)
            enum_schemas: Dictionary to collect discovered enums into
            source_schema: Source location for debugging
        """
        if not isinstance(schema, dict):
            logger.debug(
                f"Skipping non-dict schema in {source_schema}",
                extra={
                    "source_schema": source_schema,
                    "schema_type": type(schema).__name__,
                },
            )
            return

        logger.debug(
            f"Examining schema in {source_schema}",
            extra={
                "source_schema": source_schema,
                "schema_type": schema.get("type", "NO_TYPE"),
                "has_enum": "enum" in schema,
                "enum_values": schema.get("enum", None),
                "properties_count": len(schema.get("properties", {})),
            },
        )

        # Check if this schema itself is an enum
        if schema.get("type") == "string" and "enum" in schema:
            enum_name = self.generate_enum_name_from_schema(schema)

            logger.debug(
                f"Found enum in schema '{source_schema}'",
                extra={
                    "original_source": source_schema,
                    "generated_name": enum_name,
                    "enum_values": schema["enum"],
                    "schema_type": schema.get("type"),
                },
            )

            enum_schemas[enum_name] = {
                "values": schema["enum"],
                "source_field": "root",
                "source_schema": source_schema,
            }

        # Check properties for nested enums
        if "properties" in schema:
            for field_name, field_schema in schema["properties"].items():
                if not isinstance(field_schema, dict):
                    continue

                if field_schema.get("type") == "string" and "enum" in field_schema:
                    enum_name = self.generate_enum_name_from_schema(field_schema)
                    enum_schemas[enum_name] = {
                        "values": field_schema["enum"],
                        "source_field": field_name,
                        "source_schema": source_schema,
                    }

                # Recursively check nested objects
                if field_schema.get("type") == "object":
                    self._collect_enum_schemas_from_dict(
                        field_schema, enum_schemas, f"{source_schema}.{field_name}"
                    )
                elif field_schema.get("type") == "array" and "items" in field_schema:
                    self._collect_enum_schemas_from_dict(
                        field_schema["items"],
                        enum_schemas,
                        f"{source_schema}.{field_name}[]",
                    )
