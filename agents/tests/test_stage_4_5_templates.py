"""Test Stage 4.5 template rendering."""

from pathlib import Path

from jinja2 import Environment, FileSystemLoader

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"


def test_introspection_template_renders():
    """Test introspection event template renders correctly."""
    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR), autoescape=True)
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
    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR), autoescape=True)
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
    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR), autoescape=True)
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
    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR), autoescape=True)
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
    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR), autoescape=True)
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
    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR), autoescape=True)
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


def test_orchestrator_workflow_events_template_renders():
    """Test orchestrator workflow events template renders correctly (Day 4)."""
    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR), autoescape=True)
    template = env.get_template("orchestrator_workflow_events.py.jinja2")

    context = {
        "node_name": "NodeCodeGenOrchestrator",
        "node_type": "orchestrator",
        "domain": "codegen",
        "service_name": "code-generator",
        "version": "1.0.0",
        "description": "Code generation orchestrator",
    }

    result = template.render(context)

    # Verify workflow event methods are present
    assert "_publish_workflow_started" in result
    assert "_publish_stage_started" in result
    assert "_publish_stage_completed" in result
    assert "_publish_stage_failed" in result
    assert "_publish_workflow_completed" in result
    assert "_publish_workflow_failed" in result

    # Verify event types are correct
    assert "omninode.orchestration.workflow_started.v1" in result
    assert "omninode.orchestration.stage_started.v1" in result
    assert "omninode.orchestration.stage_completed.v1" in result
    assert "omninode.orchestration.workflow_completed.v1" in result

    # Verify parameters are present
    assert "correlation_id: UUID" in result
    assert "workflow_context: dict[str, Any]" in result
    assert "stage_name: str" in result
    assert "stage_result: dict[str, Any]" in result
    assert "duration_ms: int" in result

    # Verify logging statements
    assert "WORKFLOW_STARTED" in result
    assert "STAGE_COMPLETED" in result
    assert "workflow_id=" in result

    # Verify error handling
    assert (
        "Don't raise - event publishing failure shouldn't block workflow execution"
        in result
    )

    print("\n✅ Orchestrator workflow events template rendered successfully")
    print(f"   Length: {len(result)} characters")
    print(f"   Lines: {result.count(chr(10)) + 1}")
    print("   Methods: 6 workflow event methods")


def test_orchestrator_template_all_node_types():
    """Test that orchestrator template works with various orchestrator types."""
    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR), autoescape=True)
    template = env.get_template("orchestrator_workflow_events.py.jinja2")

    test_cases = [
        {
            "node_name": "NodeWorkflowOrchestrator",
            "node_type": "orchestrator",
            "domain": "workflow",
            "service_name": "workflow-orchestrator",
            "version": "1.0.0",
            "description": "Workflow orchestration",
        },
        {
            "node_name": "NodeDataPipelineOrchestrator",
            "node_type": "orchestrator",
            "domain": "data",
            "service_name": "data-pipeline",
            "version": "2.0.0",
            "description": "Data pipeline orchestrator",
        },
    ]

    for i, context in enumerate(test_cases, 1):
        result = template.render(context)
        assert context["node_name"] in result
        assert context["service_name"] in result
        assert context["domain"] in result
        assert "_publish_workflow_started" in result
        print(f"\n✅ Test case {i} passed: {context['node_name']}")


def test_orchestrator_template_indentation():
    """Test that orchestrator workflow events maintain proper indentation."""
    env = Environment(loader=FileSystemLoader(TEMPLATES_DIR), autoescape=True)
    template = env.get_template("orchestrator_workflow_events.py.jinja2")

    context = {
        "node_name": "NodeTestOrchestrator",
        "node_type": "orchestrator",
        "domain": "test",
        "service_name": "test-orchestrator",
        "version": "1.0.0",
        "description": "Test orchestrator",
    }

    result = template.render(context)

    # Check that method definitions start with proper indentation (4 spaces)
    lines = result.split("\n")
    non_empty_lines = [line for line in lines if line.strip()]

    # Find first method definition
    method_lines = [
        line for line in non_empty_lines if "async def _publish_workflow" in line
    ]
    assert len(method_lines) > 0
    assert method_lines[0].startswith("    async def _publish_workflow")

    # Check docstring indentation
    assert '        """' in result

    print("\n✅ Orchestrator template indentation test passed")


if __name__ == "__main__":
    print("=" * 70)
    print("Testing Stage 4.5 Templates (+ Day 4 Orchestrator Enhancements)")
    print("=" * 70)

    # Run tests manually for visual feedback
    try:
        # Original Stage 4.5 tests
        test_introspection_template_renders()
        test_startup_script_template_renders()
        test_introspection_template_all_variables()
        test_startup_script_template_all_variables()
        test_template_indentation()
        test_startup_script_executable()

        # Day 4: Orchestrator workflow events tests
        print("\n" + "=" * 70)
        print("Day 4: Testing Orchestrator Workflow Events Template")
        print("=" * 70)
        test_orchestrator_workflow_events_template_renders()
        test_orchestrator_template_all_node_types()
        test_orchestrator_template_indentation()

        print("\n" + "=" * 70)
        print("✅ All tests passed! (6 original + 3 Day 4 orchestrator tests)")
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
