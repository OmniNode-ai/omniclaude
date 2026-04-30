#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""CI/pre-commit entrypoint for OMN-9075 skill aspiration validation."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from plugins.onex.skills._lib.validate_skill_aspiration import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main([".", "--validate", *sys.argv[1:]]))
