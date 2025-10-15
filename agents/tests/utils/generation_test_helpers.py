#!/usr/bin/env python3
"""
Test Utilities for Phase 4 Code Generation

Helper functions for parsing, validating, and comparing generated code.
"""

import ast
import re
import yaml
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path
from difflib import unified_diff


# ============================================================================
# YAML PARSING AND VALIDATION
# ============================================================================

def parse_generated_yaml(yaml_content: str) -> Dict[str, Any]:
    """
    Parse and validate generated YAML content.

    Args:
        yaml_content: YAML string to parse

    Returns:
        Parsed YAML as dictionary

    Raises:
        ValueError: If YAML is invalid
    """
    try:
        parsed = yaml.safe_load(yaml_content)
        if parsed is None:
            raise ValueError("YAML content is empty")
        return parsed
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML: {str(e)}")


def validate_contract_schema(contract: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    Validate contract YAML against expected schema.

    Args:
        contract: Parsed contract dictionary

    Returns:
        Tuple of (is_valid, list_of_errors)
    """
    errors = []

    # Required top-level fields
    required_fields = ["version", "node_type", "domain", "microservice_name", "capabilities"]
    for field in required_fields:
        if field not in contract:
            errors.append(f"Missing required field: {field}")

    # Validate version format
    if "version" in contract:
        if not re.match(r'^\d+\.\d+\.\d+$', contract["version"]):
            errors.append(f"Invalid version format: {contract['version']}")

    # Validate node_type
    if "node_type" in contract:
        valid_types = ["EFFECT", "COMPUTE", "REDUCER", "ORCHESTRATOR"]
        if contract["node_type"] not in valid_types:
            errors.append(f"Invalid node_type: {contract['node_type']}")

    # Validate capabilities
    if "capabilities" in contract:
        if not isinstance(contract["capabilities"], list):
            errors.append("capabilities must be a list")
        else:
            for i, cap in enumerate(contract["capabilities"]):
                if not isinstance(cap, dict):
                    errors.append(f"Capability {i} must be a dictionary")
                    continue
                if "name" not in cap:
                    errors.append(f"Capability {i} missing 'name' field")
                if "description" not in cap:
                    errors.append(f"Capability {i} missing 'description' field")

    # Validate mixins (if present)
    if "mixins" in contract:
        if not isinstance(contract["mixins"], list):
            errors.append("mixins must be a list")
        else:
            for mixin in contract["mixins"]:
                if not mixin.startswith("Mixin"):
                    errors.append(f"Invalid mixin name: {mixin} (should start with 'Mixin')")

    return len(errors) == 0, errors


# ============================================================================
# PYTHON CODE PARSING AND VALIDATION
# ============================================================================

def parse_generated_python(python_code: str) -> Tuple[ast.Module, List[str]]:
    """
    Parse and validate generated Python code using AST.

    Args:
        python_code: Python code string

    Returns:
        Tuple of (AST module, list_of_syntax_errors)
    """
    errors = []
    try:
        tree = ast.parse(python_code)
        return tree, errors
    except SyntaxError as e:
        errors.append(f"Syntax error at line {e.lineno}: {e.msg}")
        return None, errors


def check_type_annotations(tree: ast.Module) -> Tuple[bool, List[str]]:
    """
    Check that all functions have proper type annotations.

    Args:
        tree: AST module to check

    Returns:
        Tuple of (all_annotated, list_of_violations)
    """
    violations = []

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            # Check return annotation
            if node.returns is None and node.name != "__init__":
                violations.append(f"Function '{node.name}' missing return type annotation")

            # Check parameter annotations
            for arg in node.args.args:
                if arg.annotation is None and arg.arg != "self" and arg.arg != "cls":
                    violations.append(
                        f"Function '{node.name}' parameter '{arg.arg}' missing type annotation"
                    )

    return len(violations) == 0, violations


def check_for_any_types(python_code: str) -> Tuple[bool, List[str]]:
    """
    Check for usage of 'Any' type (ONEX violation).

    Args:
        python_code: Python code string

    Returns:
        Tuple of (is_valid, list_of_violations)
    """
    violations = []

    # Parse AST
    tree, parse_errors = parse_generated_python(python_code)
    if tree is None:
        return False, parse_errors

    # Check for Any in annotations
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == "Any":
            # Check if it's used in type annotation context
            parent = getattr(node, 'parent', None)
            if isinstance(parent, (ast.arg, ast.AnnAssign, ast.FunctionDef)):
                violations.append(f"Usage of 'Any' type detected (ONEX violation)")

    # Also check with regex for Dict[str, Any] patterns
    any_patterns = [
        r'\bAny\b(?!\w)',  # Standalone Any
        r'Dict\[.*,\s*Any\]',  # Dict with Any value
        r'List\[Any\]',  # List of Any
        r'Optional\[Any\]',  # Optional Any
    ]

    for pattern in any_patterns:
        matches = re.finditer(pattern, python_code)
        for match in matches:
            line_num = python_code[:match.start()].count('\n') + 1
            violations.append(f"Any type usage at line {line_num}: {match.group()}")

    return len(violations) == 0, violations


def extract_class_definitions(tree: ast.Module) -> List[Dict[str, Any]]:
    """
    Extract all class definitions from AST.

    Args:
        tree: AST module

    Returns:
        List of class definition dictionaries
    """
    classes = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            class_info = {
                "name": node.name,
                "bases": [base.id if isinstance(base, ast.Name) else str(base) for base in node.bases],
                "methods": [],
                "attributes": []
            }

            # Extract methods
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    class_info["methods"].append(item.name)
                elif isinstance(item, ast.AnnAssign):
                    if isinstance(item.target, ast.Name):
                        class_info["attributes"].append(item.target.id)

            classes.append(class_info)

    return classes


def extract_imports(tree: ast.Module) -> List[str]:
    """
    Extract all import statements from AST.

    Args:
        tree: AST module

    Returns:
        List of import strings
    """
    imports = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                imports.append(f"{module}.{alias.name}")

    return imports


# ============================================================================
# ONEX NAMING VALIDATION
# ============================================================================

def validate_onex_naming(filename: str) -> Tuple[bool, Optional[str]]:
    """
    Validate filename against ONEX naming conventions.

    Args:
        filename: Filename to validate

    Returns:
        Tuple of (is_valid, error_message)
    """
    # Node files: node_<name>_<type>.py
    node_pattern = r'^node_[a-z][a-z0-9_]*_(effect|compute|reducer|orchestrator)\.py$'
    if filename.startswith("node_"):
        if not re.match(node_pattern, filename):
            return False, f"Node file must match pattern: node_<name>_<type>.py (lowercase, underscores)"
        return True, None

    # Model files: model_<name>.py
    model_pattern = r'^model_[a-z][a-z0-9_]*\.py$'
    if filename.startswith("model_"):
        if not re.match(model_pattern, filename):
            return False, f"Model file must match pattern: model_<name>.py (lowercase, underscores)"
        return True, None

    # Enum files: enum_<name>.py
    enum_pattern = r'^enum_[a-z][a-z0-9_]*\.py$'
    if filename.startswith("enum_"):
        if not re.match(enum_pattern, filename):
            return False, f"Enum file must match pattern: enum_<name>.py (lowercase, underscores)"
        return True, None

    # Contract files: contract_<name>.yaml
    contract_pattern = r'^contract_[a-z][a-z0-9_]*\.yaml$'
    if filename.startswith("contract_"):
        if not re.match(contract_pattern, filename):
            return False, f"Contract file must match pattern: contract_<name>.yaml (lowercase, underscores)"
        return True, None

    return False, f"Unknown file type: {filename}"


def validate_class_naming(class_name: str, file_type: str) -> Tuple[bool, Optional[str]]:
    """
    Validate class name against ONEX conventions.

    Args:
        class_name: Class name to validate
        file_type: Type of file (node, model, enum)

    Returns:
        Tuple of (is_valid, error_message)
    """
    if file_type == "node":
        # Node classes: Node<Domain><Name><Type>
        if not re.match(r'^Node[A-Z][a-zA-Z]*(Effect|Compute|Reducer|Orchestrator)$', class_name):
            return False, "Node class must match: Node<Domain><Name><Type> (PascalCase)"
        return True, None

    elif file_type == "model":
        # Model classes: Model<Name>
        if not re.match(r'^Model[A-Z][a-zA-Z]*$', class_name):
            return False, "Model class must match: Model<Name> (PascalCase)"
        return True, None

    elif file_type == "enum":
        # Enum classes: Enum<Name>
        if not re.match(r'^Enum[A-Z][a-zA-Z]*$', class_name):
            return False, "Enum class must match: Enum<Name> (PascalCase)"
        return True, None

    return False, f"Unknown file type: {file_type}"


# ============================================================================
# CODE COMPARISON
# ============================================================================

def compare_generated_code(expected: str, actual: str, context_lines: int = 3) -> Optional[str]:
    """
    Compare expected and actual generated code.

    Args:
        expected: Expected code
        actual: Actual generated code
        context_lines: Number of context lines in diff

    Returns:
        Diff string if different, None if identical
    """
    expected_lines = expected.splitlines(keepends=True)
    actual_lines = actual.splitlines(keepends=True)

    diff = list(unified_diff(
        expected_lines,
        actual_lines,
        fromfile='expected',
        tofile='actual',
        lineterm='',
        n=context_lines
    ))

    if not diff:
        return None

    return ''.join(diff)


def normalize_whitespace(code: str) -> str:
    """
    Normalize whitespace for comparison.

    Args:
        code: Code string

    Returns:
        Normalized code
    """
    # Remove trailing whitespace
    lines = [line.rstrip() for line in code.splitlines()]
    # Remove multiple blank lines
    normalized = []
    prev_blank = False
    for line in lines:
        is_blank = len(line.strip()) == 0
        if not (is_blank and prev_blank):
            normalized.append(line)
        prev_blank = is_blank
    return '\n'.join(normalized)


# ============================================================================
# ENUM VALIDATION
# ============================================================================

def validate_enum_serialization(tree: ast.Module) -> Tuple[bool, List[str]]:
    """
    Validate that enums have proper JSON serialization support.

    Args:
        tree: AST module

    Returns:
        Tuple of (is_valid, list_of_violations)
    """
    violations = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            # Check if it's an Enum class
            is_enum = any(
                (isinstance(base, ast.Name) and base.id == "Enum") or
                (isinstance(base, ast.Attribute) and base.attr == "Enum")
                for base in node.bases
            )

            if is_enum:
                # Check if it inherits from str for JSON serialization
                has_str_base = any(
                    isinstance(base, ast.Name) and base.id == "str"
                    for base in node.bases
                )

                if not has_str_base:
                    violations.append(
                        f"Enum class '{node.name}' should inherit from str for JSON serialization"
                    )

                # Check for __str__ method
                has_str_method = any(
                    isinstance(item, ast.FunctionDef) and item.name == "__str__"
                    for item in node.body
                )

                if not has_str_method:
                    violations.append(
                        f"Enum class '{node.name}' should implement __str__ method"
                    )

    return len(violations) == 0, violations


# ============================================================================
# CONTRACT VALIDATION HELPERS
# ============================================================================

def validate_mixin_compatibility(mixins: List[str]) -> Tuple[bool, List[str]]:
    """
    Validate that mixins are compatible with each other.

    Args:
        mixins: List of mixin names

    Returns:
        Tuple of (is_compatible, list_of_conflicts)
    """
    # Known incompatibilities
    incompatibilities = {
        "MixinCaching": ["MixinNoCaching"],
        "MixinRetry": ["MixinNoRetry"],
    }

    conflicts = []
    for mixin in mixins:
        if mixin in incompatibilities:
            for incompatible in incompatibilities[mixin]:
                if incompatible in mixins:
                    conflicts.append(f"{mixin} is incompatible with {incompatible}")

    return len(conflicts) == 0, conflicts


# ============================================================================
# PERFORMANCE HELPERS
# ============================================================================

def estimate_code_complexity(tree: ast.Module) -> Dict[str, int]:
    """
    Estimate code complexity metrics.

    Args:
        tree: AST module

    Returns:
        Dictionary of complexity metrics
    """
    metrics = {
        "num_classes": 0,
        "num_functions": 0,
        "num_lines": 0,
        "max_nesting_depth": 0,
        "num_imports": 0
    }

    def get_nesting_depth(node, depth=0):
        max_depth = depth
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.If, ast.For, ast.While, ast.With, ast.Try)):
                child_depth = get_nesting_depth(child, depth + 1)
                max_depth = max(max_depth, child_depth)
        return max_depth

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            metrics["num_classes"] += 1
        elif isinstance(node, ast.FunctionDef):
            metrics["num_functions"] += 1
            depth = get_nesting_depth(node)
            metrics["max_nesting_depth"] = max(metrics["max_nesting_depth"], depth)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            metrics["num_imports"] += 1

    return metrics


# ============================================================================
# EXPORT ALL UTILITIES
# ============================================================================

__all__ = [
    # YAML utilities
    "parse_generated_yaml",
    "validate_contract_schema",

    # Python utilities
    "parse_generated_python",
    "check_type_annotations",
    "check_for_any_types",
    "extract_class_definitions",
    "extract_imports",

    # ONEX validation
    "validate_onex_naming",
    "validate_class_naming",

    # Code comparison
    "compare_generated_code",
    "normalize_whitespace",

    # Enum validation
    "validate_enum_serialization",

    # Contract validation
    "validate_mixin_compatibility",

    # Performance
    "estimate_code_complexity",
]
