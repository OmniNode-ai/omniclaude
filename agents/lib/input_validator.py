"""
Input Validation and Sanitization

Comprehensive input validation, sanitization, and security checks for
user inputs to prevent malicious content and ensure data quality.
"""

import html
import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union


class ValidationSeverity(Enum):
    """Validation severity levels."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class InputType(Enum):
    """Input types for validation."""

    USER_PROMPT = "user_prompt"
    TASK_DATA = "task_data"
    WORKSPACE_PATH = "workspace_path"
    RAG_QUERY = "rag_query"
    JSON_DATA = "json_data"
    FILE_PATH = "file_path"
    URL = "url"


@dataclass
class ValidationResult:
    """Result of input validation."""

    is_valid: bool
    sanitized_input: Any
    issues: List[str]
    warnings: List[str]
    errors: List[str]
    metadata: Dict[str, Any]


@dataclass
class ValidationRule:
    """Validation rule configuration."""

    name: str
    pattern: Optional[str] = None
    max_length: Optional[int] = None
    min_length: Optional[int] = None
    allowed_chars: Optional[str] = None
    forbidden_patterns: Optional[List[str]] = None
    severity: ValidationSeverity = ValidationSeverity.ERROR
    description: str = ""


class InputValidator:
    """
    Comprehensive input validation and sanitization.

    Features:
    - Input sanitization
    - Security pattern detection
    - Length and format validation
    - Malicious content detection
    - Data quality checks
    """

    def __init__(self):
        self._setup_validation_rules()
        self._setup_security_patterns()

    def _setup_validation_rules(self):
        """Setup default validation rules."""
        self.rules = {
            InputType.USER_PROMPT: [
                ValidationRule(
                    name="max_length",
                    max_length=10000,
                    description="User prompt too long",
                ),
                ValidationRule(
                    name="min_length", min_length=1, description="User prompt too short"
                ),
                ValidationRule(
                    name="no_script_tags",
                    forbidden_patterns=[
                        r"<script[^>]*>.*?</script>",
                        r"<script[^>]*/>",
                    ],
                    description="Script tags not allowed",
                ),
                ValidationRule(
                    name="no_executable_content",
                    forbidden_patterns=[
                        r"javascript:",
                        r"data:text/html",
                        r"vbscript:",
                    ],
                    description="Executable content not allowed",
                ),
            ],
            InputType.TASK_DATA: [
                ValidationRule(name="valid_json", description="Must be valid JSON"),
                ValidationRule(
                    name="max_size", max_length=50000, description="Task data too large"
                ),
            ],
            InputType.WORKSPACE_PATH: [
                ValidationRule(
                    name="path_traversal",
                    forbidden_patterns=[r"\.\./", r"\.\.\\", r"//", r"\\\\"],
                    description="Path traversal not allowed",
                ),
                ValidationRule(
                    name="valid_path",
                    pattern=r"^[a-zA-Z0-9_\-/\\:\.]+$",
                    description="Invalid path characters",
                ),
            ],
            InputType.RAG_QUERY: [
                ValidationRule(
                    name="max_length", max_length=1000, description="RAG query too long"
                ),
                ValidationRule(
                    name="min_length", min_length=3, description="RAG query too short"
                ),
                ValidationRule(
                    name="no_sql_injection",
                    forbidden_patterns=[
                        r"(\b(SELECT|INSERT|UPDATE|DELETE|DROP|CREATE|ALTER)\b)",
                        r"(\b(UNION|OR|AND)\b.*\b(SELECT|INSERT|UPDATE|DELETE)\b)",
                    ],
                    description="SQL injection patterns detected",
                ),
            ],
            InputType.JSON_DATA: [
                ValidationRule(name="valid_json", description="Must be valid JSON"),
                ValidationRule(name="max_depth", description="JSON nesting too deep"),
            ],
            InputType.FILE_PATH: [
                ValidationRule(
                    name="path_traversal",
                    forbidden_patterns=[r"\.\./", r"\.\.\\", r"//", r"\\\\"],
                    description="Path traversal not allowed",
                ),
                ValidationRule(
                    name="allowed_extensions",
                    pattern=r"\.(py|js|ts|json|yaml|yml|md|txt|csv)$",
                    description="File extension not allowed",
                ),
            ],
            InputType.URL: [
                ValidationRule(
                    name="valid_url",
                    pattern=r"^https?://[a-zA-Z0-9\-\.]+\.[a-zA-Z]{2,}(/.*)?$",
                    description="Invalid URL format",
                ),
                ValidationRule(
                    name="no_localhost",
                    forbidden_patterns=[r"localhost", r"127\.0\.0\.1", r"0\.0\.0\.0"],
                    description="Localhost URLs not allowed",
                ),
            ],
        }

    def _setup_security_patterns(self):
        """Setup security threat patterns."""
        self.security_patterns = {
            "xss": [
                r"<script[^>]*>.*?</script>",
                r"<script[^>]*/>",
                r"javascript:",
                r"vbscript:",
                r"data:text/html",
                r"on\w+\s*=",
                r"<iframe[^>]*>",
                r"<object[^>]*>",
                r"<embed[^>]*>",
            ],
            "sql_injection": [
                r"(\b(SELECT|INSERT|UPDATE|DELETE|DROP|CREATE|ALTER)\b)",
                r"(\b(UNION|OR|AND)\b.*\b(SELECT|INSERT|UPDATE|DELETE)\b)",
                r"(\b(EXEC|EXECUTE)\b)",
                r"(\b(UNION|OR|AND)\b.*\b(SELECT|INSERT|UPDATE|DELETE)\b)",
                r"(\b(UNION|OR|AND)\b.*\b(SELECT|INSERT|UPDATE|DELETE)\b)",
                r"(\d+\s*(=|!=|<|>)\s*\d+)",  # Numeric comparisons like "1=1"
                r"(\'\s*(OR|AND)\s*\'\s*=\s*\')",  # String comparisons like "' OR ''='"
            ],
            "path_traversal": [
                r"\.\./",
                r"\.\.\\",
                r"//",
                r"\\\\",
                r"%2e%2e%2f",
                r"%2e%2e%5c",
            ],
            "command_injection": [
                r"[;&|`$]",
                r"(\b(rm|del|format|fdisk|mkfs)\b)",
                r"(\b(cat|type|more|less|head|tail)\b)",
                r"(\b(wget|curl|nc|netcat)\b)",
                r"(\b(python|perl|ruby|php|node)\b)",
            ],
            "malicious_urls": [
                r"javascript:",
                r"data:",
                r"vbscript:",
                r"file:",
                r"ftp:",
                r"gopher:",
            ],
        }

    async def validate_and_sanitize(
        self,
        user_input: Optional[Union[str, Dict, List]] = None,
        input_type: Optional[InputType] = None,
        strict_mode: bool = True,
        user_prompt: Optional[str] = None,
        tasks_data: Optional[Dict] = None,
    ) -> Union[ValidationResult, Dict[str, Any]]:
        """
        Validate and sanitize user input.

        Args:
            user_input: Input to validate
            input_type: Type of input for appropriate validation
            strict_mode: Whether to use strict validation
            user_prompt: User prompt (alternative calling pattern)
            tasks_data: Tasks data (alternative calling pattern)

        Returns:
            ValidationResult with validation status and sanitized input, or dict for prompt/tasks pattern
        """
        # Handle alternative calling pattern with user_prompt and tasks_data
        if user_prompt is not None or tasks_data is not None:
            deficiencies = []

            # Validate prompt
            if user_prompt is not None:
                if not user_prompt or not user_prompt.strip():
                    deficiencies.append("User prompt cannot be empty")
                sanitized_prompt = (
                    self._sanitize_string(user_prompt, InputType.USER_PROMPT)
                    if user_prompt
                    else ""
                )
            else:
                deficiencies.append("User prompt is required")
                sanitized_prompt = ""

            # Validate tasks data
            if tasks_data is not None:
                sanitized_tasks = (
                    self._sanitize_dict(tasks_data, InputType.TASK_DATA)
                    if tasks_data
                    else {}
                )
            else:
                sanitized_tasks = {}

            return {
                "is_valid": len(deficiencies) == 0,
                "sanitized_prompt": sanitized_prompt,
                "sanitized_tasks": sanitized_tasks,
                "deficiencies": deficiencies,
            }

        # Original calling pattern
        if user_input is None or input_type is None:
            raise ValueError(
                "user_input and input_type are required if not using prompt/tasks pattern"
            )

        issues = []
        warnings = []
        errors = []
        metadata = {
            "input_type": input_type.value,
            "original_length": (
                len(str(user_input)) if isinstance(user_input, str) else 0
            ),
            "validation_timestamp": None,
        }

        try:
            # Convert input to string for validation
            if isinstance(user_input, (dict, list)):
                input_str = json.dumps(user_input)
            else:
                input_str = str(user_input)

            # Apply type-specific validation rules
            if input_type in self.rules:
                for rule in self.rules[input_type]:
                    issue = self._validate_rule(input_str, rule)
                    if issue:
                        if rule.severity == ValidationSeverity.ERROR:
                            errors.append(issue)
                        elif rule.severity == ValidationSeverity.WARNING:
                            warnings.append(issue)
                        else:
                            issues.append(issue)

            # Security pattern detection
            security_issues = self._detect_security_threats(input_str)
            if security_issues:
                errors.extend(security_issues)

            # Sanitize input
            sanitized_input = self._sanitize_input(user_input, input_type)

            # Check if validation passed
            is_valid = len(errors) == 0 and (not strict_mode or len(warnings) == 0)

            metadata["validation_timestamp"] = self._get_timestamp()

            return ValidationResult(
                is_valid=is_valid,
                sanitized_input=sanitized_input,
                issues=issues,
                warnings=warnings,
                errors=errors,
                metadata=metadata,
            )

        except Exception as e:
            return ValidationResult(
                is_valid=False,
                sanitized_input=user_input,
                issues=[],
                warnings=[],
                errors=[f"Validation error: {str(e)}"],
                metadata=metadata,
            )

    def _validate_rule(self, input_str: str, rule: ValidationRule) -> Optional[str]:
        """Validate input against a specific rule."""
        # Length validation
        if rule.max_length and len(input_str) > rule.max_length:
            return f"{rule.description}: {len(input_str)} > {rule.max_length}"

        if rule.min_length and len(input_str) < rule.min_length:
            return f"{rule.description}: {len(input_str)} < {rule.min_length}"

        # Pattern validation
        if rule.pattern:
            # Use search for patterns that don't anchor to start (e.g., file extensions)
            # Use match for patterns that anchor to start with ^
            if rule.pattern.startswith("^"):
                if not re.match(rule.pattern, input_str):
                    return f"{rule.description}: pattern mismatch"
            else:
                if not re.search(rule.pattern, input_str):
                    return f"{rule.description}: pattern mismatch"

        # Forbidden patterns
        if rule.forbidden_patterns:
            for pattern in rule.forbidden_patterns:
                if re.search(pattern, input_str, re.IGNORECASE):
                    return f"{rule.description}: forbidden pattern detected"

        # Character validation
        if rule.allowed_chars:
            for char in input_str:
                if char not in rule.allowed_chars:
                    return f"{rule.description}: invalid character '{char}'"

        return None

    def _detect_security_threats(self, input_str: str) -> List[str]:
        """Detect security threats in input."""
        threats = []

        for threat_type, patterns in self.security_patterns.items():
            for pattern in patterns:
                if re.search(pattern, input_str, re.IGNORECASE):
                    # Skip path_traversal "//" pattern if it's part of a URL protocol (://)
                    if (
                        threat_type == "path_traversal"
                        and pattern == r"//"
                        and "://" in input_str
                    ):
                        continue
                    threats.append(f"Security threat detected: {threat_type} pattern")
                    break

        return threats

    def _sanitize_input(
        self, user_input: Union[str, Dict, List], input_type: InputType
    ) -> Any:
        """Sanitize input based on type."""
        if isinstance(user_input, str):
            return self._sanitize_string(user_input, input_type)
        elif isinstance(user_input, dict):
            return self._sanitize_dict(user_input, input_type)
        else:
            # user_input is a list
            return self._sanitize_list(user_input, input_type)

    def _sanitize_string(self, input_str: str, input_type: InputType) -> str:
        """Sanitize string input."""
        # HTML escape
        sanitized = html.escape(input_str, quote=True)

        # Remove null bytes
        sanitized = sanitized.replace("\x00", "")

        # Normalize whitespace
        sanitized = re.sub(r"\s+", " ", sanitized).strip()

        # Type-specific sanitization
        if input_type == InputType.USER_PROMPT:
            # Remove potential script tags
            sanitized = re.sub(
                r"<script[^>]*>.*?</script>",
                "",
                sanitized,
                flags=re.IGNORECASE | re.DOTALL,
            )
            sanitized = re.sub(r"<script[^>]*/>", "", sanitized, flags=re.IGNORECASE)

        elif input_type == InputType.WORKSPACE_PATH:
            # Normalize path separators
            sanitized = sanitized.replace("\\", "/")
            # Remove multiple slashes
            sanitized = re.sub(r"/+", "/", sanitized)

        elif input_type == InputType.RAG_QUERY:
            # Remove SQL injection patterns
            sanitized = re.sub(
                r"(\b(SELECT|INSERT|UPDATE|DELETE|DROP|CREATE|ALTER)\b)",
                "",
                sanitized,
                flags=re.IGNORECASE,
            )
            sanitized = re.sub(r"[;&|`$]", "", sanitized)

        return sanitized

    def _sanitize_dict(self, input_dict: Dict, input_type: InputType) -> Dict:
        """Sanitize dictionary input."""
        sanitized: Dict[Any, Any] = {}
        for key, value in input_dict.items():
            # Sanitize key
            sanitized_key = self._sanitize_string(str(key), input_type)

            # Sanitize value based on type
            sanitized_value: Any
            if isinstance(value, str):
                sanitized_value = self._sanitize_string(value, input_type)
            elif isinstance(value, dict):
                sanitized_value = self._sanitize_dict(value, input_type)
            elif isinstance(value, list):
                sanitized_value = self._sanitize_list(value, input_type)
            else:
                sanitized_value = value

            sanitized[sanitized_key] = sanitized_value

        return sanitized

    def _sanitize_list(self, input_list: List, input_type: InputType) -> List[Any]:
        """Sanitize list input."""
        sanitized: List[Any] = []
        for item in input_list:
            if isinstance(item, str):
                sanitized.append(self._sanitize_string(item, input_type))
            elif isinstance(item, dict):
                sanitized.append(self._sanitize_dict(item, input_type))
            elif isinstance(item, list):
                sanitized.append(self._sanitize_list(item, input_type))
            else:
                sanitized.append(item)

        return sanitized

    async def sanitize_prompt(self, prompt: str) -> str:
        """
        Sanitize user prompt for safe processing.

        Args:
            prompt: User prompt to sanitize

        Returns:
            Sanitized prompt
        """
        result = await self.validate_and_sanitize(prompt, InputType.USER_PROMPT)
        assert isinstance(result, ValidationResult)
        return str(result.sanitized_input)

    async def validate_json_input(self, json_str: str) -> Tuple[bool, Any]:
        """
        Validate and parse JSON input.

        Args:
            json_str: JSON string to validate

        Returns:
            Tuple of (is_valid, parsed_data)
        """
        try:
            parsed = json.loads(json_str)
            result = await self.validate_and_sanitize(parsed, InputType.JSON_DATA)
            assert isinstance(result, ValidationResult)
            return result.is_valid, result.sanitized_input
        except json.JSONDecodeError:
            return False, None

    async def validate_file_path(self, file_path: str) -> Tuple[bool, str]:
        """
        Validate file path for security.

        Args:
            file_path: File path to validate

        Returns:
            Tuple of (is_valid, sanitized_path)
        """
        result = await self.validate_and_sanitize(file_path, InputType.FILE_PATH)
        assert isinstance(result, ValidationResult)
        return result.is_valid, str(result.sanitized_input)

    async def validate_url(self, url: str) -> Tuple[bool, str]:
        """
        Validate URL for security.

        Args:
            url: URL to validate

        Returns:
            Tuple of (is_valid, sanitized_url)
        """
        result = await self.validate_and_sanitize(url, InputType.URL)
        assert isinstance(result, ValidationResult)
        return result.is_valid, str(result.sanitized_input)

    def _get_timestamp(self) -> str:
        """Get current timestamp."""
        from datetime import datetime

        return datetime.now().isoformat()

    def get_validation_stats(self) -> Dict[str, Any]:
        """Get validation statistics."""
        return {
            "rules_configured": sum(len(rules) for rules in self.rules.values()),
            "security_patterns": sum(
                len(patterns) for patterns in self.security_patterns.values()
            ),
            "input_types_supported": len(self.rules),
            "threat_types_detected": len(self.security_patterns),
        }


# Global input validator instance
input_validator = InputValidator()


# Convenience functions
async def validate_and_sanitize(
    user_input: Union[str, Dict, List], input_type: InputType, strict_mode: bool = True
) -> ValidationResult:
    """Validate and sanitize user input."""
    result = await input_validator.validate_and_sanitize(
        user_input, input_type, strict_mode
    )
    assert isinstance(result, ValidationResult)
    return result


async def sanitize_prompt(prompt: str) -> str:
    """Sanitize user prompt for safe processing."""
    return await input_validator.sanitize_prompt(prompt)


async def validate_json_input(json_str: str) -> Tuple[bool, Any]:
    """Validate and parse JSON input."""
    return await input_validator.validate_json_input(json_str)


async def validate_file_path(file_path: str) -> Tuple[bool, str]:
    """Validate file path for security."""
    return await input_validator.validate_file_path(file_path)


async def validate_url(url: str) -> Tuple[bool, str]:
    """Validate URL for security."""
    return await input_validator.validate_url(url)


def get_validation_stats() -> Dict[str, Any]:
    """Get validation statistics."""
    return input_validator.get_validation_stats()
