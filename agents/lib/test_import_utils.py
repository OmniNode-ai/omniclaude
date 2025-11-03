"""
Test Import Utils - Comprehensive Testing

Verifies that import_utils.py meets all success criteria:
1. Module compiles without errors
2. Function successfully imports from lib directory
3. Type hints are correct
4. Code follows ONEX patterns
5. Can be used as drop-in replacement for existing import blocks
"""

import inspect
import sys
from pathlib import Path


def test_module_compilation():
    """Test that the module compiles without errors."""
    print("=" * 70)
    print("TEST 1: Module Compilation")
    print("=" * 70)

    try:
        from import_utils import import_from_lib

        print("✓ Module imports successfully")
        print(f"✓ Function available: {import_from_lib.__name__}")
        return True
    except Exception as e:
        print(f"✗ Import failed: {e}")
        return False


def test_function_imports():
    """Test that function successfully imports from lib directory."""
    print("\n" + "=" * 70)
    print("TEST 2: Function Imports from Lib Directory")
    print("=" * 70)

    from import_utils import import_from_lib

    success_count = 0
    test_modules = [
        "intelligence_event_client",
        "intelligence_cache",
        "pattern_quality_scorer",
        "task_classifier",
    ]

    for module_name in test_modules:
        try:
            module = import_from_lib(module_name)
            print(f"✓ Successfully imported: {module_name}")
            print(f"  Module type: {type(module).__name__}")
            success_count += 1
        except Exception as e:
            print(f"✗ Failed to import {module_name}: {e}")

    print(f"\nResult: {success_count}/{len(test_modules)} modules imported")
    return success_count == len(test_modules)


def test_type_hints():
    """Test that type hints are correct."""
    print("\n" + "=" * 70)
    print("TEST 3: Type Hints")
    print("=" * 70)

    from import_utils import import_from_lib

    # Check function signature
    sig = inspect.signature(import_from_lib)
    print(f"✓ Function signature: {import_from_lib.__name__}{sig}")

    # Check annotations
    annotations = import_from_lib.__annotations__
    print(f"✓ Type annotations present: {bool(annotations)}")

    # Verify parameter types
    params = sig.parameters
    param_valid = True
    for param_name, param in params.items():
        print(f"  - Parameter '{param_name}': {param.annotation}")
        # Check that annotation is str (either as type or as string)
        if param_name == "module_name":
            # Annotation can be either the type object str or the string 'str'
            if param.annotation not in (str, "str"):
                print(f"✗ Expected str, got {param.annotation}")
                param_valid = False

    if not param_valid:
        return False

    # Verify return type
    print(f"  - Return type: {sig.return_annotation}")
    if sig.return_annotation not in ["Any", "Any"]:
        # Check if it's the actual Any type
        from typing import Any

        if sig.return_annotation != Any:
            print(f"✗ Expected Any, got {sig.return_annotation}")
            return False

    print("✓ All type hints are correct")
    return True


def test_onex_patterns():
    """Test that code follows ONEX patterns."""
    print("\n" + "=" * 70)
    print("TEST 4: ONEX Pattern Compliance")
    print("=" * 70)

    from import_utils import import_from_lib

    # Check docstring
    docstring_length = len(import_from_lib.__doc__) if import_from_lib.__doc__ else 0
    print(f"✓ Docstring present: {docstring_length > 0}")
    print(f"  Length: {docstring_length} characters")

    if docstring_length < 100:
        print("✗ Docstring too short (should be comprehensive)")
        return False

    # Check module docstring
    import import_utils

    module_docstring_length = len(import_utils.__doc__) if import_utils.__doc__ else 0
    print(f"✓ Module docstring present: {module_docstring_length > 0}")
    print(f"  Length: {module_docstring_length} characters")

    if module_docstring_length < 100:
        print("✗ Module docstring too short")
        return False

    # Check for ONEX compliance markers
    full_doc = import_utils.__doc__ + import_from_lib.__doc__
    onex_markers = ["ONEX", "Node Type", "Contract", "Architecture"]
    found_markers = [marker for marker in onex_markers if marker in full_doc]
    print(f"✓ ONEX markers found: {', '.join(found_markers)}")

    if len(found_markers) < 2:
        print("✗ Insufficient ONEX compliance documentation")
        return False

    print("✓ Follows ONEX patterns")
    return True


def test_drop_in_replacement():
    """Test that it can be used as drop-in replacement."""
    print("\n" + "=" * 70)
    print("TEST 5: Drop-in Replacement Capability")
    print("=" * 70)

    # Old pattern (simulated)
    print("Old pattern (try/except):")
    try:
        from intelligence_event_client import IntelligenceEventClient

        print("  ✓ Import via try/except works")
    except ImportError:
        lib_path = Path(__file__).parent
        if str(lib_path) not in sys.path:
            sys.path.insert(0, str(lib_path))
        from intelligence_event_client import IntelligenceEventClient

        print("  ✓ Import via fallback works")

    # New pattern
    print("\nNew pattern (import_from_lib):")
    from import_utils import import_from_lib

    intelligence_event_client = import_from_lib("intelligence_event_client")
    IntelligenceEventClientNew = intelligence_event_client.IntelligenceEventClient
    print("  ✓ Import via import_from_lib works")

    # Verify both methods get the same class
    if IntelligenceEventClient is IntelligenceEventClientNew:
        print("✓ Both methods import the same class")
    else:
        print("✗ Classes are different (unexpected)")
        return False

    # Test multiple imports
    print("\nMultiple imports:")
    cache_module = import_from_lib("intelligence_cache")
    scorer_module = import_from_lib("pattern_quality_scorer")
    print("  ✓ Can import multiple modules")

    # Test class access
    IntelligenceCache = cache_module.IntelligenceCache
    PatternQualityScorer = scorer_module.PatternQualityScorer
    print("  ✓ Can access classes from imported modules")
    print(f"    - {IntelligenceCache.__name__}")
    print(f"    - {PatternQualityScorer.__name__}")

    print("✓ Can be used as drop-in replacement")
    return True


def test_error_handling():
    """Test proper error handling."""
    print("\n" + "=" * 70)
    print("TEST 6: Error Handling")
    print("=" * 70)

    from import_utils import import_from_lib

    # Test non-existent module
    try:
        import_from_lib("nonexistent_module_xyz_123")
        print("✗ Should have raised ImportError for non-existent module")
        return False
    except ImportError as e:
        print(f"✓ Correctly raises ImportError: {str(e)[:80]}")

    # Test that error message is helpful
    try:
        import_from_lib("this_module_does_not_exist_at_all")
        print("✗ Should have raised ImportError")
        return False
    except ImportError as e:
        error_msg = str(e)
        if "this_module_does_not_exist_at_all" in error_msg:
            print(f"✓ Error message includes module name: {error_msg[:80]}")
        else:
            print(f"✗ Error message not helpful: {error_msg}")
            return False

    print("✓ Error handling is correct")
    return True


def run_all_tests():
    """Run all tests and report results."""
    print("\n" + "=" * 70)
    print("IMPORT UTILS - COMPREHENSIVE TEST SUITE")
    print("=" * 70)

    tests = [
        ("Module Compilation", test_module_compilation),
        ("Function Imports", test_function_imports),
        ("Type Hints", test_type_hints),
        ("ONEX Patterns", test_onex_patterns),
        ("Drop-in Replacement", test_drop_in_replacement),
        ("Error Handling", test_error_handling),
    ]

    results = []
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"\n✗ Test '{test_name}' raised exception: {e}")
            import traceback

            traceback.print_exc()
            results.append((test_name, False))

    # Summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for test_name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status}: {test_name}")

    print("\n" + "=" * 70)
    print(f"Results: {passed}/{total} tests passed")

    if passed == total:
        print("✓ ALL TESTS PASSED - import_utils.py meets all success criteria")
    else:
        print(f"✗ {total - passed} test(s) failed")

    print("=" * 70)

    return passed == total


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
