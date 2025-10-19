"""
Omninode/Omnibase Naming Convention Validator with Auto-Detection

Validates naming conventions with automatic repository detection:
- Omninode repositories: Enforces Omninode-specific conventions (Model* prefix, etc.)
- Other repositories: Uses standard PEP 8 conventions

Repository Detection:
- Omninode repos: Paths containing 'omnibase_', '/omni' + lowercase letter (e.g., /omniauth, /omnitools)
- Excluded from Omninode (use PEP 8):
  - Archon repo: Path contains 'Archon'
  - omninode_bridge repo: Path contains 'omninode_bridge' (uses standard PEP 8, not Omninode conventions)
  - omniagent-main repo: Path contains 'omniagent-main' (uses standard PEP 8, not Omninode conventions)
- Other repos: Use standard PEP 8

Omninode Conventions (when detected):

Files:
- Models: `model_*.py` (93% adherence)
- Enums: `enum_*.py` (99% adherence)
- TypedDicts: `typed_dict_*.py` (100% adherence)
- Node Services: `node_<type>_service.py`
- Subcontracts: `model_*_subcontract.py`

Classes:
- Models: `Model<Name>` (PascalCase, 100% adherence)
- Enums: `Enum<Name>` (PascalCase, 100% adherence)
- TypedDicts: `TypedDict<Name>` (PascalCase, 100% adherence)
- Protocols: `<Name>` or `Protocol<Name>` (mixed pattern - simple capability names or Protocol prefix)
- Node Services: `Node<Type>Service` (NodeEffectService, NodeComputeService, etc.)
- Subcontracts: `Model<Type>Subcontract` (ModelAggregationSubcontract, ModelFSMSubcontract, etc.)
- Mixins: `Mixin<Capability>` (MixinNodeService, MixinHealthCheck, etc.)
- Base Classes: `Base<Name>` prefix
- Exception Classes: `<Context>Error` suffix

Functions/Methods/Variables:
- Functions/Methods: snake_case (100% consistency)
- Variables: snake_case (100% consistency)
- Constants: UPPER_SNAKE_CASE (100% consistency)

Standard PEP 8 Conventions (non-Omninode repos):
- Classes: PascalCase (no prefix requirement)
- Functions: snake_case
- Variables: snake_case
- Constants: UPPER_SNAKE_CASE

Performance target: <100ms validation time
"""

import ast
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


@dataclass
class Violation:
    """Represents a naming convention violation."""

    file: str
    line: int
    column: int
    name: str
    violation_type: str
    expected_format: str
    message: str
    suggestion: Optional[str] = None  # Suggested correction

    def __post_init__(self):
        """Set default suggestion from expected_format if not provided."""
        if self.suggestion is None:
            self.suggestion = self.expected_format

    @property
    def rule(self) -> str:
        """Get the rule that was violated (alias for message)."""
        return self.message

    @property
    def type(self) -> str:
        """Get the violation type (alias for violation_type)."""
        return self.violation_type

    def __str__(self) -> str:
        """Format violation for display."""
        return (
            f"{self.file}:{self.line}:{self.column}: "
            f"{self.violation_type} '{self.name}' should be {self.expected_format} "
            f"({self.message})"
        )


class NamingValidator:
    """
    Validates Omninode/Omnibase naming conventions for Python files.

    This validator enforces the actual conventions used in the omnibase_core codebase
    based on analysis of 508 Python files with 98% pattern adherence.

    Omninode Python Conventions:
    - **Model Classes**: Must start with "Model" prefix (100% adherence in codebase)
      Example: ModelTaskData, ModelContractBase, ModelFieldAccessor

    - **Enum Classes**: Must start with "Enum" prefix (100% adherence)
      Example: EnumStatus, EnumNodeType, EnumExecutionStatus

    - **Functions/Methods**: snake_case (100% adherence)
      Example: execute_effect, validate_contract, get_field

    - **Variables**: snake_case (100% adherence)
      Example: correlation_id, task_data, config_value

    - **Constants**: UPPER_SNAKE_CASE (100% adherence)
      Example: MAX_FILE_SIZE, DEFAULT_TIMEOUT

    - **File Naming**:
      - Models: model_*.py (93% adherence)
      - Enums: enum_*.py (99% adherence)
      - TypedDicts: typed_dict_*.py (100% adherence)

    Supported languages:
    - Python: Omninode-specific conventions (primary)
    - TypeScript/JavaScript: camelCase for functions/variables, PascalCase for classes (legacy)
    """

    # Omninode Python patterns
    SNAKE_CASE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
    PASCAL_CASE_PATTERN = re.compile(r"^[A-Z][a-zA-Z0-9]*$")
    UPPER_SNAKE_CASE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")

    # Omninode-specific class prefixes (100% adherence in codebase)
    MODEL_PREFIX_PATTERN = re.compile(r"^Model[A-Z][a-zA-Z0-9]*$")
    ENUM_PREFIX_PATTERN = re.compile(r"^Enum[A-Z][a-zA-Z0-9]*$")
    TYPED_DICT_PREFIX_PATTERN = re.compile(r"^TypedDict[A-Z][a-zA-Z0-9]*$")
    BASE_PREFIX_PATTERN = re.compile(r"^Base[A-Z][a-zA-Z0-9]*$")
    NODE_SERVICE_PATTERN = re.compile(r"^Node[A-Z][a-zA-Z0-9]*Service$")
    MIXIN_PREFIX_PATTERN = re.compile(r"^Mixin[A-Z][a-zA-Z0-9]*$")
    ERROR_SUFFIX_PATTERN = re.compile(r"^[A-Z][a-zA-Z0-9]*Error$")
    SUBCONTRACT_SUFFIX_PATTERN = re.compile(r"^Model[A-Z][a-zA-Z0-9]*Subcontract$")

    # Protocol patterns - mixed convention (simple capability names or Protocol prefix)
    PROTOCOL_PREFIX_PATTERN = re.compile(r"^Protocol[A-Z][a-zA-Z0-9]*$")
    SIMPLE_PROTOCOL_NAMES = {
        "Serializable",
        "Configurable",
        "Executable",
        "Identifiable",
        "Nameable",
        "Validatable",
        "Comparable",
        "Hashable",
    }

    # Omninode file naming patterns
    MODEL_FILE_PATTERN = re.compile(r"^model_[a-z][a-z0-9_]*\.py$")
    ENUM_FILE_PATTERN = re.compile(r"^enum_[a-z][a-z0-9_]*\.py$")
    TYPED_DICT_FILE_PATTERN = re.compile(r"^typed_dict_[a-z][a-z0-9_]*\.py$")
    NODE_SERVICE_FILE_PATTERN = re.compile(r"^node_[a-z][a-z0-9_]*_service\.py$")
    PROTOCOL_FILE_PATTERN = re.compile(r"^protocol_[a-z][a-z0-9_]*\.py$")
    SUBCONTRACT_FILE_PATTERN = re.compile(r"^model_[a-z][a-z0-9_]*_subcontract\.py$")

    # TypeScript/JavaScript patterns (legacy support)
    CAMEL_CASE_PATTERN = re.compile(r"^[a-z][a-zA-Z0-9]*$")

    # TypeScript/JavaScript regex patterns for parsing
    TS_CLASS_PATTERN = re.compile(
        r"^\s*(?:export\s+)?(?:abstract\s+)?class\s+([A-Za-z_][A-Za-z0-9_]*)"
    )
    TS_INTERFACE_PATTERN = re.compile(
        r"^\s*(?:export\s+)?interface\s+([A-Za-z_][A-Za-z0-9_]*)"
    )
    TS_FUNCTION_PATTERN = re.compile(
        r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_][A-Za-z0-9_]*)"
    )
    TS_CONST_PATTERN = re.compile(r"^\s*(?:export\s+)?const\s+([A-Z][A-Z0-9_]*)\s*[=:]")
    TS_VARIABLE_PATTERN = re.compile(
        r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_][A-Za-z0-9_]*)\s*[=:]"
    )

    def __init__(self, language: str = None, validation_mode: str = "auto"):
        """
        Initialize the naming validator.

        Args:
            language: Optional language hint ('python', 'typescript', 'javascript').
                     If not provided, will be detected from file extension.
            validation_mode: Validation mode selection:
                - "auto" (default): Auto-detect repository type and apply appropriate conventions
                - "omninode": Force Omninode conventions (Model* prefix, etc.)
                - "pep8": Force standard PEP 8 conventions
        """
        self.violations: List[Violation] = []
        self.language = language
        self.validation_mode = validation_mode

    @staticmethod
    def is_omninode_repo(file_path: str) -> bool:
        """
        Detect if a file path is in an Omninode repository.

        Omninode repository patterns:
        - Contains 'omnibase_' (case-insensitive) - e.g., omnibase_core, omnibase_spi
        - Contains '/omni' followed by lowercase letter - e.g., /omniauth, /omnitools

        Non-Omninode patterns (use standard PEP 8):
        - Contains 'Archon' - uses standard PEP 8
        - Contains 'omninode_bridge' - uses standard PEP 8 (NOT Omninode conventions)
        - Contains 'omniagent-main' - uses standard PEP 8 (NOT Omninode conventions)
        - Any other path - uses standard PEP 8

        Args:
            file_path: Path to the file being validated

        Returns:
            True if path is in Omninode repository, False otherwise
        """
        path_lower = file_path.lower()

        # Check for Archon repo (explicit exclusion)
        if "archon" in path_lower:
            return False

        # Check for omninode_bridge repo (explicit exclusion - uses standard PEP 8)
        if "omninode_bridge" in path_lower:
            return False

        # Check for omniagent-main repo (explicit exclusion - uses standard PEP 8)
        if "omniagent-main" in path_lower:
            return False

        # Check for omnibase_ pattern
        if "omnibase_" in path_lower:
            return True

        # Check for /omni followed by lowercase letter (omniauth, omnitools, etc.)
        # This pattern avoids false positives like "omni" in the middle of words
        if re.search(r"/omni[a-z]", file_path):
            return True

        return False

    def validate_content(self, content: str, file_path: str) -> List[Violation]:
        """
        Validate naming conventions in content (in-memory validation).

        Supports auto-detection mode to apply appropriate conventions based on repository type.

        Args:
            content: Source code content to validate
            file_path: Path to the file (used for language detection and error reporting)

        Returns:
            List of naming violations found
        """
        self.violations = []
        path = Path(file_path)
        suffix = path.suffix.lower()

        # Detect language from file extension or use provided language
        if self.language:
            lang = self.language.lower()
        elif suffix == ".py":
            lang = "python"
        elif suffix in [".ts", ".tsx"]:
            lang = "typescript"
        elif suffix in [".js", ".jsx"]:
            lang = "javascript"
        else:
            return self.violations

        # Determine validation mode
        if self.validation_mode == "auto":
            # Auto-detect repository type
            is_omninode = self.is_omninode_repo(file_path)
            effective_mode = "omninode" if is_omninode else "pep8"
        else:
            effective_mode = self.validation_mode

        try:
            if lang == "python":
                if effective_mode == "omninode":
                    self._validate_python(file_path, content)
                else:
                    self._validate_python_pep8(file_path, content)
            elif lang in ["typescript", "javascript"]:
                self._validate_typescript_javascript(file_path, content)
        except Exception:
            # Gracefully handle syntax errors and other issues
            pass

        return self.violations

    def validate_file(self, file_path: str) -> List[Violation]:
        """
        Validate naming conventions in a file.

        Args:
            file_path: Path to the file to validate

        Returns:
            List of naming violations found
        """
        self.violations = []
        path = Path(file_path)

        if not path.exists():
            return self.violations

        suffix = path.suffix.lower()

        try:
            content = path.read_text(encoding="utf-8")

            if suffix == ".py":
                self._validate_python(file_path, content)
            elif suffix in [".ts", ".tsx", ".js", ".jsx"]:
                self._validate_typescript_javascript(file_path, content)

        except Exception:
            # Gracefully handle syntax errors and other issues
            # Invalid code should pass through without failing the validator
            pass

        return self.violations

    def _validate_python(self, file_path: str, content: str) -> None:
        """
        Validate Omninode Python naming conventions using AST parsing.

        Omninode Conventions (based on 508-file codebase analysis):
        - **Model Classes**: Must have "Model" prefix (100% adherence)
        - **Enum Classes**: Must have "Enum" prefix (100% adherence)
        - **Functions/Methods**: snake_case (100% adherence)
        - **Variables**: snake_case (100% adherence)
        - **Constants**: UPPER_SNAKE_CASE (100% adherence)
        - **Base Classes**: "Base" prefix
        - **Service Classes**: "Node<Type>Service" pattern
        - **Exceptions**: "<Context>Error" suffix
        """
        try:
            tree = ast.parse(content)
        except SyntaxError:
            # Let invalid Python code pass through
            return

        # Validate file naming patterns
        self._validate_file_naming(file_path, tree)

        for node in ast.walk(tree):
            # Validate function names (100% snake_case in Omninode)
            if isinstance(node, ast.FunctionDef):
                if (
                    not self._is_snake_case(node.name)
                    and not node.name.startswith("_")
                    and not node.name.startswith("__")
                ):
                    self.violations.append(
                        Violation(
                            file=file_path,
                            line=node.lineno,
                            column=node.col_offset,
                            name=node.name,
                            violation_type="function",
                            expected_format="snake_case",
                            message=f"Omninode functions must use snake_case, use '{self._to_snake_case(node.name)}' instead",
                        )
                    )

            # Validate class names with Omninode-specific patterns
            elif isinstance(node, ast.ClassDef):
                self._validate_omninode_class_name(file_path, node, tree)

            # Validate variable names and constants
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        name = target.id

                        # Skip enum members - they use UPPER_SNAKE_CASE by convention
                        if self._is_enum_member(node, tree):
                            continue

                        # Check if it's a module-level constant (all uppercase)
                        if self._is_module_level_constant(node, tree):
                            if not self._is_upper_snake_case(name):
                                self.violations.append(
                                    Violation(
                                        file=file_path,
                                        line=target.lineno,
                                        column=target.col_offset,
                                        name=name,
                                        violation_type="constant",
                                        expected_format="UPPER_SNAKE_CASE",
                                        message=f"Omninode constants must use UPPER_SNAKE_CASE, use '{self._to_upper_snake_case(name)}' instead",
                                    )
                                )
                        else:
                            # Regular variable - must be snake_case (100% in Omninode)
                            if not self._is_snake_case(name) and not name.startswith(
                                "_"
                            ):
                                self.violations.append(
                                    Violation(
                                        file=file_path,
                                        line=target.lineno,
                                        column=target.col_offset,
                                        name=name,
                                        violation_type="variable",
                                        expected_format="snake_case",
                                        message=f"Omninode variables must use snake_case, use '{self._to_snake_case(name)}' instead",
                                    )
                                )

    def _validate_python_pep8(self, file_path: str, content: str) -> None:
        """
        Validate standard PEP 8 Python naming conventions using AST parsing.

        Standard PEP 8 Conventions:
        - **Classes**: PascalCase (no prefix requirement)
        - **Functions/Methods**: snake_case
        - **Variables**: snake_case
        - **Constants**: UPPER_SNAKE_CASE
        - **Exceptions**: PascalCase with Error suffix

        This is used for non-Omninode repositories like Archon.
        """
        try:
            tree = ast.parse(content)
        except SyntaxError:
            # Let invalid Python code pass through
            return

        for node in ast.walk(tree):
            # Validate function names (snake_case in PEP 8)
            if isinstance(node, ast.FunctionDef):
                if (
                    not self._is_snake_case(node.name)
                    and not node.name.startswith("_")
                    and not node.name.startswith("__")
                ):
                    self.violations.append(
                        Violation(
                            file=file_path,
                            line=node.lineno,
                            column=node.col_offset,
                            name=node.name,
                            violation_type="function",
                            expected_format="snake_case",
                            message=f"PEP 8: Functions must use snake_case, use '{self._to_snake_case(node.name)}' instead",
                            suggestion=self._to_snake_case(node.name),
                        )
                    )

            # Validate class names (PascalCase in PEP 8)
            elif isinstance(node, ast.ClassDef):
                if not self._is_pascal_case(node.name):
                    self.violations.append(
                        Violation(
                            file=file_path,
                            line=node.lineno,
                            column=node.col_offset,
                            name=node.name,
                            violation_type="class",
                            expected_format="PascalCase",
                            message=f"PEP 8: Classes must use PascalCase, use '{self._to_pascal_case(node.name)}' instead",
                        )
                    )

            # Validate variable names and constants
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        name = target.id

                        # Skip enum members - they use UPPER_SNAKE_CASE by convention
                        if self._is_enum_member(node, tree):
                            continue

                        # Check if it's a module-level constant (all uppercase)
                        if self._is_module_level_constant(node, tree):
                            if not self._is_upper_snake_case(name):
                                self.violations.append(
                                    Violation(
                                        file=file_path,
                                        line=target.lineno,
                                        column=target.col_offset,
                                        name=name,
                                        violation_type="constant",
                                        expected_format="UPPER_SNAKE_CASE",
                                        message=f"PEP 8: Constants must use UPPER_SNAKE_CASE, use '{self._to_upper_snake_case(name)}' instead",
                                    )
                                )
                        else:
                            # Regular variable - must be snake_case
                            if not self._is_snake_case(name) and not name.startswith(
                                "_"
                            ):
                                self.violations.append(
                                    Violation(
                                        file=file_path,
                                        line=target.lineno,
                                        column=target.col_offset,
                                        name=name,
                                        violation_type="variable",
                                        expected_format="snake_case",
                                        message=f"PEP 8: Variables must use snake_case, use '{self._to_snake_case(name)}' instead",
                                    )
                                )

    def _validate_typescript_javascript(self, file_path: str, content: str) -> None:
        """
        Validate TypeScript/JavaScript naming conventions using regex.

        Conventions:
        - Functions and variables: camelCase
        - Classes and interfaces: PascalCase
        - Constants: UPPER_SNAKE_CASE
        """
        lines = content.split("\n")

        for line_num, line in enumerate(lines, start=1):
            # Skip comments and strings
            if line.strip().startswith("//") or line.strip().startswith("/*"):
                continue

            # Validate class names
            class_match = self.TS_CLASS_PATTERN.search(line)
            if class_match:
                name = class_match.group(1)
                if not self._is_pascal_case(name):
                    self.violations.append(
                        Violation(
                            file=file_path,
                            line=line_num,
                            column=class_match.start(1),
                            name=name,
                            violation_type="class",
                            expected_format="PascalCase",
                            message=f"use '{self._to_pascal_case(name)}' instead",
                        )
                    )

            # Validate interface names
            interface_match = self.TS_INTERFACE_PATTERN.search(line)
            if interface_match:
                name = interface_match.group(1)
                if not self._is_pascal_case(name):
                    self.violations.append(
                        Violation(
                            file=file_path,
                            line=line_num,
                            column=interface_match.start(1),
                            name=name,
                            violation_type="interface",
                            expected_format="PascalCase",
                            message=f"use '{self._to_pascal_case(name)}' instead",
                        )
                    )

            # Validate function names
            function_match = self.TS_FUNCTION_PATTERN.search(line)
            if function_match:
                name = function_match.group(1)
                if not self._is_camel_case(name):
                    self.violations.append(
                        Violation(
                            file=file_path,
                            line=line_num,
                            column=function_match.start(1),
                            name=name,
                            violation_type="function",
                            expected_format="camelCase",
                            message=f"use '{self._to_camel_case(name)}' instead",
                        )
                    )

            # Validate constants
            const_match = self.TS_CONST_PATTERN.search(line)
            if const_match:
                name = const_match.group(1)
                if not self._is_upper_snake_case(name):
                    self.violations.append(
                        Violation(
                            file=file_path,
                            line=line_num,
                            column=const_match.start(1),
                            name=name,
                            violation_type="constant",
                            expected_format="UPPER_SNAKE_CASE",
                            message=f"use '{self._to_upper_snake_case(name)}' instead",
                        )
                    )

            # Validate regular variables
            var_match = self.TS_VARIABLE_PATTERN.search(line)
            if var_match and not const_match:  # Skip if already matched as constant
                name = var_match.group(1)
                if not self._is_camel_case(name):
                    self.violations.append(
                        Violation(
                            file=file_path,
                            line=line_num,
                            column=var_match.start(1),
                            name=name,
                            violation_type="variable",
                            expected_format="camelCase",
                            message=f"use '{self._to_camel_case(name)}' instead",
                        )
                    )

    # Omninode-specific validation helpers

    def _validate_file_naming(self, file_path: str, tree: ast.Module) -> None:
        """
        Validate Omninode file naming patterns.

        Based on codebase analysis:
        - Files with Model classes: should be model_*.py (93% adherence)
        - Files with Enum classes: should be enum_*.py (99% adherence)
        - Files with TypedDict classes: should be typed_dict_*.py (100% adherence)
        """
        path = Path(file_path)
        filename = path.name

        # Skip __init__.py and test files
        if filename == "__init__.py" or filename.startswith("test_"):
            return

        # Check for class types in file
        has_model_class = False
        has_enum_class = False
        has_typeddict_class = False
        has_node_service_class = False
        has_protocol_class = False

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                # Check base classes
                base_names = [
                    (
                        base.id
                        if isinstance(base, ast.Name)
                        else base.attr if isinstance(base, ast.Attribute) else None
                    )
                    for base in node.bases
                ]

                # Check if class starts with Model
                if node.name.startswith("Model"):
                    has_model_class = True
                # Check if class starts with Enum
                elif node.name.startswith("Enum"):
                    has_enum_class = True
                # Check if class starts with TypedDict
                elif node.name.startswith("TypedDict"):
                    has_typeddict_class = True
                # Check if class is Node service pattern
                elif self.NODE_SERVICE_PATTERN.match(node.name):
                    has_node_service_class = True
                # Check if class is Protocol
                elif "Protocol" in base_names:
                    has_protocol_class = True

        # Validate file naming based on class types
        # Priority order: Model > TypedDict > NodeService > Protocol > Enum
        # This handles mixed files where multiple class types exist
        # Only check the highest priority type present
        if has_model_class:
            # Model class takes priority - only check model_*.py naming
            if not self.MODEL_FILE_PATTERN.match(
                filename
            ) and not self.SUBCONTRACT_FILE_PATTERN.match(filename):
                self.violations.append(
                    Violation(
                        file=file_path,
                        line=1,
                        column=0,
                        name=filename,
                        violation_type="file",
                        expected_format="model_*.py or model_*_subcontract.py",
                        message="Omninode files with Model classes should use 'model_*.py' naming (93% adherence in codebase)",
                    )
                )
        elif has_typeddict_class:
            # TypedDict takes priority if no Model class
            if not self.TYPED_DICT_FILE_PATTERN.match(filename):
                self.violations.append(
                    Violation(
                        file=file_path,
                        line=1,
                        column=0,
                        name=filename,
                        violation_type="file",
                        expected_format="typed_dict_*.py",
                        message="Omninode files with TypedDict classes should use 'typed_dict_*.py' naming (100% adherence in codebase)",
                    )
                )
        elif has_node_service_class:
            # Node service pattern if no Model or TypedDict
            if not self.NODE_SERVICE_FILE_PATTERN.match(filename):
                self.violations.append(
                    Violation(
                        file=file_path,
                        line=1,
                        column=0,
                        name=filename,
                        violation_type="file",
                        expected_format="node_<type>_service.py",
                        message="Omninode files with Node service classes should use 'node_<type>_service.py' naming",
                    )
                )
        elif has_protocol_class:
            # Protocol pattern - only suggested, not enforced strictly
            # Protocols can exist in various files, especially in SPI modules
            pass
        elif has_enum_class:
            # Enum is checked only if no other priority types
            if not self.ENUM_FILE_PATTERN.match(filename):
                self.violations.append(
                    Violation(
                        file=file_path,
                        line=1,
                        column=0,
                        name=filename,
                        violation_type="file",
                        expected_format="enum_*.py",
                        message="Omninode files with Enum classes should use 'enum_*.py' naming (99% adherence in codebase)",
                    )
                )

    def _validate_omninode_class_name(
        self, file_path: str, node: ast.ClassDef, tree: ast.Module
    ) -> None:
        """
        Validate Omninode-specific class naming conventions.

        Based on codebase analysis (100% adherence):
        - BaseModel subclasses: Must start with "Model"
        - Enum subclasses: Must start with "Enum"
        - TypedDict subclasses: Must start with "TypedDict"
        - Base classes: Should start with "Base"
        - Node services: Should match "Node<Type>Service"
        - Exceptions: Should end with "Error"
        - Dataclasses: No prefix required (different pattern)
        """
        class_name = node.name

        # Check for special base classes
        base_names = []
        for base in node.bases:
            if isinstance(base, ast.Name):
                base_names.append(base.id)
            elif isinstance(base, ast.Attribute):
                base_names.append(base.attr)

        # Pydantic BaseModel subclasses must have "Model" prefix (100% adherence)
        if "BaseModel" in base_names:
            if not self.MODEL_PREFIX_PATTERN.match(class_name):
                suggestion = (
                    f"Model{class_name}"
                    if not class_name.startswith("Model")
                    else class_name
                )
                self.violations.append(
                    Violation(
                        file=file_path,
                        line=node.lineno,
                        column=node.col_offset,
                        name=class_name,
                        violation_type="class",
                        expected_format="Model<Name> (PascalCase with Model prefix)",
                        message=f"Omninode BaseModel classes must start with 'Model' prefix (100% adherence), use '{suggestion}' instead",
                        suggestion=suggestion,
                    )
                )

        # Enum subclasses must have "Enum" prefix (100% adherence)
        if "Enum" in base_names or "str, Enum" in str(base_names):
            if not self.ENUM_PREFIX_PATTERN.match(class_name):
                suggestion = (
                    f"Enum{class_name}"
                    if not class_name.startswith("Enum")
                    else class_name
                )
                self.violations.append(
                    Violation(
                        file=file_path,
                        line=node.lineno,
                        column=node.col_offset,
                        name=class_name,
                        violation_type="class",
                        expected_format="Enum<Name> (PascalCase with Enum prefix)",
                        message=f"Omninode Enum classes must start with 'Enum' prefix (100% adherence), use '{suggestion}' instead",
                        suggestion=suggestion,
                    )
                )

        # TypedDict subclasses should have "TypedDict" prefix
        if "TypedDict" in base_names:
            if not self.TYPED_DICT_PREFIX_PATTERN.match(class_name):
                suggestion = (
                    f"TypedDict{class_name}"
                    if not class_name.startswith("TypedDict")
                    else class_name
                )
                self.violations.append(
                    Violation(
                        file=file_path,
                        line=node.lineno,
                        column=node.col_offset,
                        name=class_name,
                        violation_type="class",
                        expected_format="TypedDict<Name> (PascalCase with TypedDict prefix)",
                        message=f"Omninode TypedDict classes should start with 'TypedDict' prefix, use '{suggestion}' instead",
                        suggestion=suggestion,
                    )
                )

        # Node service classes should match Node<Type>Service pattern
        if "Service" in class_name and class_name.startswith("Node"):
            if not self.NODE_SERVICE_PATTERN.match(class_name):
                self.violations.append(
                    Violation(
                        file=file_path,
                        line=node.lineno,
                        column=node.col_offset,
                        name=class_name,
                        violation_type="class",
                        expected_format="Node<Type>Service (PascalCase)",
                        message="Omninode Node service classes should match 'Node<Type>Service' pattern",
                    )
                )

        # Protocol classes - mixed convention allowed
        if "Protocol" in base_names:
            # Allow both simple names (Serializable) and Protocol prefix (ProtocolMetadataProvider)
            is_simple_protocol = class_name in self.SIMPLE_PROTOCOL_NAMES
            has_protocol_prefix = self.PROTOCOL_PREFIX_PATTERN.match(class_name)

            # Only warn if it's neither a simple protocol name nor has Protocol prefix
            # This is a soft check - protocols have flexible naming
            if (
                not is_simple_protocol
                and not has_protocol_prefix
                and not self._is_pascal_case(class_name)
            ):
                # Only enforce PascalCase, not the prefix
                self.violations.append(
                    Violation(
                        file=file_path,
                        line=node.lineno,
                        column=node.col_offset,
                        name=class_name,
                        violation_type="class",
                        expected_format="PascalCase (optionally with Protocol prefix for complex protocols)",
                        message="Omninode Protocol classes should use PascalCase. Simple capability names (Serializable, Configurable) or Protocol prefix for complex protocols",
                    )
                )

        # Subcontract classes should match Model<Type>Subcontract pattern
        if class_name.endswith("Subcontract"):
            if not self.SUBCONTRACT_SUFFIX_PATTERN.match(class_name):
                self.violations.append(
                    Violation(
                        file=file_path,
                        line=node.lineno,
                        column=node.col_offset,
                        name=class_name,
                        violation_type="class",
                        expected_format="Model<Type>Subcontract (PascalCase with Model prefix)",
                        message="Omninode Subcontract classes should match 'Model<Type>Subcontract' pattern",
                    )
                )

        # Mixin classes should start with "Mixin"
        if "Mixin" in class_name and not self.MIXIN_PREFIX_PATTERN.match(class_name):
            suggestion = f"Mixin{class_name.replace('Mixin', '')}"
            self.violations.append(
                Violation(
                    file=file_path,
                    line=node.lineno,
                    column=node.col_offset,
                    name=class_name,
                    violation_type="class",
                    expected_format="Mixin<Capability> (PascalCase with Mixin prefix)",
                    message=f"Omninode Mixin classes should start with 'Mixin' prefix, use '{suggestion}' instead",
                    suggestion=suggestion,
                )
            )

        # Exception classes should end with "Error"
        if any(
            base in ["Exception", "BaseException", "OnexError"] for base in base_names
        ):
            if not self.ERROR_SUFFIX_PATTERN.match(class_name):
                suggestion = (
                    f"{class_name}Error"
                    if not class_name.endswith("Error")
                    else class_name
                )
                self.violations.append(
                    Violation(
                        file=file_path,
                        line=node.lineno,
                        column=node.col_offset,
                        name=class_name,
                        violation_type="class",
                        expected_format="<Context>Error (PascalCase with Error suffix)",
                        message=f"Omninode Exception classes should end with 'Error' suffix, use '{suggestion}' instead",
                        suggestion=suggestion,
                    )
                )

    # Helper methods for checking naming conventions

    def _is_snake_case(self, name: str) -> bool:
        """Check if name follows snake_case convention."""
        return bool(self.SNAKE_CASE_PATTERN.match(name))

    def _is_camel_case(self, name: str) -> bool:
        """Check if name follows camelCase convention."""
        return bool(self.CAMEL_CASE_PATTERN.match(name))

    def _is_pascal_case(self, name: str) -> bool:
        """Check if name follows PascalCase convention."""
        return bool(self.PASCAL_CASE_PATTERN.match(name))

    def _is_upper_snake_case(self, name: str) -> bool:
        """Check if name follows UPPER_SNAKE_CASE convention."""
        return bool(self.UPPER_SNAKE_CASE_PATTERN.match(name))

    def _is_module_level_constant(self, node: ast.Assign, tree: ast.Module) -> bool:
        """
        Check if an assignment is a module-level constant.

        A constant is considered module-level if:
        1. It's at the top level of the module (not inside a function or class)
        2. The name is all uppercase
        """
        for body_node in tree.body:
            if body_node == node:
                # Check if any target is all uppercase
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        if target.id.isupper():
                            return True
                return False
        return False

    def _is_enum_member(self, node: ast.Assign, tree: ast.Module) -> bool:
        """
        Check if an assignment is an enum member.

        Enum members are class-level assignments inside Enum classes and use UPPER_SNAKE_CASE.
        """
        # Walk through all class definitions to find if this assignment is inside an Enum class
        for class_node in ast.walk(tree):
            if isinstance(class_node, ast.ClassDef):
                # Check if this class inherits from Enum
                is_enum_class = False
                for base in class_node.bases:
                    if isinstance(base, ast.Name) and base.id == "Enum":
                        is_enum_class = True
                        break

                if is_enum_class:
                    # Check if this assignment is in the class body
                    for body_item in class_node.body:
                        if body_item == node:
                            return True

        return False

    # Helper methods for case conversion

    def _to_snake_case(self, name: str) -> str:
        """Convert a name to snake_case."""
        # Insert underscores before uppercase letters
        name = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
        name = re.sub("([a-z0-9])([A-Z])", r"\1_\2", name)
        return name.lower()

    def _to_camel_case(self, name: str) -> str:
        """Convert a name to camelCase."""
        # Split on underscores and capitalize each word except the first
        parts = name.split("_")
        if not parts:
            return name
        return parts[0].lower() + "".join(word.capitalize() for word in parts[1:])

    def _to_pascal_case(self, name: str) -> str:
        """Convert a name to PascalCase."""
        # Split on underscores and capitalize each word
        parts = name.split("_")
        return "".join(word.capitalize() for word in parts)

    def _to_upper_snake_case(self, name: str) -> str:
        """Convert a name to UPPER_SNAKE_CASE."""
        # Convert to snake_case first, then uppercase
        snake = self._to_snake_case(name)
        return snake.upper()
