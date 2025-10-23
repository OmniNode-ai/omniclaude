"""Mock for model_algorithm_config - imports from real package."""

# ruff: noqa: E402, F401, F403
# Import from the actual installed package by manipulating sys.path
import sys
from pathlib import Path

# Remove mock directory from path temporarily
mock_root = Path(__file__).parent.parent.parent.parent
if str(mock_root) in sys.path:
    sys.path.remove(str(mock_root))

# Now import from real package
from omnibase_core.models.contracts.model_algorithm_config import *  # noqa: F401, F403
