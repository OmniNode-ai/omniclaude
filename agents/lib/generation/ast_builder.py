"""
AST Builder Utility for ONEX Contract Generation.

Handles generation of Python AST nodes for Pydantic models, enums, and fields.
Provides type-safe AST generation with proper type annotations.

Adapted from omnibase_3 for omniclaude/omnibase_core compatibility.
"""

import ast
import logging
import re
from typing import Any, Dict, List, Optional


logger = logging.getLogger(__name__)


class ASTBuilder:
    """
    Utility for building Python AST nodes from schemas.

    Handles:
    - Pydantic model class generation with proper typing
    - Field definitions with type annotations
    - Field() calls with constraints (min/max, length, pattern)
    - Enum class generation (delegated to EnumGenerator)
    - Type annotation AST nodes
    - Import statement generation
    - Complete module generation
    """

    def __init__(self, type_mapper=None, reference_resolver=None):
        """
        Initialize the AST builder.

        Args:
            type_mapper: Type mapper utility for type string generation
            reference_resolver: Reference resolver for handling $refs
        """
        self.type_mapper = type_mapper
        self.reference_resolver = reference_resolver
        self.logger = logger

    def generate_model_class(
        self, class_name: str, schema: Dict[str, Any], base_class: str = "BaseModel"
    ) -> ast.ClassDef:
        """
        Generate a Pydantic model class from a schema definition.

        Args:
            class_name: Name of the generated class (should start with "Model")
            schema: Schema definition dictionary
            base_class: Base class name (default: "BaseModel")

        Returns:
            AST ClassDef node for the model

        Raises:
            ValueError: If schema is invalid
        """
        if not isinstance(schema, dict):
            raise ValueError(f"Expected dict schema, got {type(schema)}")

        logger.debug(
            f"Generating model class: {class_name}",
            extra={
                "class_name": class_name,
                "schema_type": schema.get("type", "UNKNOWN"),
                "has_properties": "properties" in schema,
                "has_enum": "enum" in schema,
            },
        )

        # Create base class reference
        bases = [ast.Name(id=base_class, ctx=ast.Load())]

        # Create class body
        body = []

        # Add docstring
        description = schema.get(
            "description", f"{class_name} from contract definition."
        )
        docstring_node = ast.Expr(value=ast.Constant(value=description))
        body.append(docstring_node)

        # Generate fields from properties
        if "properties" in schema:
            required_fields = schema.get("required", [])
            for field_name, field_schema in schema["properties"].items():
                is_required = field_name in required_fields
                field_def = self.create_field_definition(
                    field_name, field_schema, is_required
                )
                if field_def:
                    body.append(field_def)

        # If no fields were added, add a pass statement
        if len(body) == 1:  # Only docstring
            logger.debug(
                f"Adding pass statement to empty model class: {class_name}",
                extra={
                    "class_name": class_name,
                    "base_class": base_class,
                    "reason": "No properties found in schema",
                },
            )
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

        return class_def

    def create_field_definition(
        self, field_name: str, field_schema: Dict[str, Any], is_required: bool = True
    ) -> Optional[ast.AnnAssign]:
        """
        Create a field definition from schema.

        Args:
            field_name: Name of the field
            field_schema: Schema for the field
            is_required: Whether the field is required

        Returns:
            AST AnnAssign node for the field definition
        """
        if not isinstance(field_schema, dict):
            logger.warning(
                f"Invalid field schema for {field_name}, skipping",
                extra={
                    "field_name": field_name,
                    "schema_type": type(field_schema).__name__,
                },
            )
            return None

        # Get type annotation
        type_annotation = self.get_type_annotation(field_schema)

        # Ensure type_annotation is an AST node
        if not isinstance(type_annotation, ast.expr):
            logger.error(
                f"Type annotation is not an AST expr: {type(type_annotation)} for field {field_name}",
                extra={"field_name": field_name, "type": str(type(type_annotation))},
            )
            # Fallback to Any
            type_annotation = ast.Name(id="Any", ctx=ast.Load())

        # Wrap in Optional if not required
        if not is_required:
            type_annotation = ast.Subscript(
                value=ast.Name(id="Optional", ctx=ast.Load()),
                slice=type_annotation,
                ctx=ast.Load(),
            )

        # Create Field() call
        field_call = self.create_field_call(field_schema, is_required)

        # Create the assignment
        target = ast.Name(id=field_name, ctx=ast.Store())

        return ast.AnnAssign(
            target=target, annotation=type_annotation, value=field_call, simple=1
        )

    def get_type_annotation(self, schema: Dict[str, Any]) -> ast.expr:
        """
        Get proper type annotation AST node from schema.

        Args:
            schema: Schema to generate type annotation for

        Returns:
            AST expression node for the type annotation
        """
        if not isinstance(schema, dict):
            return ast.Name(id="Any", ctx=ast.Load())

        # Handle $ref references
        if "$ref" in schema:
            if self.reference_resolver:
                ref_name = self.reference_resolver.resolve_ref(schema["$ref"])
            else:
                # Fallback resolution
                ref_name = schema["$ref"].split("/")[-1]
                if not ref_name.startswith("Model"):
                    ref_name = f"Model{ref_name}"
            return ast.Name(id=ref_name, ctx=ast.Load())

        schema_type = schema.get("type", "string")

        # Handle enums
        if schema_type == "string" and "enum" in schema:
            if self.type_mapper:
                enum_name = self.type_mapper.generate_enum_name_from_values(
                    schema["enum"]
                )
            else:
                # Fallback enum name generation
                first_value = schema["enum"][0] if schema["enum"] else "Generic"
                clean_value = first_value.replace("-", "_")
                if "_" in clean_value:
                    parts = clean_value.split("_")
                    enum_name = "Enum" + "".join(word.capitalize() for word in parts)
                else:
                    enum_name = f"Enum{clean_value.capitalize()}"
            return ast.Name(id=enum_name, ctx=ast.Load())

        # Handle array type
        if schema_type == "array":
            if self.type_mapper:
                array_type_str = self.type_mapper.get_array_type_string(schema)
            else:
                # Fallback array type
                array_type_str = "List[Any]"

            # For List[X], we need to create a subscript AST node
            if array_type_str.startswith("List["):
                # Extract the inner type
                inner_type = array_type_str[5:-1]  # Remove "List[" and "]"
                return ast.Subscript(
                    value=ast.Name(id="List", ctx=ast.Load()),
                    slice=ast.Name(id=inner_type, ctx=ast.Load()),
                    ctx=ast.Load(),
                )
            return ast.Name(id=array_type_str, ctx=ast.Load())

        # Handle object type
        if schema_type == "object":
            if self.type_mapper:
                object_type_str = self.type_mapper.get_object_type_string(schema)
            else:
                # Default to Dict[str, Any]
                object_type_str = "Dict[str, Any]"

            # For Dict types, parse the type string properly
            if object_type_str.startswith("Dict["):
                match = re.match(r"Dict\[([^,]+),\s*([^\]]+)\]", object_type_str)
                if match:
                    key_type = match.group(1).strip()
                    value_type = match.group(2).strip()
                    return ast.Subscript(
                        value=ast.Name(id="Dict", ctx=ast.Load()),
                        slice=ast.Tuple(
                            elts=[
                                ast.Name(id=key_type, ctx=ast.Load()),
                                ast.Name(id=value_type, ctx=ast.Load()),
                            ],
                            ctx=ast.Load(),
                        ),
                        ctx=ast.Load(),
                    )
            return ast.Name(id=object_type_str, ctx=ast.Load())

        # Handle string with format using type mapper if available
        if schema_type == "string" and "format" in schema:
            if self.type_mapper:
                try:
                    type_str = self.type_mapper.get_type_string_from_schema(schema)
                    if type_str != "str":  # Type mapper found a special format
                        return ast.Name(id=type_str, ctx=ast.Load())
                except Exception as e:
                    logger.warning(
                        f"Type mapper failed for schema with format: {e}",
                        extra={"format": schema.get("format"), "error": str(e)},
                    )

        # Handle basic types
        type_mapping = {
            "string": "str",
            "integer": "int",
            "number": "float",
            "boolean": "bool",
            "null": "None",
        }

        mapped_type = type_mapping.get(schema_type, "Any")
        return ast.Name(id=mapped_type, ctx=ast.Load())

    def create_field_call(self, schema: Dict[str, Any], is_required: bool) -> ast.Call:
        """
        Create Field() call for Pydantic field.

        Args:
            schema: Schema for the field
            is_required: Whether the field is required

        Returns:
            AST Call node for Field() with appropriate arguments
        """
        args = []
        keywords = []

        # Handle required/optional fields
        if is_required:
            # Required field - use ... as first argument
            args.append(ast.Constant(value=...))
        else:
            # Optional field - use None as default
            keywords.append(ast.keyword(arg="default", value=ast.Constant(value=None)))

        # Add description if available
        if "description" in schema:
            keywords.append(
                ast.keyword(
                    arg="description", value=ast.Constant(value=schema["description"])
                )
            )

        # Add numeric constraints
        if "minimum" in schema:
            keywords.append(
                ast.keyword(arg="ge", value=ast.Constant(value=schema["minimum"]))
            )
        if "maximum" in schema:
            keywords.append(
                ast.keyword(arg="le", value=ast.Constant(value=schema["maximum"]))
            )

        # Add string constraints
        if "minLength" in schema:
            keywords.append(
                ast.keyword(
                    arg="min_length", value=ast.Constant(value=schema["minLength"])
                )
            )
        if "maxLength" in schema:
            keywords.append(
                ast.keyword(
                    arg="max_length", value=ast.Constant(value=schema["maxLength"])
                )
            )

        # Add pattern constraint
        if "pattern" in schema:
            keywords.append(
                ast.keyword(arg="pattern", value=ast.Constant(value=schema["pattern"]))
            )

        return ast.Call(
            func=ast.Name(id="Field", ctx=ast.Load()), args=args, keywords=keywords
        )

    def generate_import_statement(
        self, module: str, names: List[str]
    ) -> ast.ImportFrom:
        """
        Generate an import statement.

        Args:
            module: Module name to import from
            names: List of names to import

        Returns:
            AST ImportFrom node
        """
        aliases = [ast.alias(name=name, asname=None) for name in names]
        import_stmt = ast.ImportFrom(module=module, names=aliases, level=0)
        ast.fix_missing_locations(import_stmt)
        return import_stmt

    def generate_module_with_imports(
        self, classes: List[ast.ClassDef], imports: Dict[str, List[str]]
    ) -> ast.Module:
        """
        Generate a complete module with imports and classes.

        Args:
            classes: List of class definitions
            imports: Dict mapping module names to import lists

        Returns:
            AST Module node with imports and classes
        """
        body = []

        # Add imports
        for module, names in sorted(imports.items()):
            import_stmt = self.generate_import_statement(module, names)
            body.append(import_stmt)

        # Add classes
        body.extend(classes)

        module_node = ast.Module(body=body, type_ignores=[])
        ast.fix_missing_locations(module_node)

        return module_node

    def unparse_node(self, node: ast.AST) -> str:
        """
        Convert an AST node back to source code.

        Args:
            node: AST node to unparse

        Returns:
            Source code string
        """
        try:
            # Fix missing locations before unparsing
            ast.fix_missing_locations(node)
            return ast.unparse(node)
        except Exception as e:
            logger.error(
                f"Failed to unparse AST node: {e}",
                extra={"node_type": type(node).__name__, "error": str(e)},
            )
            return f"# Failed to generate code: {e}"
