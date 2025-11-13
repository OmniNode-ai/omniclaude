# Stage 4.5 Template Usage Guide

## Overview

Stage 4.5 introduces two critical Jinja2 templates for Event Bus Integration:

1. **introspection_event.py.jinja2** - Method implementation for publishing introspection events
2. **startup_script.py.jinja2** - Standalone node startup script with event bus integration

## Template Locations

```
agents/templates/
├── introspection_event.py.jinja2   (2.9 KB, 73 lines)
└── startup_script.py.jinja2        (4.6 KB, 145 lines)
```

## Usage Examples

### 1. Introspection Event Template

**Purpose**: Generates `_publish_introspection_event()` method for Effect nodes

**Variables Required**:
- `node_name`: Full class name (e.g., "NodePostgresqlWriterEffect")
- `node_type`: ONEX type (e.g., "effect", "compute", "reducer", "orchestrator")
- `domain`: Domain category (e.g., "database", "auth", "monitoring")
- `service_name`: Service name (e.g., "postgresql-writer")
- `version`: Semantic version (e.g., "1.0.0")
- `description`: Human-readable description

**Example Rendering**:

```python
from jinja2 import Environment, FileSystemLoader

# Enable autoescape for security (prevents XSS vulnerabilities)
env = Environment(
    loader=FileSystemLoader('agents/templates'),
    autoescape=True
)
template = env.get_template('introspection_event.py.jinja2')

context = {
    'node_name': 'NodePostgresqlWriterEffect',
    'node_type': 'effect',
    'domain': 'database',
    'service_name': 'postgresql-writer',
    'version': '1.0.0',
    'description': 'PostgreSQL writer for database operations',
}

method_code = template.render(context)
print(method_code)
```

**Output** (abbreviated):

```python
    def _publish_introspection_event(self) -> None:
        """
        Publish NODE_INTROSPECTION_EVENT for automatic service discovery.

        This enables Consul registration with:
        - Node ID and metadata
        - Available actions/capabilities
        - Health endpoint
        - Service tags for discovery
        """
        if not hasattr(self, 'event_publisher') or self.event_publisher is None:
            self.logger.warning("Event publisher not initialized, skipping introspection")
            return

        try:
            # Gather node capabilities
            capabilities = {
                "actions": [
                    "process",
                    "health_check",
                    "get_metrics",
                    "validate_input",
                    "validate_output",
                ],
                "protocols": ["event_bus", "http"],
                "metadata": {
                    "node_type": "effect",
                    "domain": "database",
                    "service_name": "postgresql-writer",
                    "version": "1.0.0",
                    "description": "PostgreSQL writer for database operations",
                    "author": "ONEX",
                },
            }

            # Create introspection event payload
            introspection_event = {
                "event_type": "omninode.discovery.node_introspection.v1",
                "node_id": str(self._node_id) if hasattr(self, '_node_id') else "unknown",
                "node_name": "NodePostgresqlWriterEffect",
                "version": "1.0.0",
                "capabilities": capabilities,
                "tags": [
                    "database",
                    "effect",
                    "postgresql-writer",
                    "event_driven",
                    "onex_compliant",
                ],
                "health_endpoint": f"/health/{self._node_id}" if hasattr(self, '_node_id') else "/health",
                "timestamp": datetime.utcnow().isoformat(),
            }

            # Publish to event bus
            self.event_publisher.publish(
                topic="omninode.discovery.introspection.v1",
                event_type="NODE_INTROSPECTION",
                payload=introspection_event,
                correlation_id=self._node_id if hasattr(self, '_node_id') else None,
            )

            self.logger.info(
                f"Published introspection event | "
                f"node_id={self._node_id if hasattr(self, '_node_id') else 'unknown'} | "
                f"service=postgresql-writer"
            )

        except Exception as e:
            self.logger.error(f"Failed to publish introspection event: {e}", exc_info=True)
            # Don't raise - introspection failure shouldn't block node startup
```

### 2. Startup Script Template

**Purpose**: Generates standalone Python script for node startup with event bus

**Variables Required**:
- `node_name`: Full class name (e.g., "NodePostgresqlWriterEffect")
- `name_lower`: Snake_case name (e.g., "postgresql_writer")
- `name_pascal`: PascalCase name (e.g., "PostgresqlWriter")
- `service_name`: Service name (e.g., "postgresql-writer")

**Example Rendering**:

```python
from jinja2 import Environment, FileSystemLoader

# Enable autoescape for security (prevents XSS vulnerabilities)
env = Environment(
    loader=FileSystemLoader('agents/templates'),
    autoescape=True
)
template = env.get_template('startup_script.py.jinja2')

context = {
    'node_name': 'NodePostgresqlWriterEffect',
    'name_lower': 'postgresql_writer',
    'name_pascal': 'PostgresqlWriter',
    'service_name': 'postgresql-writer',
}

script_code = template.render(context)

# Save to file
with open('start_node.py', 'w') as f:
    f.write(script_code)

# Make executable
import os
os.chmod('start_node.py', 0o755)
```

**Script Features**:

- **Shebang**: `#!/usr/bin/env python3` for direct execution
- **Argument Parsing**:
  - `--config` / `-c`: Custom configuration file path
  - `--kafka-servers`: Override Kafka bootstrap servers
  - `--skip-event-bus`: Standalone mode without event bus
  - `--help`: Display usage information

- **Environment Variables**:
  - `KAFKA_BOOTSTRAP_SERVERS`: Kafka connection string
  - `SERVICE_NAME`: Override service name
  - `LOG_LEVEL`: Logging verbosity (DEBUG, INFO, WARNING, ERROR)

- **Signal Handlers**:
  - `SIGINT` (Ctrl+C): Graceful shutdown
  - `SIGTERM`: Graceful shutdown

- **Error Handling**:
  - Event bus initialization failures (continues in standalone mode)
  - Fatal errors with stack traces
  - Keyboard interrupts

**Usage Examples**:

```bash
# Start with default configuration
python start_node.py

# Start with custom config
python start_node.py --config production.yaml

# Start with custom Kafka servers
python start_node.py --kafka-servers localhost:9092

# Start in standalone mode (no event bus)
python start_node.py --skip-event-bus

# Get help
python start_node.py --help
```

**Output Example**:

```
╔════════════════════════════════════════════════════════════════╗
║                 NodePostgresqlWriterEffect                      ║
║                 Event Bus Integration Enabled                   ║
╚════════════════════════════════════════════════════════════════╝

2025-10-22 07:45:00 - __main__ - INFO - Creating node instance...
2025-10-22 07:45:00 - __main__ - INFO - Initializing event bus connection...
2025-10-22 07:45:01 - __main__ - INFO - ✅ Node initialized and registered with Consul
2025-10-22 07:45:01 - __main__ - INFO -    Node ID: 550e8400-e29b-41d4-a716-446655440000
2025-10-22 07:45:01 - __main__ - INFO -    Instance ID: inst-1234
2025-10-22 07:45:01 - __main__ - INFO -    Service Name: postgresql-writer
2025-10-22 07:45:01 - __main__ - INFO - 🚀 NodePostgresqlWriterEffect is running
2025-10-22 07:45:01 - __main__ - INFO -    Press Ctrl+C to shutdown gracefully
```

## Integration with Generation Pipeline

### Step 1: Integrate Introspection Event into Effect Template

Update `effect_node_template.py` to include the introspection method:

### Conceptual Example (Pseudocode)

**Note**: The following is pseudocode for illustration purposes. The actual implementation in the generation pipeline may differ. These methods serve as examples of how the templates could be integrated.

```python
# Pseudocode - illustrative example only
# In business_logic_generator.py
def _generate_effect_node(self, context: dict) -> str:
    # Render introspection event method
    introspection_method = self._render_template(
        'introspection_event.py.jinja2',
        context
    )

    # Insert into effect template
    effect_template = self._render_template(
        'effect_node_template.py',
        {**context, 'introspection_method': introspection_method}
    )

    return effect_template
```

### Step 2: Generate Startup Script

Add startup script generation to the pipeline:

### Conceptual Example (Pseudocode)

**Note**: The following is pseudocode for illustration purposes. The actual implementation in the generation pipeline may differ. These methods serve as examples of how startup scripts could be generated.

```python
# Pseudocode - illustrative example only
# In generation_pipeline.py
def generate_node_with_startup_script(self, prompt: str, output_dir: Path):
    # Generate node
    node_code = self.generate_node(prompt)

    # Extract context
    context = self._extract_context_from_prompt(prompt)

    # Render startup script
    startup_script = self._render_template(
        'startup_script.py.jinja2',
        {
            'node_name': context['node_class_name'],
            'name_lower': context['name_snake_case'],
            'name_pascal': context['name_pascal_case'],
            'service_name': context['service_name'],
        }
    )

    # Save startup script
    script_path = output_dir / 'start_node.py'
    script_path.write_text(startup_script)
    script_path.chmod(0o755)

    return node_code, script_path
```

## Testing

Comprehensive test suite available at:
```
agents/tests/test_stage_4_5_templates.py
```

**Run Tests**:

```bash
# Direct execution
python agents/tests/test_stage_4_5_templates.py

# With pytest
pytest agents/tests/test_stage_4_5_templates.py -v

# Expected output: 6/6 tests passed
```

**Test Coverage**:
- ✅ Template rendering functionality
- ✅ Variable substitution
- ✅ Multiple node types (Effect, Compute, Reducer)
- ✅ Proper indentation
- ✅ Shebang and executable permissions
- ✅ Key features presence

## Validation Checklist

Before deploying generated code:

- [ ] All template variables provided
- [ ] Node name follows ONEX naming convention (`Node<Name><Type>`)
- [ ] Service name is kebab-case
- [ ] Version is valid semantic version (e.g., "1.0.0")
- [ ] Domain is a valid category
- [ ] Generated method has proper indentation
- [ ] Startup script is executable (chmod +x)
- [ ] Event bus connection tested
- [ ] Introspection event publishes successfully
- [ ] Signal handlers work correctly

## Common Issues and Solutions

### Issue: Template Variable Missing

**Error**: `jinja2.exceptions.UndefinedError: 'node_type' is undefined`

**Solution**: Ensure all required variables are in the context dict:

```python
required_vars = {
    'introspection_event.py.jinja2': [
        'node_name', 'node_type', 'domain',
        'service_name', 'version', 'description'
    ],
    'startup_script.py.jinja2': [
        'node_name', 'name_lower', 'name_pascal', 'service_name'
    ]
}
```

### Issue: Import Errors in Generated Code

**Error**: `ModuleNotFoundError: No module named 'models.model_postgresql_writer_config'`

**Solution**: Ensure the node directory structure matches expected imports:

```
generated_node/
├── node.py                                  # Main node class
├── models/
│   ├── __init__.py
│   ├── model_postgresql_writer_config.py
│   ├── model_postgresql_writer_input.py
│   └── model_postgresql_writer_output.py
└── start_node.py                            # Generated startup script
```

### Issue: Event Publisher Not Initialized

**Warning**: `Event publisher not initialized, skipping introspection`

**Solution**: Ensure the node has event_publisher attribute:

```python
class NodePostgresqlWriterEffect(NodeEffect):
    def __init__(self, config):
        super().__init__(config)
        self.event_publisher = EventPublisher(config.kafka_config)
```

## Best Practices

1. **Always test rendered templates** before production use
2. **Version control generated code** for traceability
3. **Use environment variables** for configuration (never hardcode)
4. **Monitor introspection events** in Kafka for successful registration
5. **Implement health checks** for Consul service discovery
6. **Log all startup phases** for debugging
7. **Handle graceful shutdown** to clean up resources
8. **Document node capabilities** in metadata
9. **Tag services appropriately** for discovery filtering
10. **Test standalone mode** as fallback for event bus failures

## Next Steps

1. **Integrate with Business Logic Generator**: Update to use new templates
2. **Add CLI Support**: Extend `generate_node.py` to create startup scripts
3. **Document Node Types**: Create guides for Compute, Reducer, Orchestrator
4. **Enhance Error Handling**: Add retry logic for Kafka connection failures
5. **Create Docker Templates**: Containerization support for generated nodes

## References

- **Introspection Publisher Mixin**: `omnibase_core.mixins.mixin_introspection_publisher` (from omnibase_core package)
- **Effect Node Template**: `agents/templates/effect_node_template.py`
- **ONEX Architecture**: Internal documentation
- **Stage 4.5 Specification**: Event Bus Integration requirements

## Support

For issues or questions:
- Check test suite for examples
- Review template source code for comments
- Consult ONEX architecture documentation
- Test with minimal example first

---

**Last Updated**: 2025-10-22
**Stage**: 4.5 (Event Bus Integration)
**Status**: ✅ Complete - All tests passing
