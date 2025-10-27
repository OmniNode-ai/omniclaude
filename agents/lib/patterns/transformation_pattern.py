#!/usr/bin/env python3
"""
Transformation Pattern for Phase 5 Code Generation

Generates data transformation operations with format conversion, validation,
type conversion, and streaming support for large datasets.
Typical for COMPUTE nodes.
"""

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class TransformationPattern:
    """
    Data transformation pattern generator.

    Generates transformation method implementations with:
    - Format conversion (CSV→JSON, XML→Dict, etc.)
    - Input validation and type conversion
    - Streaming support for large datasets
    - Pure function patterns (no side effects)
    - Error handling with OnexError
    - Proper async/await patterns
    """

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def matches(self, capability: Dict[str, Any]) -> float:
        """
        Check if capability matches Transformation pattern.

        Args:
            capability: Capability dictionary from contract

        Returns:
            Confidence score (0.0 to 1.0)
        """
        transform_keywords = {
            "transform",
            "convert",
            "parse",
            "format",
            "map",
            "filter",
            "normalize",
            "sanitize",
            "validate",
            "encode",
        }

        text = (
            f"{capability.get('name', '')} {capability.get('description', '')}".lower()
        )
        matched = sum(1 for kw in transform_keywords if kw in text)

        return min(matched / 2.5, 1.0)  # 2-3 matches = 100% confidence

    def generate(self, capability: Dict[str, Any], context: Dict[str, Any]) -> str:
        """
        Generate transformation method implementation.

        Args:
            capability: Capability dictionary from contract
            context: Additional generation context

        Returns:
            Generated Python code
        """
        method_name = self._sanitize_method_name(capability.get("name", "transform"))
        description = capability.get("description", "Transform input data")

        # Detect transformation type
        transform_type = self._detect_transformation_type(capability, context)

        if transform_type == "format_conversion":
            return self._generate_format_conversion(method_name, description, context)
        elif transform_type == "data_mapping":
            return self._generate_data_mapping(method_name, description, context)
        elif transform_type == "validation":
            return self._generate_validation_transform(
                method_name, description, context
            )
        elif transform_type == "streaming":
            return self._generate_streaming_transform(method_name, description, context)
        else:
            return self._generate_generic_transform(method_name, description, context)

    def get_required_imports(self) -> List[str]:
        """Get required imports for Transformation pattern"""
        return [
            "from typing import Dict, Any, Optional, List, AsyncIterator",
            "import json",
            "import logging",
            "from omnibase_core.errors import OnexError, EnumCoreErrorCode",
        ]

    def get_required_mixins(self) -> List[str]:
        """Get required mixins for Transformation pattern"""
        return [
            "MixinValidation",  # Input/output validation
            "MixinCaching",  # Cache transformation results (optional)
        ]

    def _generate_format_conversion(
        self, method_name: str, description: str, context: Dict[str, Any]
    ) -> str:
        """Generate format conversion method"""
        return f'''
    async def {method_name}(
        self,
        input_data: Any,
        source_format: str = "json",
        target_format: str = "dict"
    ) -> Any:
        """
        {description}

        Converts data from one format to another.

        Args:
            input_data: Input data to transform
            source_format: Source format (json, csv, xml, etc.)
            target_format: Target format (dict, json, csv, etc.)

        Returns:
            Transformed data in target format

        Raises:
            OnexError: If transformation fails
        """
        try:
            self.logger.info(f"Transforming {{source_format}} to {{target_format}}")

            # Validate input
            if input_data is None:
                raise OnexError(
                    code=EnumCoreErrorCode.VALIDATION_ERROR,
                    message="Input data cannot be None",
                    details={{"method": "{method_name}"}}
                )

            # Parse source format
            parsed_data = await self._parse_source_format(input_data, source_format)

            # Convert to target format
            result = await self._convert_to_target_format(parsed_data, target_format)

            self.logger.info(f"Transformation completed: {{len(str(result))}} bytes")

            return result

        except OnexError:
            raise
        except Exception as e:
            self.logger.error(f"Transformation failed: {{str(e)}}")
            raise OnexError(
                code=EnumCoreErrorCode.OPERATION_FAILED,
                message=f"Format conversion failed: {{str(e)}}",
                original_exception=e,
                details={{
                    "source_format": source_format,
                    "target_format": target_format
                }}
            )

    async def _parse_source_format(self, data: Any, format_type: str) -> Dict[str, Any]:
        """Parse data from source format"""
        if format_type == "json":
            if isinstance(data, str):
                return json.loads(data)
            return data
        elif format_type == "dict":
            return dict(data) if not isinstance(data, dict) else data
        elif format_type == "csv":
            import csv
            from io import StringIO
            if isinstance(data, str):
                reader = csv.DictReader(StringIO(data))
                return {{"rows": list(reader)}}
            return data
        else:
            return data

    async def _convert_to_target_format(self, data: Dict[str, Any], format_type: str) -> Any:
        """Convert data to target format"""
        if format_type == "json":
            return json.dumps(data, indent=2)
        elif format_type == "dict":
            return data
        elif format_type == "csv":
            import csv
            from io import StringIO
            output = StringIO()
            if "rows" in data and data["rows"]:
                rows = data["rows"]
                writer = csv.DictWriter(output, fieldnames=rows[0].keys())
                writer.writeheader()
                writer.writerows(rows)
            return output.getvalue()
        else:
            return json.dumps(data, indent=2)
'''

    def _generate_data_mapping(
        self, method_name: str, description: str, context: Dict[str, Any]
    ) -> str:
        """Generate data mapping method"""
        return f'''
    async def {method_name}(
        self,
        input_data: Dict[str, Any],
        mapping_rules: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        {description}

        Maps input data fields to output fields based on mapping rules.

        Args:
            input_data: Input data dictionary
            mapping_rules: Optional field mapping rules (source_field -> target_field)

        Returns:
            Mapped data dictionary

        Raises:
            OnexError: If mapping fails
        """
        try:
            self.logger.info(f"Mapping data with {{len(input_data)}} fields")

            # Use default mapping if not provided
            if not mapping_rules:
                mapping_rules = self._get_default_mapping_rules()

            # Apply mappings
            result = {{}}
            for source_field, target_field in mapping_rules.items():
                if source_field in input_data:
                    value = input_data[source_field]

                    # Apply value transformation if needed
                    transformed_value = await self._transform_value(value, source_field)

                    result[target_field] = transformed_value
                else:
                    self.logger.warning(f"Source field not found: {{source_field}}")

            # Copy unmapped fields if configured
            if context.get("copy_unmapped", False):
                for key, value in input_data.items():
                    if key not in mapping_rules and key not in result:
                        result[key] = value

            self.logger.info(f"Mapping completed: {{len(result)}} output fields")

            return result

        except Exception as e:
            self.logger.error(f"Data mapping failed: {{str(e)}}")
            raise OnexError(
                code=EnumCoreErrorCode.OPERATION_FAILED,
                message=f"Data mapping failed: {{str(e)}}",
                original_exception=e
            )

    def _get_default_mapping_rules(self) -> Dict[str, str]:
        """
        Get default field mapping rules.

        Provides intelligent default mappings for common field name variations.
        Maps common variations (camelCase, snake_case, etc.) to standard names.

        Returns:
            Dictionary of source_field -> target_field mappings
        """
        # Common field name mappings (source -> target)
        return {{
            # ID fields
            "id": "id",
            "ID": "id",
            "_id": "id",
            "uuid": "id",

            # Name fields
            "name": "name",
            "Name": "name",
            "full_name": "name",
            "fullName": "name",

            # Description fields
            "description": "description",
            "desc": "description",
            "Description": "description",

            # Timestamp fields
            "created_at": "created_at",
            "createdAt": "created_at",
            "created": "created_at",
            "timestamp": "created_at",

            "updated_at": "updated_at",
            "updatedAt": "updated_at",
            "modified": "updated_at",

            # Status fields
            "status": "status",
            "state": "status",
            "Status": "status",

            # User fields
            "user_id": "user_id",
            "userId": "user_id",
            "owner_id": "user_id",
            "ownerId": "user_id",
        }}

    async def _transform_value(self, value: Any, field_name: str) -> Any:
        """
        Transform individual field value.

        Applies intelligent type conversions and formatting based on field name
        and value characteristics.

        Args:
            value: The value to transform
            field_name: Name of the field (used for context-aware transformations)

        Returns:
            Transformed value
        """
        if value is None:
            return None

        # Timestamp field transformations
        if any(ts in field_name.lower() for ts in ["timestamp", "created_at", "updated_at", "time", "date"]):
            from datetime import datetime
            if isinstance(value, str):
                try:
                    # Try parsing ISO format
                    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
                    return dt.isoformat()
                except (ValueError, AttributeError):
                    pass
            elif isinstance(value, (int, float)):
                try:
                    # Assume Unix timestamp
                    dt = datetime.fromtimestamp(value)
                    return dt.isoformat()
                except (ValueError, OSError):
                    pass

        # ID field transformations
        if "id" in field_name.lower() or "uuid" in field_name.lower():
            # Convert to string for consistency
            return str(value)

        # Boolean field transformations
        if "is_" in field_name.lower() or "has_" in field_name.lower() or "enabled" in field_name.lower():
            if isinstance(value, str):
                return value.lower() in ("true", "yes", "1", "on", "enabled")
            return bool(value)

        # Numeric field transformations
        if any(num in field_name.lower() for num in ["count", "total", "amount", "quantity", "price"]):
            try:
                if "." in str(value) or "price" in field_name.lower() or "amount" in field_name.lower():
                    return float(value)
                return int(value)
            except (ValueError, TypeError):
                pass

        # String trimming and normalization
        if isinstance(value, str):
            # Trim whitespace
            value = value.strip()

            # Normalize empty strings to None if configured
            if value == "":
                return None

        return value
'''

    def _generate_validation_transform(
        self, method_name: str, description: str, context: Dict[str, Any]
    ) -> str:
        """Generate validation transformation method"""
        return f'''
    async def {method_name}(
        self,
        input_data: Dict[str, Any],
        validation_rules: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        {description}

        Validates and transforms input data according to validation rules.

        Args:
            input_data: Input data to validate and transform
            validation_rules: Optional validation rules

        Returns:
            Validated and transformed data

        Raises:
            OnexError: If validation fails
        """
        try:
            self.logger.info(f"Validating and transforming data: {{len(input_data)}} fields")

            validation_errors = []

            # Use default rules if not provided
            if not validation_rules:
                validation_rules = self._get_default_validation_rules()

            # Apply validation and transformation
            result = {{}}
            for field, rules in validation_rules.items():
                value = input_data.get(field)

                # Check required fields
                if rules.get("required", False) and value is None:
                    validation_errors.append(f"Required field missing: {{field}}")
                    continue

                # Type conversion
                expected_type = rules.get("type")
                if expected_type and value is not None:
                    try:
                        value = self._convert_type(value, expected_type)
                    except (ValueError, TypeError) as e:
                        validation_errors.append(
                            f"Type conversion failed for {{field}}: {{str(e)}}"
                        )
                        continue

                # Range validation
                if "min" in rules and value is not None and value < rules["min"]:
                    validation_errors.append(f"{{field}} below minimum: {{value}} < {{rules['min']}}")

                if "max" in rules and value is not None and value > rules["max"]:
                    validation_errors.append(f"{{field}} above maximum: {{value}} > {{rules['max']}}")

                result[field] = value

            # Raise error if validation failed
            if validation_errors:
                raise OnexError(
                    code=EnumCoreErrorCode.VALIDATION_ERROR,
                    message=f"Validation failed: {{len(validation_errors)}} errors",
                    details={{"errors": validation_errors}}
                )

            self.logger.info(f"Validation completed: {{len(result)}} fields validated")

            return result

        except OnexError:
            raise
        except Exception as e:
            self.logger.error(f"Validation transform failed: {{str(e)}}")
            raise OnexError(
                code=EnumCoreErrorCode.OPERATION_FAILED,
                message=f"Validation transform failed: {{str(e)}}",
                original_exception=e
            )

    def _get_default_validation_rules(self) -> Dict[str, Any]:
        """
        Get default validation rules.

        Provides common validation rules for standard field types.
        Rules include type checking, required fields, and value constraints.

        Returns:
            Dictionary of field_name -> validation_rules
        """
        return {{
            # ID fields - required, string type
            "id": {{
                "required": False,
                "type": "str"
            }},

            # Name fields - required, string, length constraints
            "name": {{
                "required": True,
                "type": "str",
                "min": 1,
                "max": 255
            }},

            # Description fields - optional, string
            "description": {{
                "required": False,
                "type": "str",
                "max": 2000
            }},

            # Email fields - optional, string, format validation
            "email": {{
                "required": False,
                "type": "str"
            }},

            # Status fields - optional, string
            "status": {{
                "required": False,
                "type": "str"
            }},

            # Count/numeric fields - optional, int, non-negative
            "count": {{
                "required": False,
                "type": "int",
                "min": 0
            }},

            # Timestamp fields - optional, string
            "created_at": {{
                "required": False,
                "type": "str"
            }},
            "updated_at": {{
                "required": False,
                "type": "str"
            }},
        }}

    def _convert_type(self, value: Any, expected_type: str) -> Any:
        """Convert value to expected type"""
        type_map = {{
            "int": int,
            "float": float,
            "str": str,
            "bool": bool,
            "list": list,
            "dict": dict,
        }}

        converter = type_map.get(expected_type)
        if converter:
            return converter(value)

        return value
'''

    def _generate_streaming_transform(
        self, method_name: str, description: str, context: Dict[str, Any]
    ) -> str:
        """Generate streaming transformation method"""
        return f'''
    async def {method_name}(
        self,
        input_stream: AsyncIterator[Any],
        batch_size: int = 100
    ) -> AsyncIterator[Any]:
        """
        {description}

        Transforms data in streaming fashion for large datasets.

        Args:
            input_stream: Async iterator of input data
            batch_size: Number of items to process in each batch

        Yields:
            Transformed data items

        Raises:
            OnexError: If transformation fails
        """
        try:
            self.logger.info(f"Starting streaming transformation (batch_size={{batch_size}})")

            batch = []
            item_count = 0

            async for item in input_stream:
                try:
                    # Transform individual item
                    transformed = await self._transform_item(item)
                    batch.append(transformed)

                    # Yield batch when size reached
                    if len(batch) >= batch_size:
                        for result in batch:
                            yield result
                        item_count += len(batch)
                        batch = []

                except Exception as e:
                    self.logger.warning(f"Failed to transform item: {{str(e)}}")
                    # Continue with next item

            # Yield remaining items
            if batch:
                for result in batch:
                    yield result
                item_count += len(batch)

            self.logger.info(f"Streaming transformation completed: {{item_count}} items")

        except Exception as e:
            self.logger.error(f"Streaming transformation failed: {{str(e)}}")
            raise OnexError(
                code=EnumCoreErrorCode.OPERATION_FAILED,
                message=f"Streaming transformation failed: {{str(e)}}",
                original_exception=e
            )

    async def _transform_item(self, item: Any) -> Any:
        """
        Transform individual stream item.

        Applies transformations appropriate for the item type.
        Handles dictionaries, lists, primitives, and objects.

        Args:
            item: Single item from stream to transform

        Returns:
            Transformed item
        """
        # Dictionary transformation - apply field-level transforms
        if isinstance(item, dict):
            result = {{}}
            for key, value in item.items():
                # Apply value transformation with field context
                transformed_value = await self._transform_value(value, key)
                result[key] = transformed_value
            return result

        # List transformation - recursively transform elements
        elif isinstance(item, list):
            return [await self._transform_item(element) for element in item]

        # Primitive types - apply basic transformations
        elif isinstance(item, str):
            # String normalization
            return item.strip()

        elif isinstance(item, (int, float, bool, type(None))):
            # Pass through unchanged
            return item

        # Object transformation - convert to dict if possible
        else:
            if hasattr(item, "__dict__"):
                # Convert object to dict and transform
                item_dict = {{k: v for k, v in item.__dict__.items() if not k.startswith("_")}}
                return await self._transform_item(item_dict)

            # Unknown type - pass through
            return item
'''

    def _generate_generic_transform(
        self, method_name: str, description: str, context: Dict[str, Any]
    ) -> str:
        """Generate generic transformation method"""
        return f'''
    async def {method_name}(self, input_data: Any) -> Any:
        """
        {description}

        Transforms input data to output format.

        Args:
            input_data: Input data to transform

        Returns:
            Transformed output data

        Raises:
            OnexError: If transformation fails
        """
        try:
            self.logger.info(f"Executing transformation: {{type(input_data).__name__}}")

            # Apply appropriate transformation based on input type
            if isinstance(input_data, dict):
                # Dictionary transformation - apply field mappings and value transforms
                result = await self._transform_item(input_data)

            elif isinstance(input_data, list):
                # List transformation - transform each item
                result = [await self._transform_item(item) for item in input_data]

            elif isinstance(input_data, str):
                # String transformation - attempt to parse if JSON
                try:
                    import json
                    parsed = json.loads(input_data)
                    result = await self._transform_item(parsed)
                except (json.JSONDecodeError, ValueError):
                    # Not JSON, return normalized string
                    result = input_data.strip()

            else:
                # Other types - pass through with basic normalization
                result = input_data

            self.logger.info(f"Transformation completed: {{type(result).__name__}}")

            return result

        except Exception as e:
            self.logger.error(f"Transformation failed: {{str(e)}}")
            raise OnexError(
                code=EnumCoreErrorCode.OPERATION_FAILED,
                message=f"Transformation failed: {{str(e)}}",
                original_exception=e
            )
'''

    def _sanitize_method_name(self, name: str) -> str:
        """Convert to valid Python method name"""
        import re

        name = re.sub(r"[^\w\s-]", "", name.lower())
        name = re.sub(r"[-\s]+", "_", name)
        return name.strip("_") or "transform_data"

    def _detect_transformation_type(
        self, capability: Dict[str, Any], context: Dict[str, Any]
    ) -> str:
        """Detect specific transformation type"""
        text = (
            f"{capability.get('name', '')} {capability.get('description', '')}".lower()
        )

        if any(kw in text for kw in ["convert", "format", "parse"]):
            return "format_conversion"
        elif any(kw in text for kw in ["map", "mapping", "field"]):
            return "data_mapping"
        elif any(kw in text for kw in ["validate", "validation", "check"]):
            return "validation"
        elif any(kw in text for kw in ["stream", "large", "batch"]):
            return "streaming"
        else:
            return "generic"
