# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
import sys
from pathlib import Path

# Make aggregate_reviews importable as a module
_SKILL_DIR = Path(__file__).parents[3] / "plugins/onex/skills/hostile_reviewer/_lib"
if str(_SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(_SKILL_DIR))
