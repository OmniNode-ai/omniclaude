
from pydantic import BaseModel, Field, ValidationError
from typing import List, Dict, Any, Optional

# 1. Define Pydantic Models
class ValidationRule(BaseModel):
    id: str
    name: str
    description: str
    severity: str # e.g., 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW'
    pattern: Optional[str] = None # Regex or specific string pattern
    expected_value: Optional[Any] = None # For configuration validation
    # Add more rule-specific fields as needed

class Violation(BaseModel):
    rule_id: str
    message: str
    location: Optional[str] = None # e.g., file:line, config_path
    severity: str

class ValidationResult(BaseModel):
    is_compliant: bool
    violations: List[Violation] = Field(default_factory=list)
    summary: str

class ValidationRequest(BaseModel):
    target_type: str # e.g., 'code', 'configuration', 'output'
    target_content: str # The actual code, config (as JSON string), or output
    rules: List[ValidationRule]

class ComplianceReport(BaseModel):
    report_id: str
    timestamp: str
    overall_status: str # e.g., 'COMPLIANT', 'NON_COMPLIANT'
    validation_results: List[ValidationResult] = Field(default_factory=list)
    details: Optional[Dict[str, Any]] = None

# 2. and 3. Implement ValidationAgent class (following agent_debug_intelligence.py pattern)
class AgentValidator:
    def __init__(self):
        # Initialize any necessary components, e.g., AI models, rule engines
        print("AgentValidator initialized.")

    def _evaluate_rule(self, content: str, rule: ValidationRule) -> Optional[Violation]:
        # Placeholder for actual rule evaluation logic
        # This would involve AI model calls, regex matching, etc.
        if rule.pattern and rule.pattern in content:
            return Violation(
                rule_id=rule.id,
                message=f"Content contains forbidden pattern: {rule.pattern}",
                severity=rule.severity,
                location="generic"
            )
        if rule.expected_value is not None and str(rule.expected_value) not in content:
            return Violation(
                rule_id=rule.id,
                message=f"Content does not contain expected value: {rule.expected_value}",
                severity=rule.severity,
                location="generic"
            )
        return None

    def validate_code(self, code: str, rules: List[ValidationRule]) -> ValidationResult:
        violations = []
        for rule in rules:
            violation = self._evaluate_rule(code, rule) # More sophisticated code analysis needed here
            if violation: 
                violations.append(violation)
        
        is_compliant = not bool(violations)
        summary = "Code is compliant." if is_compliant else "Code contains violations."
        return ValidationResult(is_compliant=is_compliant, violations=violations, summary=summary)

    def validate_config(self, config_content: str, rules: List[ValidationRule]) -> ValidationResult:
        violations = []
        try:
            config_dict = json.loads(config_content) # Assuming JSON config
        except json.JSONDecodeError as e:
            return ValidationResult(
                is_compliant=False,
                violations=[Violation(rule_id="json_parse_error", message=f"Invalid JSON configuration: {e}", severity="CRITICAL", location="config_file")],
                summary="Configuration is not valid JSON."
            )

        for rule in rules:
            # Example: check if a specific key has an expected value
            if rule.expected_value and rule.pattern: # Using pattern as a 'key' and expected_value
                config_value = config_dict.get(rule.pattern)
                if config_value != rule.expected_value:
                    violations.append(Violation(
                        rule_id=rule.id,
                        message=f"Config key '{rule.pattern}' has value '{config_value}', expected '{rule.expected_value}'",
                        severity=rule.severity,
                        location=f"config:{rule.pattern}"
                    ))
            # More sophisticated config validation logic here
            violation = self._evaluate_rule(config_content, rule) # Fallback for general pattern match
            if violation: 
                violations.append(violation)

        is_compliant = not bool(violations)
        summary = "Configuration is compliant." if is_compliant else "Configuration contains violations."
        return ValidationResult(is_compliant=is_compliant, violations=violations, summary=summary)

    def validate_output(self, output_content: str, rules: List[ValidationRule]) -> ValidationResult:
        violations = []
        for rule in rules:
            violation = self._evaluate_rule(output_content, rule) # More sophisticated output analysis needed
            if violation: 
                violations.append(violation)

        is_compliant = not bool(violations)
        summary = "Output is compliant." if is_compliant else "Output contains violations."
        return ValidationResult(is_compliant=is_compliant, violations=violations, summary=summary)

    def process_validation_request(self, request: ValidationRequest) -> ComplianceReport:
        # Simple example of combining validation results into a ComplianceReport
        if request.target_type == 'code':
            result = self.validate_code(request.target_content, request.rules)
        elif request.target_type == 'configuration':
            import json # local import for config parsing
            result = self.validate_config(request.target_content, request.rules)
        elif request.target_type == 'output':
            result = self.validate_output(request.target_content, request.rules)
        else:
            result = ValidationResult(is_compliant=False, violations=[Violation(rule_id="unsupported_type", message=f"Unsupported target type: {request.target_type}", severity="CRITICAL")])

        overall_status = "COMPLIANT" if result.is_compliant else "NON_COMPLIANT"
        import datetime
        report_id = f"report-{datetime.datetime.now().isoformat()}"

        return ComplianceReport(
            report_id=report_id,
            timestamp=datetime.datetime.now().isoformat(),
            overall_status=overall_status,
            validation_results=[result]
        )

# Example usage (for demonstration, not part of the 'fixed code' directly)
# if __name__ == '__main__':
#     validator = AgentValidator()
    
#     # Example Code Validation
#     code_rules = [
#         ValidationRule(id="CR001", name="No Debug Prints", description="Ensure no 'print(' statements are in production code", severity="HIGH", pattern="print(")
#     ]
#     code_content = "def my_func():\n    print('Hello Debug')\n    return 1"
#     code_request = ValidationRequest(target_type="code", target_content=code_content, rules=code_rules)
#     code_report = validator.process_validation_request(code_request)
#     print("\nCode Validation Report:", code_report.model_dump_json(indent=2))

#     # Example Config Validation
#     config_rules = [
#         ValidationRule(id="CF001", name="DB Host Check", description="Ensure database host is production.db", severity="CRITICAL", pattern="db_host", expected_value="production.db")
#     ]
#     config_content = '{"db_host": "dev.db", "port": 5432}'
#     config_request = ValidationRequest(target_type="configuration", target_content=config_content, rules=config_rules)
#     config_report = validator.process_validation_request(config_request)
#     print("\nConfig Validation Report:", config_report.model_dump_json(indent=2))
