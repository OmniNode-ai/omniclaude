# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
import sys
from pathlib import Path

_SKILLS_ROOT = Path(__file__).parents[3] / "plugins" / "onex" / "skills"

# Make aggregate_reviews importable as a module
_SKILL_DIR = _SKILLS_ROOT / "hostile_reviewer" / "_lib"
if str(_SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(_SKILL_DIR))

# Make shared skill helpers importable (e.g. systemd_helper, docker_helper)
_SHARED_DIR = _SKILLS_ROOT / "_shared"
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))
