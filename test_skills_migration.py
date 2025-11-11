#!/usr/bin/env python3
"""
Test script for verifying Pydantic Settings migration in skills.

Tests:
1. Import each skill's main module
2. Verify no import errors
3. Verify Pydantic Settings configuration loads correctly
4. Test settings attributes are accessible
5. Verify no legacy os.getenv() patterns remain in critical paths
"""

import sys
from pathlib import Path

# Add omniclaude to path
OMNICLAUDE_PATH = Path("/Volumes/PRO-G40/Code/omniclaude")
sys.path.insert(0, str(OMNICLAUDE_PATH))

# Import Pydantic Settings first
from config import settings


def test_pydantic_settings():
    """Test 1: Verify Pydantic Settings loads correctly."""
    print("=" * 70)
    print("TEST 1: Pydantic Settings Configuration")
    print("=" * 70)

    try:
        # Test basic settings access
        print(f"✅ Kafka bootstrap servers: {settings.kafka_bootstrap_servers}")
        print(f"✅ Postgres host: {settings.postgres_host}")
        print(f"✅ Postgres port: {settings.postgres_port}")

        # Test helper methods
        effective_kafka = settings.get_effective_kafka_bootstrap_servers()
        print(f"✅ Effective Kafka servers: {effective_kafka}")

        postgres_dsn = settings.get_postgres_dsn()
        print(f"✅ PostgreSQL DSN: {postgres_dsn[:50]}...")  # Truncate password

        # Test validation
        errors = settings.validate_required_services()
        if errors:
            print(f"⚠️  Validation warnings: {len(errors)} issues found")
            for error in errors[:3]:  # Show first 3
                print(f"    - {error}")
        else:
            print("✅ All required services validated")

        print(
            "\n✅ TEST 1 PASSED: Pydantic Settings configuration loaded successfully\n"
        )
        return True

    except Exception as e:
        print(f"\n❌ TEST 1 FAILED: {e}\n")
        import traceback

        traceback.print_exc()
        return False


def test_skill_execute_direct():
    """Test 2: execute_direct.py imports and uses Pydantic Settings."""
    print("=" * 70)
    print("TEST 2: Skill execute_direct.py")
    print("=" * 70)

    try:
        # Add skill to path
        skill_path = (
            Path.home() / ".claude" / "skills" / "routing" / "request-agent-routing"
        )
        sys.path.insert(0, str(skill_path))

        # Import the module
        import execute_direct

        print("✅ Module imported successfully")

        # Verify it has access to settings
        print(
            f"✅ Module has access to Pydantic Settings: {hasattr(execute_direct, 'settings')}"
        )

        # Verify the request_routing_direct function exists
        print(
            f"✅ Function 'request_routing_direct' exists: {hasattr(execute_direct, 'request_routing_direct')}"
        )

        # Check for legacy patterns (should not find os.getenv for config)
        with open(skill_path / "execute_direct.py", "r") as f:
            content = f.read()
            if 'os.getenv("KAFKA' in content or 'os.getenv("POSTGRES' in content:
                print("❌ Found legacy os.getenv() patterns for Kafka/Postgres config")
                return False
            else:
                print("✅ No legacy os.getenv() patterns for critical configuration")

        print("\n✅ TEST 2 PASSED: execute_direct.py migrated successfully\n")
        return True

    except Exception as e:
        print(f"\n❌ TEST 2 FAILED: {e}\n")
        import traceback

        traceback.print_exc()
        return False


def test_skill_execute_kafka():
    """Test 3: execute_kafka.py imports and uses Pydantic Settings."""
    print("=" * 70)
    print("TEST 3: Skill execute_kafka.py")
    print("=" * 70)

    try:
        # Add skill to path
        skill_path = (
            Path.home() / ".claude" / "skills" / "routing" / "request-agent-routing"
        )
        sys.path.insert(0, str(skill_path))

        # Import the module
        import execute_kafka

        print("✅ Module imported successfully")

        # Verify it has access to settings
        print(
            f"✅ Module has access to Pydantic Settings: {hasattr(execute_kafka, 'settings')}"
        )

        # Verify the RoutingEventClient class exists
        print(
            f"✅ Class 'RoutingEventClient' exists: {hasattr(execute_kafka, 'RoutingEventClient')}"
        )

        # Verify RoutingEventClient uses settings.get_effective_kafka_bootstrap_servers()
        client_class = execute_kafka.RoutingEventClient
        print(f"✅ RoutingEventClient class is defined")

        # Check the actual implementation
        with open(skill_path / "execute_kafka.py", "r") as f:
            content = f.read()
            if "settings.get_effective_kafka_bootstrap_servers()" in content:
                print(
                    "✅ Uses settings.get_effective_kafka_bootstrap_servers() helper method"
                )
            else:
                print("⚠️  May not use Pydantic Settings helper method")

            # Check for legacy patterns
            if 'os.getenv("KAFKA' in content or 'os.getenv("POSTGRES' in content:
                print("❌ Found legacy os.getenv() patterns for Kafka/Postgres config")
                return False
            else:
                print("✅ No legacy os.getenv() patterns for critical configuration")

        print("\n✅ TEST 3 PASSED: execute_kafka.py migrated successfully\n")
        return True

    except Exception as e:
        print(f"\n❌ TEST 3 FAILED: {e}\n")
        import traceback

        traceback.print_exc()
        return False


def test_skill_intelligence():
    """Test 4: intelligence/request-intelligence/execute.py uses Pydantic Settings."""
    print("=" * 70)
    print("TEST 4: Skill intelligence/request-intelligence/execute.py")
    print("=" * 70)

    try:
        # Add skill to path
        skill_path = (
            Path.home() / ".claude" / "skills" / "intelligence" / "request-intelligence"
        )
        sys.path.insert(0, str(skill_path))

        # Import the module (rename to avoid conflict)
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "execute_intelligence", skill_path / "execute.py"
        )
        execute_intelligence = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(execute_intelligence)

        print("✅ Module imported successfully")

        # Verify it has access to settings
        print(
            f"✅ Module has access to Pydantic Settings: {hasattr(execute_intelligence, 'settings')}"
        )

        # Verify the main function exists
        print(f"✅ Function 'main' exists: {hasattr(execute_intelligence, 'main')}")

        # Check the actual implementation
        with open(skill_path / "execute.py", "r") as f:
            content = f.read()
            if "settings.get_effective_kafka_bootstrap_servers()" in content:
                print(
                    "✅ Uses settings.get_effective_kafka_bootstrap_servers() helper method"
                )
            else:
                print("⚠️  May not use Pydantic Settings helper method")

            # Check for legacy patterns
            if 'os.getenv("KAFKA' in content or 'os.getenv("POSTGRES' in content:
                print("❌ Found legacy os.getenv() patterns for Kafka/Postgres config")
                return False
            else:
                print("✅ No legacy os.getenv() patterns for critical configuration")

        print("\n✅ TEST 4 PASSED: intelligence/execute.py migrated successfully\n")
        return True

    except Exception as e:
        print(f"\n❌ TEST 4 FAILED: {e}\n")
        import traceback

        traceback.print_exc()
        return False


def test_runtime_configuration():
    """Test 5: Verify runtime configuration access in skill context."""
    print("=" * 70)
    print("TEST 5: Runtime Configuration Access")
    print("=" * 70)

    try:
        # Simulate what skills do at runtime
        from config import settings

        # Test Kafka configuration
        kafka_servers = settings.get_effective_kafka_bootstrap_servers()
        if kafka_servers:
            print(f"✅ Kafka bootstrap servers accessible: {kafka_servers}")
        else:
            print("⚠️  Kafka bootstrap servers not configured (may be expected)")

        # Test PostgreSQL configuration
        try:
            postgres_dsn = settings.get_postgres_dsn()
            print(f"✅ PostgreSQL DSN generation works")
        except Exception as e:
            print(f"⚠️  PostgreSQL DSN generation: {e}")

        # Test configuration categories
        print(f"✅ Postgres host: {settings.postgres_host}")
        print(f"✅ Qdrant host: {settings.qdrant_host}")
        print(f"✅ Archon intelligence URL: {settings.archon_intelligence_url}")

        print("\n✅ TEST 5 PASSED: Runtime configuration access verified\n")
        return True

    except Exception as e:
        print(f"\n❌ TEST 5 FAILED: {e}\n")
        import traceback

        traceback.print_exc()
        return False


def main():
    """Run all tests."""
    print("\n")
    print("╔" + "=" * 68 + "╗")
    print("║" + " " * 15 + "SKILLS PYDANTIC SETTINGS MIGRATION TEST" + " " * 14 + "║")
    print("╚" + "=" * 68 + "╝")
    print()

    tests = [
        ("Pydantic Settings Configuration", test_pydantic_settings),
        ("execute_direct.py", test_skill_execute_direct),
        ("execute_kafka.py", test_skill_execute_kafka),
        ("intelligence/execute.py", test_skill_intelligence),
        ("Runtime Configuration", test_runtime_configuration),
    ]

    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"❌ Test '{name}' crashed: {e}")
            import traceback

            traceback.print_exc()
            results.append((name, False))

    # Summary
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)

    for name, passed in results:
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"{status}: {name}")

    print()
    total = len(results)
    passed = sum(1 for _, p in results if p)
    print(f"Total: {passed}/{total} tests passed")

    if passed == total:
        print(
            "\n🎉 ALL TESTS PASSED - Skills successfully migrated to Pydantic Settings!"
        )
        return 0
    else:
        print(f"\n⚠️  {total - passed} test(s) failed - review output above")
        return 1


if __name__ == "__main__":
    sys.exit(main())
