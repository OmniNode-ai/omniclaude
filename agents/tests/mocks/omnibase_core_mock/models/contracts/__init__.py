"""Mock contracts module - re-exports from real omnibase_core package."""

# ruff: noqa: E402
# This prevents the mock from shadowing the real package for contracts
# Import directly from site-packages by using __import__ with package path
import os
import sys

# Find and import the real omnibase_core.models.contracts module
real_module_name = "omnibase_core.models.contracts"

# Remove any paths that point to our mock from sys.path temporarily
mock_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
original_path = sys.path.copy()
sys.path = [p for p in sys.path if not p.startswith(mock_dir)]

try:
    # Import the real module
    real_module = __import__(real_module_name, fromlist=["*"])

    # Copy all public attributes from real module to this module
    for attr in dir(real_module):
        if not attr.startswith("_"):
            globals()[attr] = getattr(real_module, attr)
finally:
    # Restore original path
    sys.path = original_path
