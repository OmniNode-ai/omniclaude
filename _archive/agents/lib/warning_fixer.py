#!/usr/bin/env python3
"""
Automatic Warning Fixer - Poly 3 Implementation

Deterministic fixes for common validation warnings (G12, G13, G14).
Applies pattern-based transformations to generated code BEFORE AI refinement.

This reduces costs and improves generation success rates by fixing known issues
using deterministic rules rather than expensive AI calls.
"""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class FixResult:
    """Result of applying a fix."""

    fixed_code: str
    fixes_applied: list[str] = field(default_factory=list)
    warnings_fixed: list[str] = field(default_factory=list)
    fix_count: int = 0
    success: bool = True
    error_message: str | None = None


@dataclass
class ValidationWarning:
    """Represents a validation warning."""

    gate_id: str  # G12, G13, G14
    warning_type: str  # e.g., "missing_config", "missing_type_hint"
    line_number: int | None = None
    column_number: int | None = None
    message: str = ""


class WarningFixer:
    """
    Automatic fixes for validation warnings.

    Applies deterministic pattern-based fixes for:
    - G12: Pydantic v2 ConfigDict issues
    - G13: Missing type hints
    - G14: Import errors

    Usage:
        fixer = WarningFixer()
        result = fixer.fix_all_warnings(code, file_path)
        if result.fix_count > 0:
            print(f"Applied {result.fix_count} fixes")
    """

    # Standard imports for each node type
    NODE_TYPE_IMPORTS = {
        "effect": [
            "from typing import Any, Dict, List, Optional",
            "from uuid import UUID",
            "from omnibase_core.nodes.node_effect import NodeEffect",
            "from omnibase_core.errors import EnumCoreErrorCode, ModelOnexError",
        ],
        "compute": [
            "from typing import Any, Dict, List, Optional",
            "from uuid import UUID",
            "from omnibase_core.nodes.node_compute import NodeCompute",
            "from omnibase_core.errors import EnumCoreErrorCode, ModelOnexError",
        ],
        "reducer": [
            "from typing import Any, Dict, List, Optional",
            "from uuid import UUID",
            "from omnibase_core.nodes.node_reducer import NodeReducer",
            "from omnibase_core.errors import EnumCoreErrorCode, ModelOnexError",
        ],
        "orchestrator": [
            "from typing import Any, Dict, List, Optional",
            "from uuid import UUID",
            "from omnibase_core.nodes.node_orchestrator import NodeOrchestrator",
            "from omnibase_core.errors import EnumCoreErrorCode, ModelOnexError",
        ],
    }

    # Common type hints for methods
    COMMON_METHOD_HINTS = {
        "__init__": "-> None",
        "_validate_input": "-> None",
        "_execute_business_logic": "-> Dict[str, Any]",
        "_execute_computation": "-> Dict[str, Any]",
        "_handle_error": "-> None",
        "_log_operation": "-> None",
    }

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def fix_all_warnings(self, code: str, file_path: Path | None = None) -> FixResult:
        """
        Apply all automatic fixes to code.

        Runs fixes in optimal order:
        1. G14 - Import fixes (must come first)
        2. G12 - Pydantic ConfigDict (structural changes)
        3. G13 - Type hints (final polish)

        Args:
            code: Source code to fix
            file_path: Optional file path for context

        Returns:
            FixResult with fixed code and applied fixes
        """
        self.logger.info("Starting automatic warning fixes")

        result = FixResult(fixed_code=code)

        try:
            # Phase 1: Fix imports (G14)
            import_result = self.fix_g14_imports(result.fixed_code, file_path)
            if import_result.fix_count > 0:
                result.fixed_code = import_result.fixed_code
                result.fixes_applied.extend(import_result.fixes_applied)
                result.warnings_fixed.append("G14")
                result.fix_count += import_result.fix_count

            # Phase 2: Fix Pydantic models (G12)
            pydantic_result = self.fix_g12_pydantic_config(result.fixed_code, file_path)
            if pydantic_result.fix_count > 0:
                result.fixed_code = pydantic_result.fixed_code
                result.fixes_applied.extend(pydantic_result.fixes_applied)
                result.warnings_fixed.append("G12")
                result.fix_count += pydantic_result.fix_count

            # Phase 3: Fix type hints (G13)
            type_result = self.fix_g13_type_hints(result.fixed_code)
            if type_result.fix_count > 0:
                result.fixed_code = type_result.fixed_code
                result.fixes_applied.extend(type_result.fixes_applied)
                result.warnings_fixed.append("G13")
                result.fix_count += type_result.fix_count

            self.logger.info(
                f"Applied {result.fix_count} fixes: {', '.join(result.fixes_applied)}"
            )

        except Exception as e:
            self.logger.error(f"Error during warning fixes: {e}", exc_info=True)
            result.success = False
            result.error_message = str(e)

        return result

    def fix_g12_pydantic_config(
        self, code: str, file_path: Path | None = None
    ) -> FixResult:
        """
        G12: Add Pydantic v2 ConfigDict to models.

        Detects:
        - class Model*(...BaseModel): without ConfigDict
        - Old Pydantic v1 patterns (.dict(), .parse_obj())

        Adds:
        - model_config = ConfigDict(extra="forbid", validate_assignment=True)
        - Pydantic v2 import if missing

        Args:
            code: Source code to fix
            file_path: Optional file path for context

        Returns:
            FixResult with Pydantic v2 compliance fixes
        """
        self.logger.debug("Applying G12 Pydantic ConfigDict fixes")

        result = FixResult(fixed_code=code)
        lines = code.split("\n")
        modified = False

        # Step 1: Ensure ConfigDict import
        has_configdict_import = "from pydantic import" in code and "ConfigDict" in code
        if not has_configdict_import and "from pydantic import" in code:
            for i, line in enumerate(lines):
                if line.strip().startswith("from pydantic import"):
                    # Add ConfigDict to import
                    if "ConfigDict" not in line:
                        # Parse existing imports
                        import_match = re.match(
                            r"from pydantic import (.+)", line.strip()
                        )
                        if import_match:
                            existing_imports = import_match.group(1)
                            # Add ConfigDict
                            lines[i] = (
                                f"from pydantic import {existing_imports}, ConfigDict"
                            )
                            result.fixes_applied.append("Added ConfigDict import")
                            modified = True
                            break

        # Step 2: Find Pydantic models and add model_config
        _in_class = False
        class_indent = 0
        class_name = ""

        for i, line in enumerate(lines):
            # Detect class definition
            class_match = re.match(r"^(\s*)class (Model\w+)\(.*BaseModel.*\):", line)
            if class_match:
                _in_class = True
                class_indent = len(class_match.group(1))
                class_name = class_match.group(2)

                # Check if model_config already exists in next few lines
                has_config = False
                for j in range(i + 1, min(i + 10, len(lines))):
                    if "model_config" in lines[j]:
                        has_config = True
                        break
                    # Stop at next class or method
                    if lines[j].strip().startswith("class ") or lines[
                        j
                    ].strip().startswith("def "):
                        break

                if not has_config:
                    # Find where to insert model_config (after docstring if present)
                    insert_line = i + 1

                    # Skip docstring if present
                    if insert_line < len(lines) and '"""' in lines[insert_line]:
                        # Find end of docstring
                        for j in range(insert_line, min(insert_line + 20, len(lines))):
                            if '"""' in lines[j] and j > insert_line:
                                insert_line = j + 1
                                break

                    # Determine config based on model name
                    if "Input" in class_name or "Config" in class_name:
                        config_line = (
                            " " * (class_indent + 4)
                            + 'model_config = ConfigDict(extra="forbid", '
                            "validate_assignment=True, str_strip_whitespace=True)"
                        )
                    else:  # Output models
                        config_line = (
                            " " * (class_indent + 4)
                            + 'model_config = ConfigDict(extra="allow", '
                            "validate_assignment=True)"
                        )

                    # Insert blank line and config
                    lines.insert(insert_line, "")
                    lines.insert(insert_line + 1, config_line)

                    result.fixes_applied.append(f"Added model_config to {class_name}")
                    modified = True

        # Step 3: Fix Pydantic v1 patterns
        pydantic_v1_patterns = {
            r"\.dict\(\)": ".model_dump()",
            r"\.parse_obj\(": ".model_validate(",
            r"\.json\(\)": ".model_dump_json()",
            r"\.parse_raw\(": ".model_validate_json(",
        }

        for i, line in enumerate(lines):
            for old_pattern, new_pattern in pydantic_v1_patterns.items():
                if re.search(old_pattern, line):
                    lines[i] = re.sub(old_pattern, new_pattern, line)
                    result.fixes_applied.append(
                        f"Replaced Pydantic v1 pattern: {old_pattern} → {new_pattern}"
                    )
                    modified = True

        if modified:
            result.fixed_code = "\n".join(lines)
            result.fix_count = len(result.fixes_applied)

        return result

    def fix_g13_type_hints(self, code: str) -> FixResult:
        """
        G13: Add missing type hints.

        Detects:
        - Methods without return type hints
        - Parameters without type annotations
        - Common patterns in generated code

        Adds:
        - Return type hints based on method name patterns
        - Parameter type hints for common patterns
        - Import additions for typing module

        Args:
            code: Source code to fix

        Returns:
            FixResult with type hint additions
        """
        self.logger.debug("Applying G13 type hint fixes")

        result = FixResult(fixed_code=code)
        lines = code.split("\n")
        modified = False

        # Ensure typing imports
        has_typing = "from typing import" in code
        if not has_typing:
            # Find first import and add typing
            for i, line in enumerate(lines):
                if line.strip().startswith("import ") or line.strip().startswith(
                    "from "
                ):
                    lines.insert(i, "from typing import Any, Dict, List, Optional")
                    result.fixes_applied.append("Added typing imports")
                    modified = True
                    break

        # Fix method signatures
        for i, line in enumerate(lines):
            # Match method definitions without type hints
            method_match = re.match(r"^(\s*)def (\w+)\((.*?)\)(\s*):(.*)", line)
            if method_match:
                indent = method_match.group(1)
                method_name = method_match.group(2)
                params = method_match.group(3)
                _whitespace = method_match.group(4)
                rest = method_match.group(5)

                # Skip if already has return type hint
                if "->" in params or "->" in rest:
                    continue

                # Add return type hint based on method name
                return_hint = self.COMMON_METHOD_HINTS.get(method_name)
                if not return_hint:
                    # Infer from method name
                    if method_name.startswith("_validate"):
                        return_hint = "-> None"
                    elif method_name.startswith("_execute"):
                        return_hint = "-> Dict[str, Any]"
                    elif method_name.startswith("_get"):
                        return_hint = "-> Any"
                    elif method_name.startswith("_is") or method_name.startswith(
                        "_has"
                    ):
                        return_hint = "-> bool"
                    elif method_name.startswith("_count"):
                        return_hint = "-> int"
                    else:
                        return_hint = "-> Any"

                # Reconstruct line with return hint
                lines[i] = f"{indent}def {method_name}({params}) {return_hint}:{rest}"
                result.fixes_applied.append(f"Added return type to {method_name}")
                modified = True

        if modified:
            result.fixed_code = "\n".join(lines)
            result.fix_count = len(result.fixes_applied)

        return result

    def fix_g14_imports(self, code: str, file_path: Path | None = None) -> FixResult:
        """
        G14: Fix import errors.

        Detects and fixes:
        - Missing imports for standard libraries
        - Unterminated strings in docstrings
        - Circular import issues
        - Missing ONEX base class imports

        Args:
            code: Source code to fix
            file_path: Optional file path for node type detection

        Returns:
            FixResult with import fixes
        """
        self.logger.debug("Applying G14 import fixes")

        result = FixResult(fixed_code=code)
        lines = code.split("\n")
        modified = False

        # Step 1: Fix unterminated docstrings
        docstring_fixes = self._fix_unterminated_docstrings(lines)
        if docstring_fixes > 0:
            result.fixes_applied.append(
                f"Fixed {docstring_fixes} unterminated docstrings"
            )
            modified = True

        # Step 2: Detect node type and add required imports
        node_type = self._detect_node_type(code, file_path)
        if node_type:
            missing_imports = self._get_missing_imports(code, node_type)
            if missing_imports:
                # Find where to insert imports (after shebang and module docstring)
                insert_pos = self._find_import_insertion_point(lines)

                # Insert missing imports
                for imp in reversed(missing_imports):
                    lines.insert(insert_pos, imp)

                result.fixes_applied.append(
                    f"Added {len(missing_imports)} required imports for {node_type} node"
                )
                modified = True

        # Step 3: Fix common import issues
        import_fixes = self._fix_common_import_issues(lines)
        if import_fixes > 0:
            result.fixes_applied.append(f"Fixed {import_fixes} import issues")
            modified = True

        if modified:
            result.fixed_code = "\n".join(lines)
            result.fix_count = len(result.fixes_applied)

        return result

    def _fix_unterminated_docstrings(self, lines: list[str]) -> int:
        """
        Fix unterminated docstrings by ensuring balanced triple quotes.

        Modifies lines in-place.

        Args:
            lines: Code lines to fix

        Returns:
            Number of fixes applied
        """
        fixes = 0
        in_docstring = False
        docstring_indent = 0
        _docstring_start = -1
        insertions = []  # Track insertions to apply after iteration

        # Safety limit to prevent infinite loops (typical files have < 10k lines)
        max_iterations = max(len(lines) * 2, 10000)
        iteration_count = 0

        i = 0
        while i < len(lines) and iteration_count < max_iterations:
            iteration_count += 1
            line = lines[i]
            stripped = line.strip()

            # Detect docstring start/end
            if '"""' in stripped or "'''" in stripped:
                # Use whichever quote style is in the line
                quote_style = '"""' if '"""' in stripped else "'''"
                quote_count = stripped.count(quote_style)

                if quote_count == 2:
                    # Single-line docstring - both start and end on same line
                    in_docstring = False
                    _docstring_start = -1
                elif quote_count == 1:
                    # Toggle docstring state
                    if not in_docstring:
                        # Starting a new docstring
                        in_docstring = True
                        docstring_indent = len(line) - len(line.lstrip())
                        _docstring_start = i

                        # Look ahead to find the closing quotes
                        found_end = False
                        for j in range(i + 1, len(lines)):
                            if quote_style in lines[j]:
                                # Found closing quotes
                                found_end = True
                                in_docstring = False
                                _docstring_start = -1
                                i = j  # Skip to after the closing quotes
                                break

                        # If no closing quotes found, check for dedent
                        if not found_end:
                            # Look for dedent or end of file
                            for j in range(i + 1, len(lines)):
                                next_line = lines[j]
                                next_indent = len(next_line) - len(next_line.lstrip())
                                # Check for dedent or method/class definition
                                if next_line.strip() and (
                                    next_indent <= docstring_indent
                                    or next_line.strip().startswith("def ")
                                    or next_line.strip().startswith("class ")
                                ):
                                    # Insert closing quotes before this line
                                    insertions.append(
                                        (j, " " * docstring_indent + quote_style)
                                    )
                                    fixes += 1
                                    in_docstring = False
                                    _docstring_start = -1
                                    break
                            else:
                                # Reached end of file
                                if in_docstring:
                                    insertions.append(
                                        (
                                            len(lines),
                                            " " * docstring_indent + quote_style,
                                        )
                                    )
                                    fixes += 1
                                    in_docstring = False
                                    _docstring_start = -1
                    else:
                        # Closing an existing docstring
                        in_docstring = False
                        _docstring_start = -1

            i += 1

        # Warn if we hit the iteration limit
        if iteration_count >= max_iterations:
            self.logger.warning(
                f"_fix_unterminated_docstrings hit iteration limit ({max_iterations}) "
                f"processing {len(lines)} lines. Possible infinite loop prevented."
            )

        # Apply insertions in reverse order to maintain indices
        for pos, text in reversed(insertions):
            lines.insert(pos, text)

        return fixes

    def _detect_node_type(self, code: str, file_path: Path | None = None) -> str | None:
        """
        Detect ONEX node type from code or file path.

        Args:
            code: Source code
            file_path: Optional file path

        Returns:
            Node type: 'effect', 'compute', 'reducer', 'orchestrator', or None
        """
        # Check file path first
        if file_path:
            path_str = str(file_path).lower()
            for node_type in ["effect", "compute", "reducer", "orchestrator"]:
                if node_type in path_str:
                    return node_type

        # Check code patterns
        for node_type in ["effect", "compute", "reducer", "orchestrator"]:
            pattern = f"class Node\\w+{node_type.capitalize()}"
            if re.search(pattern, code, re.IGNORECASE):
                return node_type

        return None

    def _get_missing_imports(self, code: str, node_type: str) -> list[str]:
        """
        Get list of missing required imports for node type.

        Args:
            code: Source code
            node_type: ONEX node type

        Returns:
            List of import statements to add
        """
        required_imports = self.NODE_TYPE_IMPORTS.get(node_type, [])
        missing = []

        for imp in required_imports:
            # Check if the full import statement already exists
            # This is more accurate than checking just the imported name
            if imp.strip() not in code:
                missing.append(imp)

        return missing

    def _find_import_insertion_point(self, lines: list[str]) -> int:
        """
        Find the correct position to insert imports.

        Inserts after shebang and module docstring.

        Args:
            lines: Code lines

        Returns:
            Line index for insertion
        """
        pos = 0

        # Skip shebang
        if lines and lines[0].startswith("#!"):
            pos = 1

        # Skip module docstring
        if pos < len(lines) and '"""' in lines[pos]:
            # Check for single-line docstring
            if lines[pos].count('"""') == 2:
                pos = pos + 1
            else:
                # Multi-line docstring - find end
                for i in range(pos + 1, min(pos + 50, len(lines))):
                    if '"""' in lines[i]:
                        pos = i + 1
                        break

        # Skip blank lines after docstring (with safety limit)
        max_blank_lines = 100  # Prevent infinite loop on malformed files
        blank_count = 0
        while (
            pos < len(lines)
            and not lines[pos].strip()
            and blank_count < max_blank_lines
        ):
            pos += 1
            blank_count += 1

        return pos

    def _fix_common_import_issues(self, lines: list[str]) -> int:
        """
        Fix common import issues.

        Modifies lines in-place.

        Args:
            lines: Code lines

        Returns:
            Number of fixes applied
        """
        fixes = 0

        for i, line in enumerate(lines):
            # Fix relative imports that should be absolute
            if "from .." in line and "omnibase_core" not in line:
                # Suggest absolute import
                self.logger.debug(f"Potential relative import issue at line {i + 1}")

            # Fix missing commas in multi-line imports
            if line.strip().startswith("from") and "import" in line:
                # Check if next line continues import
                if i + 1 < len(lines):
                    next_line = lines[i + 1].strip()
                    if (
                        next_line
                        and not next_line.startswith("from")
                        and not next_line.startswith("import")
                        and next_line[0].isupper()
                    ):
                        # Likely missing comma
                        if not line.rstrip().endswith(
                            ","
                        ) and not line.rstrip().endswith("("):
                            # This might be intentional, so just log
                            self.logger.debug(
                                f"Possible missing comma in import at line {i + 1}"
                            )

        return fixes


# Convenience function for pipeline integration
def apply_automatic_fixes(code: str, file_path: Path | None = None) -> FixResult:
    """
    Apply all automatic warning fixes to code.

    Convenience function for pipeline integration.

    Args:
        code: Source code to fix
        file_path: Optional file path for context

    Returns:
        FixResult with fixed code
    """
    fixer = WarningFixer()
    return fixer.fix_all_warnings(code, file_path)
