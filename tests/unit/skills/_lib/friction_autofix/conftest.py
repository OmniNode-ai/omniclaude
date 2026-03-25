# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
import sys
from pathlib import Path

# Make friction_autofix importable as a top-level module name.
# This adds the _lib directory to sys.path so tests can do:
#   from friction_autofix.models import ModelFrictionClassification
_LIB_DIR = Path(__file__).parents[5] / "plugins/onex/skills/_lib"
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

# Also add _shared so tests can import friction_recorder, friction_aggregator etc.
_SHARED_DIR = Path(__file__).parents[5] / "plugins/onex/skills/_shared"
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))
