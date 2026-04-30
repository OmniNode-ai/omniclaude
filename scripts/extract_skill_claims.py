#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Extract deterministic SKILL.md capability claims."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from plugins.onex.skills._lib.validate_skill_aspiration import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
