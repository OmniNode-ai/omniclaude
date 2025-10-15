#!/usr/bin/env python3
"""
Static Validation for Business Logic Generator

Validates the code structure without executing it.
"""

import ast
import re
import sys
from pathlib import Path

def validate_business_logic_generator():
    """Validate the business logic generator file"""

    file_path = Path(__file__).parent.parent / "lib" / "business_logic_generator.py"

    print("=" * 80)
    print("VALIDATING BUSINESS LOGIC GENERATOR")
    print("=" * 80)

    with open(file_path, 'r') as f:
        code = f.read()

    # Test 1: Valid Python syntax
    print("\n1. Checking Python syntax...")
    try:
        tree = ast.parse(code)
        print("   ✓ Valid Python syntax")
    except SyntaxError as e:
        print(f"   ✗ Syntax error: {e}")
        return False

    # Test 2: Required classes
    print("\n2. Checking required classes...")
    classes = [node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]

    required_classes = ['BusinessLogicGenerator', 'CodegenConfig']
    for cls in required_classes:
        if cls in classes:
            print(f"   ✓ Found class: {cls}")
        else:
            print(f"   ✗ Missing class: {cls}")
            return False

    # Test 3: Required methods
    print("\n3. Checking required methods...")

    # Find BusinessLogicGenerator class
    blg_class = None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == 'BusinessLogicGenerator':
            blg_class = node
            break

    if not blg_class:
        print("   ✗ BusinessLogicGenerator class not found")
        return False

    methods = [node.name for node in blg_class.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]

    required_methods = [
        '__init__',
        'generate_node_implementation',
        '_generate_class_definition',
        '_generate_init_method',
        '_generate_primary_method',
        '_generate_validation_method',
        '_generate_health_check',
        '_generate_mixin_methods',
        '_generate_capability_methods',
        '_detect_pattern_type',
        '_infer_method_logic_hints'
    ]

    for method in required_methods:
        if method in methods:
            print(f"   ✓ Found method: {method}")
        else:
            print(f"   ✗ Missing method: {method}")
            return False

    # Test 4: Node type mappings
    print("\n4. Checking node type mappings...")
    node_types = ['EFFECT', 'COMPUTE', 'REDUCER', 'ORCHESTRATOR']
    for node_type in node_types:
        if f'"{node_type}"' in code:
            print(f"   ✓ Found node type: {node_type}")
        else:
            print(f"   ✗ Missing node type: {node_type}")
            return False

    # Test 5: Pattern detection
    print("\n5. Checking pattern detection...")
    patterns = ['CRUD_CREATE', 'CRUD_READ', 'CRUD_UPDATE', 'CRUD_DELETE',
                'AGGREGATION', 'TRANSFORMATION', 'VALIDATION']
    for pattern in patterns:
        if pattern in code:
            print(f"   ✓ Found pattern: {pattern}")
        else:
            print(f"   ✗ Missing pattern: {pattern}")
            return False

    # Test 6: Type hints
    print("\n6. Checking type hints...")
    type_hints = ['Dict[str, Any]', 'Optional[UUID]', 'List[str]']
    found_hints = []
    for hint in type_hints:
        if hint in code:
            found_hints.append(hint)

    if found_hints:
        print(f"   ✓ Found type hints: {', '.join(found_hints)}")
    else:
        print("   ✗ No type hints found")
        return False

    # Test 7: Error handling
    print("\n7. Checking error handling...")
    if 'OnexError' in code:
        print("   ✓ Uses OnexError")
    else:
        print("   ✗ OnexError not used")
        return False

    # Test 8: Correlation tracking
    print("\n8. Checking correlation tracking...")
    if 'correlation_id' in code and 'UUID' in code:
        print("   ✓ Correlation ID tracking present")
    else:
        print("   ✗ Correlation ID tracking missing")
        return False

    # Test 9: Docstrings
    print("\n9. Checking docstrings...")
    docstring_count = 0
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.Module)):
            if ast.get_docstring(node):
                docstring_count += 1

    if docstring_count >= 10:
        print(f"   ✓ Found {docstring_count} docstrings")
    else:
        print(f"   ✗ Only {docstring_count} docstrings found (expected 10+)")
        return False

    # Test 10: File stats
    print("\n10. File statistics...")
    lines = code.split('\n')
    print(f"   ✓ Total lines: {len(lines)}")
    print(f"   ✓ Total characters: {len(code)}")
    print(f"   ✓ Total classes: {len(classes)}")
    print(f"   ✓ Total methods: {len(methods)}")

    return True


def main():
    """Run validation"""
    try:
        if validate_business_logic_generator():
            print("\n" + "=" * 80)
            print("✓ ALL VALIDATIONS PASSED")
            print("=" * 80)
            return 0
        else:
            print("\n" + "=" * 80)
            print("✗ VALIDATION FAILED")
            print("=" * 80)
            return 1
    except Exception as e:
        print(f"\n✗ Validation error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
