# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""AST-based test verifying no direct HandlerSlackWebhook imports in hooks/lib/.

This test scans all Python files in plugins/onex/hooks/lib/ using the AST module
to ensure that no file contains a direct `from omnibase_infra.handlers.handler_slack_webhook
import HandlerSlackWebhook` statement. The correct pattern is to use
`importlib.import_module` for lazy resolution, typed against `SlackHandlerProtocol`.

Related Tickets:
    - OMN-2814: [GAP-001] Replace direct HandlerSlackWebhook import with lazy resolution

.. versionadded:: 0.3.1
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

# All tests in this module are unit tests
pytestmark = pytest.mark.unit

# Directory containing the hooks library modules
_HOOKS_LIB_DIR = (
    Path(__file__).parent.parent.parent.parent.parent
    / "plugins"
    / "onex"
    / "hooks"
    / "lib"
)

# The forbidden direct import pattern
_FORBIDDEN_MODULE = "omnibase_infra.handlers.handler_slack_webhook"
_FORBIDDEN_NAME = "HandlerSlackWebhook"


def _find_direct_handler_imports(file_path: Path) -> list[tuple[int, str]]:
    """Scan a Python file's AST for direct HandlerSlackWebhook imports.

    Returns a list of (line_number, import_statement) tuples for violations.
    """
    source = file_path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(file_path))
    except SyntaxError:
        return []

    violations: list[tuple[int, str]] = []

    for node in ast.walk(tree):
        # Check `from omnibase_infra.handlers.handler_slack_webhook import HandlerSlackWebhook`
        if isinstance(node, ast.ImportFrom):
            if node.module and node.module == _FORBIDDEN_MODULE:
                imported_names = [alias.name for alias in node.names]
                if _FORBIDDEN_NAME in imported_names:
                    stmt = f"from {node.module} import {', '.join(imported_names)}"
                    violations.append((node.lineno, stmt))

        # Check `import omnibase_infra.handlers.handler_slack_webhook`
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == _FORBIDDEN_MODULE:
                    violations.append((node.lineno, f"import {alias.name}"))

    return violations


class TestNoDirectHandlerImports:
    """Verify no Python file in hooks/lib/ directly imports HandlerSlackWebhook."""

    def test_hooks_lib_dir_exists(self) -> None:
        """Sanity check: the hooks/lib directory exists."""
        assert _HOOKS_LIB_DIR.is_dir(), (
            f"Expected hooks/lib directory at {_HOOKS_LIB_DIR}"
        )

    def test_no_direct_handler_slack_webhook_imports(self) -> None:
        """No file in hooks/lib/ should directly import HandlerSlackWebhook.

        The correct pattern is:
            import importlib
            mod = importlib.import_module("omnibase_infra.handlers.handler_slack_webhook")
            handler_cls = getattr(mod, "HandlerSlackWebhook")

        This ensures the handler is lazily resolved and typed against
        SlackHandlerProtocol, not the concrete class.
        """
        python_files = sorted(_HOOKS_LIB_DIR.glob("*.py"))
        assert len(python_files) > 0, "No Python files found in hooks/lib/"

        all_violations: list[str] = []

        for py_file in python_files:
            violations = _find_direct_handler_imports(py_file)
            for lineno, stmt in violations:
                all_violations.append(f"  {py_file.name}:{lineno}: {stmt}")

        if all_violations:
            violation_report = "\n".join(all_violations)
            pytest.fail(
                f"Found direct HandlerSlackWebhook imports in hooks/lib/.\n"
                f"Use importlib.import_module() for lazy resolution instead:\n"
                f"\n{violation_report}\n"
                f"\nCorrect pattern:\n"
                f"  import importlib\n"
                f'  mod = importlib.import_module("{_FORBIDDEN_MODULE}")\n'
                f'  handler_cls = getattr(mod, "{_FORBIDDEN_NAME}")\n'
            )

    def test_scans_all_python_files(self) -> None:
        """Verify the test actually scans a reasonable number of files.

        This prevents a false pass if the glob pattern breaks or the
        directory is empty.
        """
        python_files = list(_HOOKS_LIB_DIR.glob("*.py"))
        # hooks/lib/ should contain at least pipeline_slack_notifier.py
        # and blocked_notifier.py
        assert len(python_files) >= 2, (
            f"Expected at least 2 Python files in hooks/lib/, found {len(python_files)}"
        )

    def test_detects_from_import_pattern(self) -> None:
        """Verify the scanner detects the 'from ... import' pattern."""
        # Create a synthetic source with the forbidden import
        source = (
            "from omnibase_infra.handlers.handler_slack_webhook "
            "import HandlerSlackWebhook\n"
        )
        tree = ast.parse(source)

        violations: list[tuple[int, str]] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and node.module == _FORBIDDEN_MODULE:
                    imported_names = [alias.name for alias in node.names]
                    if _FORBIDDEN_NAME in imported_names:
                        violations.append((node.lineno, "detected"))

        assert len(violations) == 1, "Scanner should detect from-import pattern"

    def test_ignores_importlib_usage(self) -> None:
        """Verify the scanner does NOT flag importlib.import_module usage."""
        source = (
            "import importlib\n"
            "mod = importlib.import_module("
            '"omnibase_infra.handlers.handler_slack_webhook")\n'
            'handler_cls = getattr(mod, "HandlerSlackWebhook")\n'
        )
        tree = ast.parse(source)

        violations: list[tuple[int, str]] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and node.module == _FORBIDDEN_MODULE:
                    imported_names = [alias.name for alias in node.names]
                    if _FORBIDDEN_NAME in imported_names:
                        violations.append((node.lineno, "detected"))
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == _FORBIDDEN_MODULE:
                        violations.append((node.lineno, "detected"))

        assert len(violations) == 0, (
            "Scanner should NOT flag importlib.import_module usage"
        )
