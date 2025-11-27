"""
Reference Resolver Utility for ONEX Contract Generation.

Handles resolution of JSON Schema $ref references to Python type names.
Provides consistent reference resolution across all ONEX tools.

Adapted from omnibase_3 for omniclaude/omnibase_core compatibility.
"""

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


logger = logging.getLogger(__name__)


@dataclass
class RefInfo:
    """Structured data for reference resolution."""

    file_path: str
    type_name: str
    is_internal: bool = False
    is_subcontract: bool = False


class ReferenceResolver:
    """
    Utility for resolving JSON Schema $ref references.

    Handles:
    - Internal references (#/definitions/...)
    - External references (file.yaml#/...)
    - Subcontract references (contracts/...)
    - Tool-specific prefix cleanup
    - Circular reference detection
    """

    # Known type mappings for clean resolution
    TYPE_MAPPINGS = {
        "ProcessingConfig": "ModelProcessingConfig",
        "ValidationConfig": "ModelValidationConfig",
        "ProcessingResult": "ModelProcessingResult",
        "ValidationResult": "ModelValidationResult",
        "NodeStatus": "ModelNodeStatus",
        "SemVerModel": "ModelSemVer",
        "OnexFieldModel": "ModelOnexFieldModel",
        "ActionSpec": "ModelActionSpec",
        "LogContext": "ModelLogContext",
        "ErrorInfo": "ModelErrorInfo",
        "SuccessInfo": "ModelSuccessInfo",
    }

    # Pattern for tool-specific prefixes to clean up
    TOOL_PREFIX_PATTERN = re.compile(
        r"^Tool[A-Z][a-zA-Z]*"
        r"(?:Generator|Parser|Manager|Processor|Validator|Analyzer|"
        r"Injector|Resolver|Builder|Runner|Tracker|Engine)?"
        r"(ProcessingConfig|ValidationConfig|ProcessingResult|"
        r"ValidationResult|NodeStatus|ActionSpec|LogContext)$"
    )

    def __init__(self):
        """Initialize the reference resolver."""
        self.logger = logger
        self.resolved_cache: Dict[str, str] = {}  # Cache for performance

    def resolve_ref(self, ref: str) -> str:
        """
        Main entry point to resolve a $ref to a type name.

        Args:
            ref: Reference string (e.g., "#/definitions/User", "contracts/models.yaml#/Config")

        Returns:
            Resolved type name (e.g., "ModelUser", "ModelConfig")
        """
        # Check cache first
        if ref in self.resolved_cache:
            return self.resolved_cache[ref]

        ref_info = self.parse_reference(ref)
        resolved = self.resolve_type_name(ref_info)

        # Cache result
        self.resolved_cache[ref] = resolved

        logger.debug(
            f"Resolved reference: {ref} -> {resolved}",
            extra={
                "ref": ref,
                "resolved": resolved,
                "is_internal": ref_info.is_internal,
            },
        )

        return resolved

    def parse_reference(self, ref: str) -> RefInfo:
        """
        Parse a reference string into structured data.

        Args:
            ref: Reference string

        Returns:
            Structured reference information
        """
        if ref.startswith("#/definitions/"):
            # Internal reference
            type_name = ref.split("/")[-1]
            return RefInfo(file_path="", type_name=type_name, is_internal=True)

        if "#/" in ref:
            # External reference
            file_part, type_part = ref.split("#/", 1)
            # Remove any leading slashes from type_part
            type_name = type_part.split("/")[-1] if "/" in type_part else type_part

            return RefInfo(
                file_path=file_part,
                type_name=type_name,
                is_subcontract=file_part.startswith("contracts/"),
            )

        # Fallback for malformed refs
        logger.warning(f"Malformed reference: {ref}", extra={"ref": ref})
        return RefInfo(file_path="", type_name=ref)

    def resolve_type_name(self, ref_info: RefInfo) -> str:
        """
        Resolve reference info to proper model name.

        Args:
            ref_info: Parsed reference information

        Returns:
            Resolved Python type name
        """
        # Handle empty type names
        if not ref_info.type_name or ref_info.type_name.strip() == "":
            return "Dict[str, Any]"  # Fallback for empty refs

        # Internal references
        if ref_info.is_internal:
            return self._ensure_model_prefix(ref_info.type_name)

        # Subcontract references
        if ref_info.is_subcontract:
            clean_name = self._clean_tool_prefix(ref_info.type_name)
            return self._ensure_model_prefix(clean_name)

        # External schema references based on file path
        if ref_info.file_path:
            resolved = self._resolve_by_file_path(ref_info)
            if resolved:
                return resolved

        # Default resolution
        return self._ensure_model_prefix(ref_info.type_name)

    def is_external_reference(self, ref: str) -> bool:
        """
        Check if a reference is external (not internal to current schema).

        Args:
            ref: Reference string

        Returns:
            True if external reference
        """
        if not ref:
            return False
        return not ref.startswith("#/definitions/")

    def resolve_references(
        self, schema: Dict[str, Any], path: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Recursively resolve all $ref references in a schema.

        Args:
            schema: Schema dictionary with potential $ref fields
            path: Current resolution path (for circular detection)

        Returns:
            Schema with all $ref references resolved

        Raises:
            ValueError: If circular reference detected
        """
        if path is None:
            path = []

        # Note: The recursive calls below (lines 220-228) are guarded by isinstance(value, dict)
        # checks, so this method always receives a dict. No defensive check needed.

        # Check for $ref
        if "$ref" in schema:
            ref = schema["$ref"]

            # Check for circular reference
            if ref in path:
                raise ValueError(
                    f"Circular reference detected: {' -> '.join(path + [ref])}"
                )

            # For now, just replace $ref with the resolved type name
            # Full resolution would require loading the referenced schema
            resolved_type = self.resolve_ref(ref)
            return {"type": "object", "__resolved_ref": resolved_type}

        # Recursively resolve all dict values
        result: Dict[str, Any] = {}
        for key, value in schema.items():
            if isinstance(value, dict):
                result[key] = self.resolve_references(value, path)
            elif isinstance(value, list):
                resolved_list: List[Any] = [
                    (
                        self.resolve_references(item, path)
                        if isinstance(item, dict)
                        else item
                    )
                    for item in value
                ]
                result[key] = resolved_list
            else:
                result[key] = value

        return result

    def get_package_name_for_subcontract(self, subcontract_path: str) -> str:
        """
        Get the package name for a subcontract.

        Args:
            subcontract_path: Path to subcontract file

        Returns:
            Package name for imports
        """
        # Default: derive from file path
        # contracts/contract_models.yaml -> models
        if subcontract_path.startswith("contracts/contract_"):
            name = subcontract_path.replace("contracts/contract_", "").replace(
                ".yaml", ""
            )
            return name

        # Fallback to stem
        return Path(subcontract_path).stem

    def get_import_path_for_subcontract(self, subcontract_path: str) -> str:
        """
        Get the Python import path for a subcontract.

        Args:
            subcontract_path: Path to subcontract file

        Returns:
            Python import path
        """
        package_name = self.get_package_name_for_subcontract(subcontract_path)
        return f"generated.{package_name}"

    # Private helper methods

    def _clean_tool_prefix(self, type_name: str) -> str:
        """Remove tool-specific prefixes from type names."""
        # Check for known pattern
        match = self.TOOL_PREFIX_PATTERN.match(type_name)
        if match:
            config_type = match.group(1)
            return self.TYPE_MAPPINGS.get(config_type, config_type)

        # Check simple prefixes
        for prefix in ["Tool", "Node"]:
            if type_name.startswith(prefix):
                clean_name = type_name[len(prefix) :]
                return self.TYPE_MAPPINGS.get(clean_name, clean_name)

        return type_name

    def _ensure_model_prefix(self, name: str) -> str:
        """Ensure type name has Model prefix per ONEX convention."""
        if not name:
            return "Dict[str, Any]"

        # Check if already has Model prefix
        if name.startswith("Model"):
            return name

        # Check if it's an enum (Enum prefix is also valid)
        if name.startswith("Enum"):
            return name

        # Add Model prefix
        return f"Model{name}"

    def _resolve_by_file_path(self, ref_info: RefInfo) -> Optional[str]:
        """Try to resolve type by examining file path."""
        path_lower = ref_info.file_path.lower()

        # Known file patterns
        if "onex_field_model" in path_lower:
            return "ModelOnexFieldModel"
        elif "semver" in path_lower:
            return "ModelSemVer"
        elif "action_spec" in path_lower:
            return "ModelActionSpec"
        elif "log_context" in path_lower:
            return "ModelLogContext"

        return None

    def clear_cache(self) -> None:
        """Clear the resolution cache."""
        self.resolved_cache.clear()
        logger.debug("Cleared reference resolution cache")
