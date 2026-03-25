# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Hook lib package -- ensures repo root is on sys.path for subprocess invocation.

When hook lib scripts are run as subprocesses (e.g. by shell hooks), the
repo root may not be on sys.path, causing ``from plugins.onex.hooks.lib.X``
imports to fail with ModuleNotFoundError.  This __init__.py adds the repo
root to sys.path once on first import so that all intra-package absolute
imports resolve correctly.

See: OMN-6482 / F14
"""

import sys
from pathlib import Path

_REPO_ROOT = str(Path(__file__).resolve().parents[4])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
