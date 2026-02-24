# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""conftest.py for scripts unit tests.

Adds the repository root to sys.path so that ``from scripts.<module> import``
works in test modules.  This must run before any test module in this directory
is imported.
"""

import sys
from pathlib import Path

# Repo root: 4 levels up from this file (tests/unit/scripts/conftest.py)
_repo_root = str(Path(__file__).parent.parent.parent.parent)
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)
