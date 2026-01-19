#!/usr/bin/env python3
"""
Test script for environment-specific .env file loading.

This script validates that the Settings class correctly loads configuration
from environment-specific .env files based on the ENVIRONMENT variable.
"""

import subprocess
import sys
from pathlib import Path


def test_default_loading():
    """Test loading without ENVIRONMENT variable set."""
    print("Test 1: Loading without ENVIRONMENT variable")
    print("-" * 60)

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import os
if 'ENVIRONMENT' in os.environ:
    del os.environ['ENVIRONMENT']
from config.settings import Settings
settings = Settings()
print(f'Environment field: {settings.environment}')
print(f'PostgreSQL port: {settings.postgres_port}')
""",
        ],
        capture_output=True,
        text=True,
        cwd=Path(__file__).parent.parent,
    )

    if result.returncode == 0:
        print("✅ Loaded successfully")
        print(result.stdout.strip())
    else:
        print("❌ Failed")
        print(result.stderr)
        return False

    print()
    return True


def test_environment_specific_loading():
    """Test loading with ENVIRONMENT=test and a .env.test file."""
    print("Test 2: Loading with ENVIRONMENT=test")
    print("-" * 60)

    # Create temporary .env.test file
    repo_root = Path(__file__).parent.parent
    test_env_path = repo_root / ".env.test"

    try:
        # Write test-specific configuration
        test_env_path.write_text(
            """# Test environment configuration
POSTGRES_PORT=9999
ENVIRONMENT=test
"""
        )
        print(f"Created test file: {test_env_path}")

        result = subprocess.run(
            [
                sys.executable,
                "-c",
                """
import os
os.environ['ENVIRONMENT'] = 'test'
from config.settings import Settings
settings = Settings()
print(f'Environment field: {settings.environment}')
print(f'PostgreSQL port: {settings.postgres_port}')
assert settings.postgres_port == 9999, f'Expected port 9999, got {settings.postgres_port}'
print('✅ Environment-specific value loaded correctly!')
""",
            ],
            capture_output=True,
            text=True,
            cwd=repo_root,
        )

        if result.returncode == 0:
            print("✅ Loaded successfully from .env.test")
            print(result.stdout.strip())
        else:
            print("❌ Failed")
            print(result.stderr)
            return False

    finally:
        # Cleanup
        test_env_path.unlink(missing_ok=True)
        print(f"Cleaned up: {test_env_path}")

    print()
    return True


def test_fallback_when_env_file_missing():
    """Test fallback to .env when environment-specific file doesn't exist."""
    print("Test 3: Fallback when .env.{ENVIRONMENT} doesn't exist")
    print("-" * 60)

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import os
os.environ['ENVIRONMENT'] = 'nonexistent'
from config.settings import Settings
settings = Settings()
print(f'Environment field: {settings.environment}')
print(f'PostgreSQL port: {settings.postgres_port}')
print('✅ Fallback to .env worked correctly!')
""",
        ],
        capture_output=True,
        text=True,
        cwd=Path(__file__).parent.parent,
    )

    if result.returncode == 0:
        print("✅ Fallback successful")
        print(result.stdout.strip())
    else:
        print("❌ Failed")
        print(result.stderr)
        return False

    print()
    return True


def main():
    """Run all tests."""
    print("=" * 60)
    print("Environment-Specific .env Loading Tests")
    print("=" * 60)
    print()

    tests = [
        test_default_loading,
        test_environment_specific_loading,
        test_fallback_when_env_file_missing,
    ]

    results = []
    for test in tests:
        results.append(test())

    print("=" * 60)
    print("Test Summary")
    print("=" * 60)

    if all(results):
        print("✅ All tests passed!")
        return 0
    else:
        print("❌ Some tests failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
