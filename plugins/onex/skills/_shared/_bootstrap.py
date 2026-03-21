# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Centralized path bootstrapping for friction system modules.

All consumers (node shell, adapter, tests, hook inline Python) should call
bootstrap_paths() once instead of manually manipulating sys.path.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SHARED_DIR = str(Path(__file__).resolve().parent)
_HOOKS_LIB = str(Path(__file__).resolve().parent.parent.parent / "hooks" / "lib")


def bootstrap_paths() -> None:
    """Add _shared and hooks/lib to sys.path if not already present."""
    for p in [_SHARED_DIR, _HOOKS_LIB]:
        if p not in sys.path:
            sys.path.insert(0, p)
