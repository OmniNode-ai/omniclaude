# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""OmniClaude library -- lazy subpackage loading (PEP 562).

Subpackages (clients, config, core, errors, models, utils) are loaded on
first access, not at import time.  This prevents the circular import chain
that occurs when config -> aggregators -> hooks -> lib.utils -> config.
"""

from __future__ import annotations

import importlib
from typing import Any

_SUBPACKAGES = frozenset({"clients", "config", "core", "errors", "models", "utils"})

__all__ = [
    "clients",
    "config",
    "core",
    "errors",
    "models",
    "utils",
]


def __getattr__(name: str) -> Any:
    if name in _SUBPACKAGES:
        mod = importlib.import_module(f"omniclaude.lib.{name}")
        globals()[name] = mod  # cache so __getattr__ is only called once
        return mod
    raise AttributeError(f"module 'omniclaude.lib' has no attribute {name!r}")
