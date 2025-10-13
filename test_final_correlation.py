#!/usr/bin/env python3
"""
Final correlation test file.

This write operation should trigger:
1. PreToolUse hook (before write)
2. PostToolUse hook (after write)

Both should capture the correlation ID from the latest UserPromptSubmit event.
"""

def test_correlation():
    """Test function to verify hook correlation."""
    print("Testing correlation propagation across hooks")
    return "Correlation test complete"


if __name__ == "__main__":
    result = test_correlation()
    print(result)
