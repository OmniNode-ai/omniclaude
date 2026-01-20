"""Tests for OmniClaude hooks module."""

import sys
from pathlib import Path

# Ensure src/omniclaude takes precedence over legacy omniclaude/ directory
_src_path = str(Path(__file__).parent.parent.parent / "src")
if _src_path not in sys.path:
    sys.path.insert(0, _src_path)
