#!/usr/bin/env python3
"""
Test file to verify hook correlation ID propagation.

This file will trigger:
1. UserPromptSubmit (when I read it)
2. PreToolUse (when I write it)
3. PostToolUse (after write completes)

All should share the same correlation ID.
"""

def calculate_fibonacci(n: int) -> int:
    """Calculate the nth Fibonacci number using recursion."""
    if n <= 1:
        return n
    return calculate_fibonacci(n - 1) + calculate_fibonacci(n - 2)


def main():
    """Test function for hook correlation."""
    result = calculate_fibonacci(10)
    print(f"Fibonacci(10) = {result}")


if __name__ == "__main__":
    main()
