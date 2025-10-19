"""
Template for Model Contracts

This template defines the structure and patterns for data contracts
that ensure type safety and validation in the ONEX framework.
"""

# Model Contract Template
MODEL_CONTRACT_TEMPLATE = '''
"""
{docstring}

from typing import Dict, Any, Optional, List, Union
from dataclasses import dataclass, field
from enum import Enum
import re
import json
from datetime import datetime


class {operation_enum_name}(str, Enum):
    """Supported operations for {contract_name}.**/n    {operation_definitions}


class {severity_enum_name}(str, Enum):
    """Validation severity levels for {contract_name}.**/n    {severity_definitions}


class ValidationResult:
    """Result of validation operation."""

    def __init__(self, is_valid: bool, errors: List[str] = None, warnings: List[str] = None):
        self.is_valid = is_valid
        self.errors = errors or []
        self.warnings = warnings or []

    @property
    def severity(self) -> {severity_enum_name}:
        """Get validation severity.**/n        if self.errors:
            return {severity_enum_name}.ERROR
        elif self.warnings:
            return {severity_enum_name}.WARNING
        return {severity_enum_name}.INFO


@dataclass
class {input_contract_class_name}:
    """Input contract for {contract_name.lower()} operations.**/n    {input_contract_fields}

    def validate(self) -> ValidationResult:
        """Validate input contract.**/n        {input_validation}


@dataclass
class {output_contract_class_name}:
    """Output contract for {contract_name.lower()} operations.**/n    {output_contract_fields}

    def validate(self) -> ValidationResult:
        """Validate output contract.**/n        {output_validation}


class {validator_class_name}:
    """Validator for {contract_name} model contracts.**/n/n    @staticmethod/n    def validate_input(input_data: Dict[str, Any]) -> ValidationResult:
        """Validate input contract.**/n        try:
            contract = {input_contract_class_name}(**input_data)
            return contract.validate()
        except Exception as e:
            return ValidationResult(False, [f"Invalid contract structure: {{str(e)}}"])

    @staticmethod/n    def validate_output(output_data: Dict[str, Any]) -> ValidationResult:
        """Validate output contract.**/n        try:
            contract = {output_contract_class_name}(**output_data)
            return contract.validate()
        except Exception as e:
            return ValidationResult(False, [f"Invalid contract structure: {{str(e)}}"])
'''


# Validation template parts
OPERATION_ENUM_DEFINITION_TEMPLATE = '''    {operation_name} = "{operation_value}"'''

SEVERITY_ENUM_DEFINITION_TEMPLATE = '''    {severity_name} = "{severity_value}"'''

INPUT_FIELD_TEMPLATE = """    {field_name}: {field_type} = {default_value}"""

OUTPUT_FIELD_TEMPLATE = """    {field_name}: {field_type} = {default_value}"""

INPUT_VALIDATION_TEMPLATE = """        errors = []
        warnings = []

        # Required field validation
        {input_validation_rules}

        return ValidationResult(len(errors) == 0, errors, warnings)"""

OUTPUT_VALIDATION_TEMPLATE = """        errors = []
        warnings = []

        # Required field validation
        {output_validation_rules}

        return ValidationResult(len(errors) == 0, errors, warnings)"""


# Template configurations
TEMPLATES = {
    "consul": {
        "docstring": "Model contracts for Consul API integration",
        "contract_name": "Consul",
        "operation_enum_name": "ConsulOperationType",
        "severity_enum_name": "ConsulSeverity",
        "input_contract_class_name": "ModelContractConsulInput",
        "output_contract_class_name": "ModelContractConsulOutput",
        "validator_class_name": "ConsulContractValidator",
        "operations": [
            {"name": "REGISTER", "value": "register"},
            {"name": "DEREGISTER", "value": "deregister"},
            {"name": "HEALTH_CHECK", "value": "health_check"},
            {"name": "KV_GET", "value": "kv_get"},
            {"name": "KV_SET", "value": "kv_set"},
        ],
        "severities": [
            {"name": "INFO", "value": "info"},
            {"name": "WARNING", "value": "warning"},
            {"name": "ERROR", "value": "error"},
            {"name": "CRITICAL", "value": "critical"},
        ],
        "input_fields": [
            {
                "name": "operation",
                "type": "ConsulOperationType",
                "default": "ConsulOperationType.REGISTER",
            },
            {"name": "service_id", "type": "str"},
            {"name": "service_name", "type": "Optional[str]", "default": "None"},
            {"name": "address", "type": "Optional[str]", "default": "None"},
            {"name": "port", "type": "Optional[int]", "default": "None"},
            {"name": "health_check_url", "type": "Optional[str]", "default": "None"},
            {
                "name": "tags",
                "type": "Optional[List[str]]",
                "default": "field(default_factory=list)",
            },
        ],
        "output_fields": [
            {"name": "success", "type": "bool"},
            {"name": "operation", "type": "ConsulOperationType"},
            {
                "name": "data",
                "type": "Dict[str, Any]",
                "default": "field(default_factory=dict)",
            },
            {"name": "error", "type": "Optional[str]", "default": "None"},
            {"name": "timestamp", "type": "Optional[str]", "default": "None"},
        ],
        "input_validation_rules": [
            "if not self.service_id or not self.service_id.strip():",
            "    errors.append('service_id is required and cannot be empty')",
            "",
            "if not re.match(r'^[a-zA-Z0-9_-]+$', self.service_id):",
            "    errors.append('service_id must contain only alphanumeric characters, hyphens, and underscores')",
            "",
            "# Operation-specific validation",
            "if self.operation == ConsulOperationType.REGISTER:",
            "    if not self.service_name or not self.service_name.strip():",
            "        errors.append('service_name is required for registration')",
            "    ",
            "    if not self.address or not self.address.strip():",
            "        errors.append('address is required for registration')",
            "    else:",
            "        # Validate IP address format",
            "        try:",
            "            from ipaddress import ip_address",
            "            ip_address(self.address)",
            "        except ValueError:",
            "            warnings.append('address does not appear to be a valid IP address')",
            "    ",
            "    if self.port is None:",
            "        errors.append('port is required for registration')",
            "    elif not (1 <= self.port <= 65535):",
            "        errors.append('port must be between 1 and 65535')",
        ],
        "output_validation_rules": [
            "if not isinstance(self.success, bool):",
            "    errors.append('success must be boolean')",
            "",
            "if not self.operation:",
            "    errors.append('operation is required')",
            "",
            "if not isinstance(self.data, dict):",
            "    errors.append('data must be a dictionary')",
            "",
            "if self.success and self.error:",
            "    warnings.append('error should not be set when success is true')",
            "",
            "if not self.success and not self.error:",
            "    warnings.append('error should be provided when success is false')",
        ],
    },
    "validation": {
        "docstring": "Validation system contracts with configurable rules",
        "contract_name": "Validation",
        "operation_enum_name": "ValidationOperation",
        "severity_enum_name": "ValidationSeverity",
        "input_contract_class_name": "ModelContractValidationInput",
        "output_contract_class_name": "ModelContractValidationOutput",
        "validator_class_name": "ValidationContractValidator",
        "operations": [{"name": "VALIDATE", "value": "validate"}],
        "severities": [
            {"name": "INFO", "value": "info"},
            {"name": "WARNING", "value": "warning"},
            {"name": "ERROR", "value": "error"},
            {"name": "CRITICAL", "value": "critical"},
        ],
        "input_fields": [
            {
                "name": "operation",
                "type": "ValidationOperation",
                "default": "ValidationOperation.VALIDATE",
            },
            {"name": "data", "type": "Dict[str, Any]"},
            {
                "name": "rules",
                "type": "List[Dict[str, Any]]",
                "default": "field(default_factory=list)",
            },
        ],
        "output_fields": [
            {"name": "is_valid", "type": "bool"},
            {
                "name": "violations",
                "type": "List[Dict[str, Any]]",
                "default": "field(default_factory=list)",
            },
            {"name": "summary", "type": "str"},
            {"name": "timestamp", "type": "Optional[str]", "default": "None"},
        ],
        "input_validation_rules": [
            "if not isinstance(self.data, dict):",
            "    errors.append('data must be a dictionary')",
            "",
            "if not isinstance(self.rules, list):",
            "    errors.append('rules must be a list')",
            "",
            "# Validate each rule",
            "for rule_data in self.rules:",
            "    if not isinstance(rule_data, dict):",
            "        errors.append(f'Invalid rule format: {{rule_data}}')",
            "        continue",
            "    ",
            "    required_fields = ['rule_id', 'rule_type', 'field_path']",
            "    for field in required_fields:",
            "        if field not in rule_data:",
            "            errors.append(f'Rule missing required field: {{field}}')",
        ],
        "output_validation_rules": [
            "if not isinstance(self.is_valid, bool):",
            "    errors.append('is_valid must be boolean')",
            "",
            "if not isinstance(self.violations, list):",
            "    errors.append('violations must be a list')",
            "",
            "if not isinstance(self.summary, str):",
            "    errors.append('summary must be a string')",
        ],
    },
}


def generate_model_contract_code(
    template_name: str, agent_name: str, task_id: str, recommendations: List[Dict]
) -> str:
    """Generate model contract code from template."""
    template_config = TEMPLATES.get(template_name, TEMPLATES["consul"])

    # Extract template parts
    docstring = template_config["docstring"]
    contract_name = template_config["contract_name"]
    operation_enum_name = template_config["operation_enum_name"]
    severity_enum_name = template_config["severity_enum_name"]
    input_contract_class_name = template_config["input_contract_class_name"]
    output_contract_class_name = template_config["output_contract_class_name"]
    validator_class_name = template_config["validator_class_name"]

    # Generate operation enum definitions
    operation_definitions = []
    for op in template_config["operations"]:
        operation_definitions.append(
            f"{OPERATION_ENUM_DEFINITION_TEMPLATE.format(**op)}"
        )

    # Generate severity enum definitions
    severity_definitions = []
    for sev in template_config["severities"]:
        severity_definitions.append(
            f"{SEVERITY_ENUM_DEFINITION_TEMPLATE.format(**sev)}"
        )

    # Generate input contract fields
    input_contract_fields = []
    for field in template_config["input_fields"]:
        input_contract_fields.append(f"{INPUT_FIELD_TEMPLATE.format(**field)}")

    # Generate output contract fields
    output_contract_fields = []
    for field in template_config["output_fields"]:
        output_contract_fields.append(f"{OUTPUT_FIELD_TEMPLATE.format(**field)}")

    # Generate validation rules
    input_validation = "\n        ".join(template_config["input_validation_rules"])
    output_validation = "\n        ".join(template_config["output_validation_rules"])

    # Build final code
    code = MODEL_CONTRACT_TEMPLATE.format(
        docstring=docstring,
        contract_name=contract_name,
        operation_enum_name=operation_enum_name,
        operation_definitions="\n    ".join(operation_definitions),
        severity_enum_name=severity_enum_name,
        severity_definitions="\n    ".join(severity_definitions),
        input_contract_class_name=input_contract_class_name,
        input_contract_fields="\n    ".join(input_contract_fields),
        input_validation=input_validation,
        output_contract_class_name=output_contract_class_name,
        output_contract_fields="\n    ".join(output_contract_fields),
        output_validation=output_validation,
        validator_class_name=validator_class_name,
    )

    return code
