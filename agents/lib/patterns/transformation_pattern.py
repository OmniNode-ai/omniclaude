#!/usr/bin/env python3
"""
Transformation Pattern for Phase 5 Code Generation

Generates data transformation operations with format conversion, validation,
type conversion, and streaming support for large datasets.
Typical for COMPUTE nodes.
"""

import logging
from typing import Dict, Any, List

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
            'transform', 'convert', 'parse', 'format', 'map',
            'filter', 'normalize', 'sanitize', 'validate', 'encode'
        }

        text = f"{capability.get('name', '')} {capability.get('description', '')}".lower()
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
            return self._generate_validation_transform(method_name, description, context)
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
        self,
        method_name: str,
        description: str,
        context: Dict[str, Any]
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
        else:
            # TODO: Implement additional format parsers (CSV, XML, etc.)
            return data

    async def _convert_to_target_format(self, data: Dict[str, Any], format_type: str) -> Any:
        """Convert data to target format"""
        if format_type == "json":
            return json.dumps(data, indent=2)
        elif format_type == "dict":
            return data
        else:
            # TODO: Implement additional format converters
            return data
'''

    def _generate_data_mapping(
        self,
        method_name: str,
        description: str,
        context: Dict[str, Any]
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
        """Get default field mapping rules"""
        # TODO: Implement default mapping based on schema
        return {{}}

    async def _transform_value(self, value: Any, field_name: str) -> Any:
        """Transform individual field value"""
        # TODO: Implement value transformations (type conversion, formatting, etc.)
        return value
'''

    def _generate_validation_transform(
        self,
        method_name: str,
        description: str,
        context: Dict[str, Any]
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
        """Get default validation rules"""
        # TODO: Implement default rules based on schema
        return {{}}

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
        self,
        method_name: str,
        description: str,
        context: Dict[str, Any]
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
        """Transform individual stream item"""
        # TODO: Implement item transformation logic
        return item
'''

    def _generate_generic_transform(
        self,
        method_name: str,
        description: str,
        context: Dict[str, Any]
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

            # TODO: Implement transformation logic based on requirements

            result = input_data  # Placeholder

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
        name = re.sub(r'[^\w\s-]', '', name.lower())
        name = re.sub(r'[-\s]+', '_', name)
        return name.strip('_') or "transform_data"

    def _detect_transformation_type(
        self,
        capability: Dict[str, Any],
        context: Dict[str, Any]
    ) -> str:
        """Detect specific transformation type"""
        text = f"{capability.get('name', '')} {capability.get('description', '')}".lower()

        if any(kw in text for kw in ['convert', 'format', 'parse']):
            return "format_conversion"
        elif any(kw in text for kw in ['map', 'mapping', 'field']):
            return "data_mapping"
        elif any(kw in text for kw in ['validate', 'validation', 'check']):
            return "validation"
        elif any(kw in text for kw in ['stream', 'large', 'batch']):
            return "streaming"
        else:
            return "generic"
