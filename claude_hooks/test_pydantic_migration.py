#!/usr/bin/env python3
"""
Test script for Pydantic Settings migration in hooks.

Tests all 9 migrated hooks to ensure they:
1. Import without errors
2. Load Pydantic Settings correctly
3. Access configuration attributes
4. Have no legacy os.getenv() for configuration

Correlation ID: bbec08a3-ac7f-4900-877a-6ed0a3d443e8
"""

import importlib.util
import os
import re
import sys
from pathlib import Path
from typing import List, Tuple, TypedDict


# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# ANSI color codes
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
RESET = "\033[0m"

# Hooks to test
HOOKS_TO_TEST = [
    "lib/hook_event_logger.py",
    "lib/session_intelligence.py",
    "lib/archon_intelligence.py",
    "pattern_tracker.py",
    "lib/route_via_events_wrapper.py",
    "lib/agent_invoker.py",
    "lib/workflow_executor.py",
    "lib/hybrid_agent_selector.py",
    "quality_enforcer.py",
    "lib/quality_enforcer.py",
]


def print_header(text: str):
    """Print formatted header."""
    print(f"\n{BLUE}{'=' * 80}{RESET}")
    print(f"{BLUE}{text.center(80)}{RESET}")
    print(f"{BLUE}{'=' * 80}{RESET}\n")


def print_test(hook_name: str, status: str, message: str = ""):
    """Print test result."""
    status_color = GREEN if status == "PASS" else RED if status == "FAIL" else YELLOW
    status_text = f"[{status_color}{status}{RESET}]"
    print(f"{status_text} {hook_name}")
    if message:
        print(f"      {message}")


def check_import(hook_path: Path) -> Tuple[bool, str, object]:
    """
    Test if hook imports without errors.

    Returns:
        (success, error_message, module)
    """
    try:
        # Get module name from path
        module_name = hook_path.stem
        if "lib/" in str(hook_path):
            module_name = f"lib.{module_name}"

        # Import module
        spec = importlib.util.spec_from_file_location(module_name, hook_path)
        if spec is None or spec.loader is None:
            return False, "Failed to create module spec", None

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module

        # Redirect stderr to capture sys.exit() from hook imports
        import io

        old_stderr = sys.stderr
        sys.stderr = io.StringIO()

        try:
            spec.loader.exec_module(module)
        except SystemExit as e:
            # Hook called sys.exit() - likely due to missing dependencies
            stderr_content = sys.stderr.getvalue()
            return False, f"Import error (sys.exit): {stderr_content.strip()}", None
        finally:
            sys.stderr = old_stderr

        return True, "", module
    except Exception as e:
        return False, f"Import error: {str(e)}", None


def check_settings_usage(module: object) -> Tuple[bool, str]:
    """
    Check if module uses Pydantic Settings correctly.

    Returns:
        (success, message)
    """
    try:
        # Check if module has settings import
        if not hasattr(module, "settings"):
            return False, "Module does not import 'settings' from config"

        # Try to access a common setting
        settings = module.settings

        # Check some common attributes exist
        common_attrs = ["postgres_host", "kafka_bootstrap_servers"]
        for attr in common_attrs:
            if hasattr(settings, attr):
                return True, f"Successfully accessed settings.{attr}"

        return True, "Settings imported (no common attributes checked)"
    except Exception as e:
        return False, f"Settings access error: {str(e)}"


def check_legacy_getenv(hook_path: Path) -> Tuple[bool, List[str]]:
    """
    Check for legacy os.getenv() usage for configuration.

    Returns:
        (is_clean, list_of_issues)
    """
    try:
        content = hook_path.read_text()

        # Configuration-related environment variables to check
        config_env_vars = [
            "POSTGRES_HOST",
            "POSTGRES_PORT",
            "POSTGRES_DATABASE",
            "POSTGRES_USER",
            "POSTGRES_PASSWORD",
            "KAFKA_BOOTSTRAP_SERVERS",
            "KAFKA_ENABLE_INTELLIGENCE",
            "QDRANT_HOST",
            "QDRANT_PORT",
            "QDRANT_URL",
            "ARCHON_INTELLIGENCE_URL",
            "ARCHON_SEARCH_URL",
            "ARCHON_BRIDGE_URL",
            "GEMINI_API_KEY",
            "ZAI_API_KEY",
            "OPENAI_API_KEY",
        ]

        issues = []

        # Check for os.getenv with configuration variables
        for var in config_env_vars:
            pattern = rf'os\.getenv\s*\(\s*["\']({var})["\']'
            matches = re.findall(pattern, content)
            if matches:
                issues.append(f"Found os.getenv('{var}')")

        return len(issues) == 0, issues
    except Exception as e:
        return False, [f"File read error: {str(e)}"]


class ImportResultDict(TypedDict):
    """Type for import test result."""

    success: bool
    message: str


class SettingsResultDict(TypedDict):
    """Type for settings test result."""

    success: bool
    message: str


class LegacyResultDict(TypedDict):
    """Type for legacy test result."""

    is_clean: bool
    issues: List[str]


# Using functional syntax because "import" is a Python reserved word
TestResultDict = TypedDict(
    "TestResultDict",
    {
        "hook": str,
        "import": ImportResultDict,
        "settings": SettingsResultDict,
        "legacy": LegacyResultDict,
        "overall_pass": bool,
    },
)


def run_comprehensive_test(hook_path: Path) -> TestResultDict:
    """
    Run comprehensive test on a single hook.

    Returns:
        TestResultDict with test results
    """
    import_result: ImportResultDict = {"success": False, "message": ""}
    settings_result: SettingsResultDict = {"success": False, "message": ""}
    legacy_result: LegacyResultDict = {"is_clean": False, "issues": []}

    results: TestResultDict = {
        "hook": hook_path.name,
        "import": import_result,
        "settings": settings_result,
        "legacy": legacy_result,
        "overall_pass": False,
    }

    # Test 1: Import
    import_success, import_msg, module = check_import(hook_path)
    import_result["success"] = import_success
    import_result["message"] = import_msg

    if not import_success:
        return results

    # Test 2: Settings usage
    settings_success, settings_msg = check_settings_usage(module)
    settings_result["success"] = settings_success
    settings_result["message"] = settings_msg

    # Test 3: Legacy os.getenv()
    is_clean, issues = check_legacy_getenv(hook_path)
    legacy_result["is_clean"] = is_clean
    legacy_result["issues"] = issues

    # Overall pass if all tests pass
    results["overall_pass"] = import_success and settings_success and is_clean

    return results


def main():
    """Main test execution."""
    print_header("Pydantic Settings Migration Test")
    print(f"Correlation ID: bbec08a3-ac7f-4900-877a-6ed0a3d443e8")
    print(f"Testing {len(HOOKS_TO_TEST)} migrated hooks\n")

    hooks_dir = Path(__file__).parent
    all_results = []

    # Test each hook
    for hook_file in HOOKS_TO_TEST:
        hook_path = hooks_dir / hook_file

        if not hook_path.exists():
            print_test(hook_file, "FAIL", f"File not found: {hook_path}")
            continue

        print(f"\n{YELLOW}Testing: {hook_file}{RESET}")
        results = run_comprehensive_test(hook_path)
        all_results.append(results)

        # Print import test
        if results["import"]["success"]:
            print_test("  Import", "PASS")
        else:
            print_test("  Import", "FAIL", results["import"]["message"])

        # Print settings test
        if results["settings"]["success"]:
            print_test("  Settings", "PASS", results["settings"]["message"])
        else:
            print_test("  Settings", "FAIL", results["settings"]["message"])

        # Print legacy check
        if results["legacy"]["is_clean"]:
            print_test("  Legacy Check", "PASS", "No legacy os.getenv() for config")
        else:
            print_test(
                "  Legacy Check",
                "WARN",
                f"Found {len(results['legacy']['issues'])} issue(s)",
            )
            for issue in results["legacy"]["issues"]:
                print(f"        - {issue}")

        # Overall status
        if results["overall_pass"]:
            print(f"  {GREEN}✓ All tests passed{RESET}")
        else:
            print(f"  {RED}✗ Some tests failed{RESET}")

    # Summary
    print_header("Test Summary")

    total = len(all_results)
    passed = sum(1 for r in all_results if r["overall_pass"])
    failed = total - passed

    import_passed = sum(1 for r in all_results if r["import"]["success"])
    settings_passed = sum(1 for r in all_results if r["settings"]["success"])
    legacy_clean = sum(1 for r in all_results if r["legacy"]["is_clean"])

    print(f"Total Hooks Tested: {total}")
    print(f"{GREEN}Passed: {passed}{RESET}")
    print(f"{RED}Failed: {failed}{RESET}\n")

    print(f"Import Test:       {import_passed}/{total} passed")
    print(f"Settings Test:     {settings_passed}/{total} passed")
    print(f"Legacy Check:      {legacy_clean}/{total} clean")

    # Success criteria
    print_header("Success Criteria")

    criteria_met = []

    # Criterion 1: All hooks import without errors
    if import_passed == total:
        criteria_met.append(True)
        print(f"{GREEN}✓{RESET} All {total} hooks import without errors")
    else:
        criteria_met.append(False)
        print(f"{RED}✗{RESET} {total - import_passed} hooks failed to import")

    # Criterion 2: Pydantic Settings loads correctly
    if settings_passed == total:
        criteria_met.append(True)
        print(f"{GREEN}✓{RESET} Pydantic Settings loads correctly in all hooks")
    else:
        criteria_met.append(False)
        print(f"{RED}✗{RESET} {total - settings_passed} hooks have settings issues")

    # Criterion 3: No configuration-related os.getenv()
    if legacy_clean == total:
        criteria_met.append(True)
        print(f"{GREEN}✓{RESET} No legacy os.getenv() for configuration")
    else:
        criteria_met.append(False)
        print(
            f"{YELLOW}⚠{RESET} {total - legacy_clean} hooks have legacy os.getenv() usage"
        )

    # Final result
    print()
    if all(criteria_met):
        print(f"{GREEN}{'=' * 80}{RESET}")
        print(f"{GREEN}SUCCESS: All criteria met! Migration complete.{RESET}")
        print(f"{GREEN}{'=' * 80}{RESET}")
        return 0
    else:
        print(f"{RED}{'=' * 80}{RESET}")
        print(f"{RED}FAILURE: Some criteria not met. Review failed tests above.{RESET}")
        print(f"{RED}{'=' * 80}{RESET}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
