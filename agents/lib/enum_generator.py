#!/usr/bin/env python3
"""
Enum Generator for Phase 4

Generates ONEX-compliant enum classes from PRD analysis.
Includes operation type enums, status enums, and domain-specific enums.
"""

import logging
import re
from dataclasses import dataclass
from typing import List, Optional, Set

# Import from omnibase_core
from omnibase_core.errors import EnumCoreErrorCode, OnexError

from .simple_prd_analyzer import SimplePRDAnalysisResult

logger = logging.getLogger(__name__)


@dataclass
class EnumValue:
    """Represents a single enum value"""

    name: str  # UPPER_SNAKE_CASE
    value: str  # lowercase
    description: Optional[str] = None

    def __hash__(self):
        return hash(self.name)

    def __eq__(self, other):
        if isinstance(other, EnumValue):
            return self.name == other.name
        return False


@dataclass
class GeneratedEnum:
    """Represents a generated enum class"""

    class_name: str
    enum_type: str  # 'operation_type', 'status', 'domain_specific'
    values: List[EnumValue]
    docstring: str
    file_path: str
    source_code: str


class EnumGenerator:
    """Generates ONEX-compliant enum classes from PRD analysis"""

    # Standard operation verbs
    OPERATION_VERBS = {
        "create",
        "read",
        "update",
        "delete",
        "list",
        "search",
        "validate",
        "process",
        "transform",
        "analyze",
        "compute",
        "aggregate",
        "filter",
        "sort",
        "merge",
        "split",
        "join",
        "publish",
        "subscribe",
        "notify",
        "send",
        "receive",
        "start",
        "stop",
        "pause",
        "resume",
        "cancel",
        "retry",
        "upload",
        "download",
        "import",
        "export",
        "sync",
        "authenticate",
        "authorize",
        "encrypt",
        "decrypt",
        "compress",
        "decompress",
        "encode",
        "decode",
        "register",
        "unregister",
        "activate",
        "deactivate",
        "enable",
        "disable",
        "configure",
        "initialize",
        "cleanup",
    }

    # Standard status values
    STANDARD_STATUSES = [
        EnumValue("PENDING", "pending", "Operation is pending"),
        EnumValue("IN_PROGRESS", "in_progress", "Operation is in progress"),
        EnumValue("COMPLETED", "completed", "Operation completed successfully"),
        EnumValue("FAILED", "failed", "Operation failed"),
        EnumValue("CANCELLED", "cancelled", "Operation was cancelled"),
        EnumValue("TIMEOUT", "timeout", "Operation timed out"),
        EnumValue("RETRYING", "retrying", "Operation is being retried"),
    ]

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def generate_operation_type_enum(
        self,
        prd_analysis: SimplePRDAnalysisResult,
        service_name: str,
        additional_operations: Optional[List[str]] = None,
    ) -> GeneratedEnum:
        """
        Generate operation type enum from PRD analysis.

        Args:
            prd_analysis: PRD analysis result
            service_name: Service name (e.g., 'user_management')
            additional_operations: Optional additional operation types

        Returns:
            GeneratedEnum with operation type enum

        Raises:
            OnexError: If generation fails
        """
        try:
            self.logger.info(f"Generating operation type enum for {service_name}")

            # Extract operation values from PRD
            inferred_values = self.infer_enum_values(prd_analysis, "operation")

            # Add additional operations if provided
            if additional_operations:
                for op in additional_operations:
                    inferred_values.add(self._to_enum_value(op, "operation"))

            # Ensure minimum CRUD operations if no operations found
            if not inferred_values:
                inferred_values = {
                    EnumValue("CREATE", "create", "Create a new resource"),
                    EnumValue("READ", "read", "Read an existing resource"),
                    EnumValue("UPDATE", "update", "Update an existing resource"),
                    EnumValue("DELETE", "delete", "Delete an existing resource"),
                }

            # Sort values alphabetically
            sorted_values = sorted(inferred_values, key=lambda x: x.name)

            # Generate class name
            pascal_name = self._to_pascal_case(service_name)
            class_name = f"Enum{pascal_name}OperationType"

            # Generate docstring
            docstring = f"""Operation types for {service_name} service.

    Extracted from PRD functional requirements.
    """

            # Generate file path
            file_path = f"enum_{service_name}_operation_type.py"

            # Generate source code
            source_code = self._generate_enum_source(
                class_name=class_name,
                values=sorted_values,
                docstring=docstring,
                service_name=service_name,
            )

            # Validate generated code
            self.validate_enum_code(source_code, class_name)

            return GeneratedEnum(
                class_name=class_name,
                enum_type="operation_type",
                values=sorted_values,
                docstring=docstring,
                file_path=file_path,
                source_code=source_code,
            )

        except Exception as e:
            self.logger.error(f"Operation type enum generation failed: {str(e)}")
            raise OnexError(
                code=EnumCoreErrorCode.OPERATION_FAILED,
                message=f"Operation type enum generation failed: {str(e)}",
                details={"service_name": service_name},
            )

    def generate_status_enum(
        self,
        service_name: str,
        prd_analysis: Optional[SimplePRDAnalysisResult] = None,
        additional_statuses: Optional[List[str]] = None,
    ) -> GeneratedEnum:
        """
        Generate status enum for service operations.

        Args:
            service_name: Service name (e.g., 'user_management')
            prd_analysis: Optional PRD analysis for custom statuses
            additional_statuses: Optional additional status values

        Returns:
            GeneratedEnum with status enum

        Raises:
            OnexError: If generation fails
        """
        try:
            self.logger.info(f"Generating status enum for {service_name}")

            # Start with standard statuses
            status_values = set(self.STANDARD_STATUSES)

            # Extract domain-specific statuses from PRD if provided
            if prd_analysis:
                inferred_statuses = self.infer_enum_values(prd_analysis, "status")
                status_values.update(inferred_statuses)

            # Add additional statuses if provided
            if additional_statuses:
                for status in additional_statuses:
                    status_values.add(self._to_enum_value(status, "status"))

            # Sort values alphabetically
            sorted_values = sorted(status_values, key=lambda x: x.name)

            # Generate class name
            pascal_name = self._to_pascal_case(service_name)
            class_name = f"Enum{pascal_name}Status"

            # Generate docstring
            docstring = f"Status values for {service_name} operations."

            # Generate file path
            file_path = f"enum_{service_name}_status.py"

            # Generate source code
            source_code = self._generate_enum_source(
                class_name=class_name,
                values=sorted_values,
                docstring=docstring,
                service_name=service_name,
            )

            # Validate generated code
            self.validate_enum_code(source_code, class_name)

            return GeneratedEnum(
                class_name=class_name,
                enum_type="status",
                values=sorted_values,
                docstring=docstring,
                file_path=file_path,
                source_code=source_code,
            )

        except Exception as e:
            self.logger.error(f"Status enum generation failed: {str(e)}")
            raise OnexError(
                code=EnumCoreErrorCode.OPERATION_FAILED,
                message=f"Status enum generation failed: {str(e)}",
                details={"service_name": service_name},
            )

    def infer_enum_values(
        self, prd_analysis: SimplePRDAnalysisResult, enum_type: str = "operation"
    ) -> Set[EnumValue]:
        """
        Extract enum values from PRD functional requirements using NLP.

        Args:
            prd_analysis: PRD analysis result
            enum_type: Type of enum ('operation', 'status', 'domain')

        Returns:
            Set of inferred EnumValue objects
        """
        enum_values = set()

        try:
            # Combine all text sources
            all_text = self._gather_text_from_prd(prd_analysis)

            if enum_type == "operation":
                enum_values = self._extract_operation_values(all_text)
            elif enum_type == "status":
                enum_values = self._extract_status_values(all_text)
            elif enum_type == "domain":
                enum_values = self._extract_domain_values(all_text)

            self.logger.info(f"Inferred {len(enum_values)} {enum_type} enum values")

        except Exception as e:
            self.logger.warning(f"Error inferring enum values: {str(e)}")

        return enum_values

    def validate_enum_code(self, source_code: str, class_name: str) -> bool:
        """
        Ensure ONEX compliance for generated enum code.

        Args:
            source_code: Generated Python source code
            class_name: Name of the enum class

        Returns:
            True if valid

        Raises:
            OnexError: If validation fails
        """
        errors = []

        # Check for required imports
        if "from enum import Enum" not in source_code:
            errors.append("Missing 'from enum import Enum' import")

        # Check for class definition
        if f"class {class_name}(str, Enum):" not in source_code:
            errors.append(f"Missing or incorrect class definition for {class_name}")

        # Check for from_string classmethod
        if (
            "@classmethod" not in source_code
            or "def from_string(cls" not in source_code
        ):
            errors.append("Missing from_string() classmethod")

        # Check for __str__ method
        if "def __str__(self)" not in source_code:
            errors.append("Missing __str__() method")

        # Check for docstring
        if '"""' not in source_code[:200]:  # Check near the top
            errors.append("Missing class docstring")

        if errors:
            raise OnexError(
                code=EnumCoreErrorCode.VALIDATION_ERROR,
                message="Enum code validation failed",
                details={"errors": errors, "class_name": class_name},
            )

        return True

    # Private helper methods

    def _gather_text_from_prd(self, prd_analysis: SimplePRDAnalysisResult) -> str:
        """Gather all text from PRD for analysis"""
        parsed = prd_analysis.parsed_prd

        parts = [
            parsed.title,
            parsed.description,
            " ".join(parsed.functional_requirements),
            " ".join(parsed.features),
            " ".join(parsed.technical_details),
        ]

        return " ".join(parts).lower()

    def _extract_operation_values(self, text: str) -> Set[EnumValue]:
        """Extract operation enum values from text"""
        found_operations = set()

        # Extract exact verb matches
        for verb in self.OPERATION_VERBS:
            # Look for verb as standalone word or with common suffixes
            pattern = r"\b" + verb + r"(s|ing|ed)?\b"
            if re.search(pattern, text):
                found_operations.add(
                    EnumValue(
                        name=verb.upper(),
                        value=verb,
                        description=f"{verb.capitalize()} operation",
                    )
                )

        # Extract CRUD patterns
        crud_patterns = {
            r"\b(add|insert|new)\b": EnumValue("CREATE", "create", "Create operation"),
            r"\b(get|fetch|retrieve|view)\b": EnumValue(
                "READ", "read", "Read operation"
            ),
            r"\b(modify|edit|change)\b": EnumValue(
                "UPDATE", "update", "Update operation"
            ),
            r"\b(remove|drop)\b": EnumValue("DELETE", "delete", "Delete operation"),
        }

        for pattern, enum_value in crud_patterns.items():
            if re.search(pattern, text):
                found_operations.add(enum_value)

        return found_operations

    def _extract_status_values(self, text: str) -> Set[EnumValue]:
        """Extract status enum values from text"""
        found_statuses = set()

        # Status patterns
        status_patterns = {
            r"\b(queued|waiting|scheduled)\b": EnumValue(
                "PENDING", "pending", "Pending status"
            ),
            r"\b(processing|running|executing)\b": EnumValue(
                "IN_PROGRESS", "in_progress", "In progress status"
            ),
            r"\b(done|finished|success|completed)\b": EnumValue(
                "COMPLETED", "completed", "Completed status"
            ),
            r"\b(error|failure|unsuccessful|failed)\b": EnumValue(
                "FAILED", "failed", "Failed status"
            ),
            r"\b(cancelled|aborted|terminated)\b": EnumValue(
                "CANCELLED", "cancelled", "Cancelled status"
            ),
            r"\b(expired|timed.*out)\b": EnumValue(
                "TIMEOUT", "timeout", "Timeout status"
            ),
            r"\b(retry|retrying|reattempt)\b": EnumValue(
                "RETRYING", "retrying", "Retrying status"
            ),
            r"\b(approved|accepted)\b": EnumValue(
                "APPROVED", "approved", "Approved status"
            ),
            r"\b(rejected|denied)\b": EnumValue(
                "REJECTED", "rejected", "Rejected status"
            ),
            r"\b(suspended|paused)\b": EnumValue("PAUSED", "paused", "Paused status"),
            r"\b(active|enabled)\b": EnumValue("ACTIVE", "active", "Active status"),
            r"\b(inactive|disabled)\b": EnumValue(
                "INACTIVE", "inactive", "Inactive status"
            ),
        }

        for pattern, enum_value in status_patterns.items():
            if re.search(pattern, text):
                found_statuses.add(enum_value)

        return found_statuses

    def _extract_domain_values(self, text: str) -> Set[EnumValue]:
        """Extract domain-specific enum values from text"""
        found_values = set()

        # Extract capitalized words that might be domain concepts
        domain_words = re.findall(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b", text)

        # Convert to enum values
        for word in set(domain_words):
            if len(word) > 2:  # Skip very short words
                enum_name = self._to_enum_name(word)
                enum_val = word.lower().replace(" ", "_")
                found_values.add(
                    EnumValue(
                        name=enum_name,
                        value=enum_val,
                        description=f"{word} domain value",
                    )
                )

        return found_values

    def _to_enum_value(self, text: str, context: str = "operation") -> EnumValue:
        """Convert text to EnumValue"""
        enum_name = self._to_enum_name(text)
        enum_val = text.lower().replace(" ", "_").replace("-", "_")

        description = f"{text.capitalize()} {context}"

        return EnumValue(name=enum_name, value=enum_val, description=description)

    def _to_enum_name(self, text: str) -> str:
        """Convert text to UPPER_SNAKE_CASE enum name"""
        # Replace hyphens and spaces with underscores
        text = text.replace("-", "_").replace(" ", "_")

        # Insert underscores before capital letters (for camelCase/PascalCase)
        text = re.sub(r"([a-z])([A-Z])", r"\1_\2", text)

        # Convert to uppercase
        text = text.upper()

        # Clean up multiple underscores
        text = re.sub(r"_+", "_", text)

        # Remove leading/trailing underscores
        text = text.strip("_")

        return text

    def _to_pascal_case(self, text: str) -> str:
        """Convert text to PascalCase"""
        # Insert spaces before capital letters (for camelCase/PascalCase inputs)
        text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
        # Convert to lowercase to normalize
        text = text.lower()
        # Replace separators with spaces and split
        words = text.replace("_", " ").replace("-", " ").split()
        # Capitalize first letter of each word
        return "".join(word.capitalize() for word in words)

    def _generate_enum_source(
        self,
        class_name: str,
        values: List[EnumValue],
        docstring: str,
        service_name: str,
    ) -> str:
        """Generate complete enum source code"""

        # Generate enum value definitions
        enum_defs = []
        for value in values:
            if value.description:
                enum_defs.append(
                    f'    {value.name} = "{value.value}"  # {value.description}'
                )
            else:
                enum_defs.append(f'    {value.name} = "{value.value}"')

        enum_values_str = "\n".join(enum_defs)

        # Generate complete source code
        source = f'''#!/usr/bin/env python3
"""
{class_name} - ONEX Compliant Enum

Generated from PRD analysis for {service_name} service.
"""

from enum import Enum
from typing import Optional


class {class_name}(str, Enum):
    """{docstring}"""

{enum_values_str}

    @classmethod
    def from_string(cls, value: str) -> "{class_name}":
        """
        Convert string to enum value.

        Args:
            value: String value to convert

        Returns:
            Enum instance

        Raises:
            ValueError: If value is not valid
        """
        try:
            return cls(value.lower())
        except ValueError:
            valid_values = [e.value for e in cls]
            raise ValueError(
                f"Invalid {class_name}: {{value}}. "
                f"Valid values: {{', '.join(valid_values)}}"
            )

    def __str__(self) -> str:
        """Return string representation of enum value."""
        return self.value

    @property
    def display_name(self) -> str:
        """Return human-readable display name."""
        return self.value.replace('_', ' ').title()
'''

        return source
