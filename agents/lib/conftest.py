#!/usr/bin/env python3
"""
Pytest Configuration for agents/lib tests.

Sets up Python path and environment for testing:
- Adds project root to sys.path for config module access
- Loads .env file for configuration
- Enables routing_event_client tests to import config.settings

This follows the same pattern as agents/tests/conftest.py.
"""

import sys
from pathlib import Path

# Load environment variables
from dotenv import load_dotenv


# Add project root to sys.path (3 levels up: lib -> agents -> project root)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Load .env from project root
env_path = PROJECT_ROOT / ".env"
if env_path.exists():
    load_dotenv(env_path)
else:
    # Fallback: try current directory
    load_dotenv()

print(f"[conftest.py] Project root added to sys.path: {PROJECT_ROOT}")
print(
    f"[conftest.py] Environment loaded from: {env_path if env_path.exists() else 'default .env'}"
)
