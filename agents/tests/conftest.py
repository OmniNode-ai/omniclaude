#!/usr/bin/env python3
"""
Pytest Configuration File (conftest.py)

NOTE: This conftest.py uses sys.path manipulation for pytest test discovery and imports.
This is a standard pytest pattern when tests need to import from parent directories
and when test fixtures/mocks need to be accessible.

BETTER APPROACH: Instead of sys.path manipulation in conftest.py, consider:
1. Installing the package in development mode: `pip install -e .`
2. Configuring PYTHONPATH in pytest.ini or pyproject.toml:
   [tool.pytest.ini_options]
   pythonpath = ["."]
3. Using proper package structure with __init__.py files

However, for standalone test directories, conftest.py sys.path manipulation is acceptable
and is a common pytest pattern. This runs once during test collection and is isolated
to the test execution environment.
"""

import sys
from pathlib import Path

# Ensure project root is on sys.path for test imports
# This allows tests to import from the agents package
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Add mocks directory for omnibase_core stub
# This allows tests to use mock implementations of external dependencies
MOCKS_DIR = Path(__file__).parent / "mocks"
if str(MOCKS_DIR) not in sys.path:
    sys.path.insert(0, str(MOCKS_DIR))
