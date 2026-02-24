# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Conftest for NL Intent-Plan-Ticket Compiler pipeline integration tests.

This conftest adds the other epic OMN-2357 worktree src directories to
sys.path so the integration tests can import all pipeline stages before
those PRs are merged.  In CI (after merge), the packages are installed
from the repo and no path manipulation is needed.
"""

from __future__ import annotations

import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Add sibling worktree src directories for pre-merge local testing
# ---------------------------------------------------------------------------
# Each OMN-2357 branch lives in a separate worktree.  Before those PRs are
# merged, we add their src/ directories here so the integration tests can
# import all pipeline stages.
#
# After all PRs are merged, these paths are redundant (packages installed
# from the repo root) but harmless.

_WORKTREES_ROOT = Path(
    __file__
).parent.parent.parent.parent.parent  # .claude/worktrees/OMN-2357/0b5e28f4/
_EPIC_ROOT = _WORKTREES_ROOT

_PIPELINE_WORKTREES = [
    "OMN-2501",
    "OMN-2502",
    "OMN-2503",
    "OMN-2504",
    "OMN-2505",
    "OMN-2506",
]

for _ticket in _PIPELINE_WORKTREES:
    _src = _EPIC_ROOT / _ticket / "src"
    if _src.exists():
        _src_str = str(_src)
        if _src_str not in sys.path:
            sys.path.insert(0, _src_str)
