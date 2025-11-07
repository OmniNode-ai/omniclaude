#!/usr/bin/env python3
"""
Test script to demonstrate enhanced session start output.

This simulates the enhanced username logging without requiring database access.
"""

import os
import platform
import sys

# Add current directory to path
sys.path.insert(0, os.path.dirname(__file__))

from session_intelligence import (
    get_environment_metadata,
    get_git_metadata,
)


def simulate_session_start_output():
    """Simulate the enhanced session start logging output."""
    print("=" * 60)
    print("Enhanced Session Start Output Demonstration")
    print("=" * 60)
    print()

    # Get metadata (same as actual function does)
    env_metadata = get_environment_metadata()
    git_metadata = get_git_metadata(os.getcwd())

    # Simulate the enhanced output (from lines 238-257)
    event_id = "test-event-123"
    elapsed_ms = 25.3

    print("Simulated session start output:")
    print("-" * 60)

    # Enhanced logging with username for better debugging/auditing
    username = env_metadata.get("user", "unknown")
    hostname = env_metadata.get("hostname", "unknown")

    # Show user context in session start message
    print(f"✅ Session start logged: {event_id} ({elapsed_ms:.1f}ms)")
    print(f"   User: {username}@{hostname}")

    # Show additional context if available (full name, UID)
    if env_metadata.get("user_fullname"):
        print(f"   Name: {env_metadata['user_fullname']}")
    if env_metadata.get("uid") is not None:
        print(f"   UID: {env_metadata['uid']}")

    # Show git context if available
    if git_metadata.get("git_branch"):
        branch_info = git_metadata["git_branch"]
        if git_metadata.get("git_dirty"):
            branch_info += " (uncommitted changes)"
        print(f"   Branch: {branch_info}")

    print("-" * 60)
    print()

    # Show what metadata is captured
    print("Metadata captured for database:")
    print("-" * 60)
    for key, value in env_metadata.items():
        if value is not None:
            # Don't show full shell path (too long)
            if key == "shell" and value:
                value = value.split("/")[-1] if "/" in value else value
            print(f"   {key}: {value}")

    print()
    print("Git metadata:")
    for key, value in git_metadata.items():
        if value and key != "git_remote":  # Don't show remote URL (can be long)
            print(f"   {key}: {value}")

    print("-" * 60)
    print()

    # Summary
    print("=" * 60)
    print("Enhancement Summary:")
    print("=" * 60)
    print()
    print("✅ BEFORE: Only showed event ID and timing")
    print("   Example: ✅ Session start logged: abc123 (25.3ms)")
    print()
    print("✅ AFTER: Shows user context for debugging/auditing")
    print("   Example:")
    print("   ✅ Session start logged: abc123 (25.3ms)")
    print(f"      User: {username}@{hostname}")
    if env_metadata.get("user_fullname"):
        print(f"      Name: {env_metadata['user_fullname']}")
    if env_metadata.get("uid") is not None:
        print(f"      UID: {env_metadata['uid']}")
    if git_metadata.get("git_branch"):
        print(f"      Branch: {git_metadata['git_branch']}")
    print()
    print("Benefits:")
    print("  • Immediate visibility of who started the session")
    print("  • Better debugging in multi-user environments")
    print("  • Improved audit trail in console logs")
    print("  • UID helps distinguish users with same username")
    print("  • Full name helps identify developers")
    print("  • Git branch shows development context")
    print()
    print("=" * 60)


if __name__ == "__main__":
    simulate_session_start_output()
