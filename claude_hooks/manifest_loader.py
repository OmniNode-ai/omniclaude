#!/usr/bin/env python3
"""
Manifest Loader - Load system manifest for hook injection
Used by user-prompt-submit hook to inject manifest into agent context
"""

import os
import sys
from pathlib import Path


def load_manifest():
    """Load and return system manifest."""
    # Add agents/lib to path - try multiple locations
    project_path = os.environ.get("PROJECT_PATH", "")
    search_paths = []

    # Add project path if available (prioritize project directory)
    if project_path:
        search_paths.append(Path(project_path) / "agents" / "lib")

    # Add home directory
    search_paths.append(Path.home() / ".claude" / "agents" / "lib")

    # Add current working directory as fallback
    search_paths.append(Path.cwd() / "agents" / "lib")

    # Add all existing paths to sys.path
    for lib_path in search_paths:
        if lib_path.exists():
            sys.path.insert(0, str(lib_path))

    try:
        from manifest_injector import inject_manifest

        manifest = inject_manifest()
        return manifest
    except FileNotFoundError:
        # Manifest file doesn't exist - non-blocking
        return "System Manifest: Not available (file not found)"
    except Exception as e:
        # Any other error - non-blocking
        return f"System Manifest: Not available (error: {str(e)})"


if __name__ == "__main__":
    print(load_manifest())
