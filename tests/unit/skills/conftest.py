# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
import sys
from pathlib import Path

_SKILLS_ROOT = Path(__file__).parents[3] / "plugins" / "onex" / "skills"

# Make shared skill helpers importable (e.g. systemd_helper, docker_helper)
_SHARED_DIR = _SKILLS_ROOT / "_shared"
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))
