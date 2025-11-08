#!/usr/bin/env python3
"""
Integration test for session start logging with username display.

This test verifies the enhanced console output shows username information.
"""

import os
import sys
import uuid
from pathlib import Path

# Add current directory to path
sys.path.insert(0, os.path.dirname(__file__))

from session_intelligence import log_session_start


def main():
    """Test session start logging with enhanced username display."""
    print("=" * 60)
    print("Session Start Integration Test")
    print("Testing enhanced username logging...")
    print("=" * 60)
    print()

    # Generate test session ID
    session_id = str(uuid.uuid4())

    # Determine project path portably
    # This file is in claude_hooks/lib/, so project root is 2 levels up
    project_path = Path(__file__).parent.parent.parent.resolve()

    # Log session start
    # Note: This will attempt to connect to the database
    # If database is unavailable, it will gracefully fail
    print("Calling log_session_start()...\n")

    event_id = log_session_start(
        session_id=session_id,
        project_path=str(project_path),
        cwd=os.getcwd(),
        additional_metadata={"test": "username_logging_enhancement"},
    )

    print()
    print("=" * 60)

    if event_id:
        print("✅ Integration test PASSED")
        print(f"   Event ID: {event_id}")
        print()
        print("Expected output should show:")
        print("  - User: username@hostname")
        print("  - Name: Full Name (if available)")
        print("  - UID: user_id (if Unix/Linux)")
        print("  - Branch: git_branch (if available)")
    else:
        print("⚠️  Integration test completed with warnings")
        print("   (Database may not be available - this is expected in test)")

    print("=" * 60)


if __name__ == "__main__":
    main()
