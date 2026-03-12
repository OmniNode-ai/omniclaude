# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Root conftest.py — loaded by pytest before any test module is imported.

Ensures the repository root is on ``sys.path`` so that top-level packages
such as ``scripts`` are importable from test modules like
``tests/unit/scripts/test_generate_skill_node.py``.

This must live at the rootdir level (next to ``pyproject.toml``) so pytest
processes it during ``pytest_configure`` — before collection begins and
before any subdirectory conftest files are imported.
"""

from __future__ import annotations

import sys
from pathlib import Path


def pytest_configure(config: object) -> None:  # type: ignore[type-arg]
    """Insert the repo root into sys.path at the earliest possible hook.

    This runs before any test module or conftest in a subdirectory is
    imported, guaranteeing that ``from scripts.<module> import ...`` works
    regardless of the order in which pytest-split allocates test groups.
    """
    repo_root = str(Path(__file__).parent)
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
