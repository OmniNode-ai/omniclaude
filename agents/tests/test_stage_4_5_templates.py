"""Test Stage 4.5 template rendering."""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"


def test_introspection_template_renders():
    """Test introspection event template renders correctly."""
    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR))
    template = env.get_template("introspection_event.py.jinja2")

    context = {
        "node_name": "NodePostgresqlWriterEffect",
        "node_type": "effect",
        "domain": "database",
        "service_name": "postgresql-writer",
        "version": "1.0.0",
        "description": "PostgreSQL writer for database operations",
    }

    result = template.render(context)

    # Verify key elements are present
    assert "_publish_introspection_event" in result
    assert "NODE_INTROSPECTION" in result
    assert "postgresql-writer" in result
    assert "database" in result
    assert "effect" in result
    assert "event_publisher" in result
    assert "capabilities" in result
    assert "omninode.discovery.node_introspection.v1" in result
    assert "Don't raise - introspection failure shouldn't block node startup" in result

    print("\n✅ Introspection template rendered successfully")
    print(f"   Length: {len(result)} characters")
    print(f"   Lines: {result.count(chr(10)) + 1}")


def test_startup_script_template_renders():
    """Test startup script template renders correctly."""
    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR))
    template = env.get_template("startup_script.py.jinja2")

    context = {
        "node_name": "NodePostgresqlWriterEffect",
        "name_lower": "postgresql_writer",
        "name_pascal": "PostgresqlWriter",
        "service_name": "postgresql-writer",
    }

    result = template.render(context)

    # Verify key elements are present
    assert "#!/usr/bin/env python3" in result
    assert "async def main" in result
    assert "NodePostgresqlWriterEffect" in result
    assert "graceful shutdown" in result.lower()
    assert "parse_args" in result
    assert "signal_handler" in result
    assert "KAFKA_BOOTSTRAP_SERVERS" in result
    assert "ModelPostgresqlWriterConfig" in result
    assert "--config" in result
    assert "--skip-event-bus" in result

    print("\n✅ Startup script template rendered successfully")
    print(f"   Length: {len(result)} characters")
    print(f"   Lines: {result.count(chr(10)) + 1}")


def test_introspection_template_all_variables():
    """Test introspection template with comprehensive variable set."""
    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR))
    template = env.get_template("introspection_event.py.jinja2")

    # Test with various node types
    test_cases = [
        {
            "node_name": "NodeUserAuthEffect",
            "node_type": "effect",
            "domain": "auth",
            "service_name": "user-auth",
            "version": "2.1.3",
            "description": "User authentication service",
        },
        {
            "node_name": "NodeDataTransformCompute",
            "node_type": "compute",
            "domain": "data",
            "service_name": "data-transform",
            "version": "1.5.0",
            "description": "Data transformation engine",
        },
        {
            "node_name": "NodeMetricsReducer",
            "node_type": "reducer",
            "domain": "monitoring",
            "service_name": "metrics-reducer",
            "version": "3.0.0",
            "description": "Metrics aggregation reducer",
        },
    ]

    for i, context in enumerate(test_cases, 1):
        result = template.render(context)
        assert context["node_name"] in result
        assert context["node_type"] in result
        assert context["domain"] in result
        assert context["service_name"] in result
        assert context["version"] in result
        print(f"\n✅ Test case {i} passed: {context['node_name']}")


def test_startup_script_template_all_variables():
    """Test startup script template with comprehensive variable set."""
    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR))
    template = env.get_template("startup_script.py.jinja2")

    test_cases = [
        {
            "node_name": "NodeUserAuthEffect",
            "name_lower": "user_auth",
            "name_pascal": "UserAuth",
            "service_name": "user-auth",
        },
        {
            "node_name": "NodeDataTransformCompute",
            "name_lower": "data_transform",
            "name_pascal": "DataTransform",
            "service_name": "data-transform",
        },
    ]

    for i, context in enumerate(test_cases, 1):
        result = template.render(context)
        assert context["node_name"] in result
        assert context["name_pascal"] in result
        assert f"model_{context['name_lower']}_config" in result
        print(f"\n✅ Test case {i} passed: {context['node_name']}")


def test_template_indentation():
    """Test that introspection template maintains proper indentation."""
    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR))
    template = env.get_template("introspection_event.py.jinja2")

    context = {
        "node_name": "NodeTestEffect",
        "node_type": "effect",
        "domain": "test",
        "service_name": "test-service",
        "version": "1.0.0",
        "description": "Test service",
    }

    result = template.render(context)

    # Check that the method definition starts with proper indentation (4 spaces)
    lines = result.split("\n")
    # Skip empty lines from Jinja2 comments
    non_empty_lines = [line for line in lines if line.strip()]
    assert non_empty_lines[0].startswith("    def _publish_introspection_event")

    # Check that docstring is properly indented
    assert '        """' in result

    print("\n✅ Indentation test passed")


def test_startup_script_executable():
    """Test that startup script has proper shebang."""
    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR))
    template = env.get_template("startup_script.py.jinja2")

    context = {
        "node_name": "NodeTestEffect",
        "name_lower": "test",
        "name_pascal": "Test",
        "service_name": "test-service",
    }

    result = template.render(context)

    # Check that script starts with shebang
    lines = result.split("\n")
    assert lines[0] == "#!/usr/bin/env python3"

    print("\n✅ Executable test passed")


if __name__ == "__main__":
    print("=" * 70)
    print("Testing Stage 4.5 Templates")
    print("=" * 70)

    # Run tests manually for visual feedback
    try:
        test_introspection_template_renders()
        test_startup_script_template_renders()
        test_introspection_template_all_variables()
        test_startup_script_template_all_variables()
        test_template_indentation()
        test_startup_script_executable()

        print("\n" + "=" * 70)
        print("✅ All tests passed!")
        print("=" * 70)

    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        import traceback

        traceback.print_exc()
        exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback

        traceback.print_exc()
        exit(1)
