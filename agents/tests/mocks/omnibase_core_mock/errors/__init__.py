"""Mock errors module - re-exports from real omnibase_core package."""

# This prevents the mock from shadowing the real package for errors
import os
import sys

# Remove any paths that point to our mock from sys.path temporarily
mock_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
original_path = sys.path.copy()
sys.path = [p for p in sys.path if not p.startswith(mock_dir)]

try:
    # Import the real module
    real_module = __import__("omnibase_core.errors", fromlist=["*"])

    # Copy all public attributes from real module to this module
    for attr in dir(real_module):
        if not attr.startswith("_"):
            globals()[attr] = getattr(real_module, attr)
finally:
    # Restore original path
    sys.path = original_path
