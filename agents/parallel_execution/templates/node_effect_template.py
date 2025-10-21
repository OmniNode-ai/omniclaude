"""
Template for ONEX Effect Node

This template defines the structure and patterns for Effect nodes
that handle external I/O operations.
"""

from typing import Dict, List

# NodeEffect Template
NODE_EFFECT_TEMPLATE = '''
"""
{docstring}

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from enum import Enum
import asyncio
import logging

# ONEX Framework imports
from onex.base import NodeEffect


class {operation_enum_name}(str, Enum):
    """Supported operations for {node_name}."""
    {operation_definitions}


@dataclass
class {config_class_name}:
    """Configuration for {node_name.lower()} operations."""
    {config_fields}


class I{interface_name}(ABC):
    """Interface for {node_name.lower()} operations."""

    {interface_methods}


class {node_class_name}(NodeEffect):
    """ONEX Effect node for {node_name.lower()}.

    {description}

    Follows ONEX Effect node pattern for external I/O operations.
    """

    def __init__(self, {constructor_params}):
        """Initialize {node_name.lower()} effect."""
        {constructor_body}

    async def execute_effect(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute {node_name.lower()} effect operations.

        Args:
            input_data: Dictionary containing operation and parameters

        Returns:
            Dictionary with operation results
        """
        try:
            operation = input_data.get('operation', '{default_operation}')

            self.logger.info(f"Executing {node_name.lower()} operation: {{operation}}")

            {operation_dispatch}

        except Exception as e:
            self.logger.error(f"{node_name} operation failed: {{operation}}", exc_info=True)
            return {{
                "success": False,
                "error": str(e),
                "operation": operation
            }}

    {operation_methods}
'''


# Template parts
OPERATION_ENUM_TEMPLATE = '''    {operation_name} = "{operation_value}"'''

CONFIG_FIELD_TEMPLATE = """    {field_name}: {field_type} = {default_value}"""

INTERFACE_METHOD_TEMPLATE = '''    @abstractmethod
    async def {method_signature}:
        """{method_docstring}"""
        pass'''

CONSTRUCTOR_PARAM_TEMPLATE = """{param_name}: {param_type}"""

CONSTRUCTOR_BODY_TEMPLATE = """        self.{param_name} = {param_name}
        self.logger = logger or logging.getLogger(__name__)"""

OPERATION_METHOD_TEMPLATE = '''    async def _{operation_method}(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """{operation_docstring}"""
        {operation_body}
        return {{
            {operation_return_fields}
        }}'''

OPERATION_RETURN_FIELD_TEMPLATE = """            "{field_name}": {field_value},"""

# Template configurations
TEMPLATES = {
    "consul_adapter": {
        "docstring": "Consul API adapter Effect node for service discovery and configuration management",
        "node_name": "ConsulAdapter",
        "description": "Provides service discovery, configuration management, and health checks through Consul API integration",
        "default_operation": "register",
        "operations": [
            {
                "name": "REGISTER",
                "value": "register",
                "method": "_register_service",
                "docstring": "Register service with Consul",
            },
            {
                "name": "DEREGISTER",
                "value": "deregister",
                "method": "_deregister_service",
                "docstring": "Deregister service from Consul",
            },
            {
                "name": "HEALTH_CHECK",
                "value": "health_check",
                "method": "_health_check",
                "docstring": "Perform health check on service",
            },
            {
                "name": "KV_GET",
                "value": "kv_get",
                "method": "_kv_get",
                "docstring": "Get value from Consul KV store",
            },
            {
                "name": "KV_SET",
                "value": "kv_set",
                "method": "_kv_set",
                "docstring": "Set value in Consul KV store",
            },
        ],
        "config_fields": [
            {"name": "consul_url", "type": "str", "default": '"http://localhost:8500"'},
            {"name": "token", "type": "Optional[str]", "default": "None"},
        ],
        "interface_methods": [
            {
                "signature": "async def register_service(self, config: ConsulServiceConfig) -> bool:",
                "docstring": "Register service with Consul",
            },
            {
                "signature": "async def deregister_service(self, service_id: str) -> bool:",
                "docstring": "Deregister service from Consul",
            },
            {
                "signature": "async def health_check(self, service_id: str) -> Dict[str, Any]:",
                "docstring": "Perform health check on service",
            },
            {
                "signature": "async def get_kv(self, key: str) -> Optional[str]:",
                "docstring": "Get value from Consul KV store",
            },
            {
                "signature": "async def set_kv(self, key: str, value: str) -> bool:",
                "docstring": "Set value in Consul KV store",
            },
        ],
        "constructor_params": [
            {"name": "consul_adapter", "type": "IConsulClientAdapter"},
            {"name": "logger", "type": "Optional[logging.Logger]", "default": "None"},
        ],
        "operation_methods": [
            {
                "operation": "REGISTER",
                "method": "_register_service",
                "docstring": "Register service with Consul",
                "body": """config = ConsulServiceConfig(**data)
            success = await self.consul_adapter.register_service(config)

            if success:
                self.services[config.service_id] = config
                self.logger.info(f"Service registered: {{config.service_id}}")""",
                "return_fields": [
                    {"name": "success", "value": "success"},
                    {"name": "service_id", "value": "config.service_id"},
                    {"name": "service_name", "value": "config.service_name"},
                    {"name": "operation", "value": "ConsulOperationType.REGISTER"},
                ],
            }
        ],
    }
}


def generate_node_effect_code(
    template_name: str, agent_name: str, task_id: str, recommendations: List[Dict]
) -> str:
    """Generate node effect code from template."""
    template_config = TEMPLATES.get(template_name, TEMPLATES["consul_adapter"])

    # Extract template parts
    docstring = template_config["docstring"]
    node_name = template_config["node_name"]
    description = template_config["description"]
    default_operation = template_config["default_operation"]

    # Generate operation enum
    operation_definitions = []
    for op in template_config["operations"]:
        operation_definitions.append(f"{OPERATION_ENUM_TEMPLATE.format(**op)}")

    # Generate config fields
    config_fields = []
    for field in template_config["config_fields"]:
        config_fields.append(f"{CONFIG_FIELD_TEMPLATE.format(**field)}")

    # Generate interface methods
    interface_methods = []
    for method in template_config["interface_methods"]:
        interface_methods.append(f"{INTERFACE_METHOD_TEMPLATE.format(**method)}")

    # Generate constructor params
    constructor_params = []
    constructor_body = []
    for param in template_config["constructor_params"]:
        constructor_params.append(f"{CONSTRUCTOR_PARAM_TEMPLATE.format(**param)}")
        constructor_body.append(f"{CONSTRUCTOR_BODY_TEMPLATE.format(**param)}")

    # Generate operation dispatch
    operation_dispatch = []
    for op in template_config["operations"]:
        operation_dispatch.append(
            f"""            if operation == {node_name}OperationType.{op["name"]}:
                return await self._{op["method"]}(input_data)"""
        )

    # Generate operation methods
    operation_methods = []
    for op in template_config["operation_methods"]:
        return_fields = []
        for field in op["return_fields"]:
            return_fields.append(f"{OPERATION_RETURN_FIELD_TEMPLATE.format(**field)}")

        operation_methods.append(
            f'{OPERATION_METHOD_TEMPLATE.format(
            operation_method=op["method"],
            operation_docstring=op["docstring"],
            operation_body=op["body"],
            return_fields='\n            '.join(return_fields)
        )}'
        )

    # Build final code
    code = NODE_EFFECT_TEMPLATE.format(
        docstring=docstring,
        node_name=node_name,
        description=description,
        operation_enum_name=f"{node_name}Operation",
        operation_definitions="\n    ".join(operation_definitions),
        config_class_name=f"{node_name}Config",
        config_fields="\n    ".join(config_fields),
        interface_name=f"I{node_name}Adapter",
        interface_methods="\n\n    ".join(interface_methods),
        node_class_name=f"Node{node_name}Effect",
        constructor_params=", ".join(constructor_params),
        constructor_body="\n        ".join(constructor_body),
        operation_dispatch="\n            ".join(operation_dispatch),
        operation_methods="\n\n    ".join(operation_methods),
        default_operation=default_operation,
    )

    return code
