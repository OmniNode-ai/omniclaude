#!/usr/bin/env python3
"""
View the complete manifest that agents receive.
Shows all sections with pattern discovery, infrastructure, models, etc.
"""

import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agents.lib.manifest_injector import inject_manifest


def main():
    print("=" * 80)
    print("GENERATING AGENT MANIFEST")
    print("=" * 80)
    print()

    # Generate manifest with all sections (inject_manifest is synchronous)
    manifest = inject_manifest(
        agent_name="manifest-viewer",
        sections=[
            "patterns",
            "infrastructure",
            "models",
            "database_schemas",
            "debug_intelligence",
        ],
    )

    print(manifest)
    print()
    print("=" * 80)
    print("END OF MANIFEST")
    print("=" * 80)


if __name__ == "__main__":
    main()
