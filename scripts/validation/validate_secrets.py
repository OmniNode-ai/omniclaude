#!/usr/bin/env python3
"""
Secret Detection Validator for OmniClaude

Validates that:
1. No hardcoded secrets (passwords, API keys, tokens) exist in Python files
2. All secrets are properly stored in .env files
3. Code uses environment variables or secure configuration instead of hardcoded values

Common secret patterns detected:
- API keys (api_key, API_KEY)
- Passwords (password, PASSWORD, pwd)
- Tokens (token, TOKEN, auth_token, access_token)
- Connection strings (connection_string, DATABASE_URL)
- AWS credentials (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY)
- Generic secrets (secret, SECRET)

Uses AST parsing for reliable detection of secret patterns and their values.

Adapted from omnibase_core secret detection patterns.
"""

from __future__ import annotations

import ast
import os
import re
import sys
from pathlib import Path
from typing import Final, NamedTuple


class BypassChecker:
    """Unified bypass comment detection for security validators.

    Provides consistent bypass checking across all security validation tools.
    Supports both file-level bypasses (anywhere in file) and line-level
    bypasses (inline with specific violations).
    """

    @staticmethod
    def check_line_bypass(line: str, bypass_patterns: list[str]) -> bool:
        """Check if a specific line has an inline bypass comment."""
        return any(pattern in line for pattern in bypass_patterns)

    @staticmethod
    def check_file_bypass(
        content_lines: list[str], bypass_patterns: list[str], max_lines: int = 10
    ) -> bool:
        """Check if file has a bypass comment in the header."""
        for line in content_lines[:max_lines]:
            stripped = line.strip()
            if stripped.startswith("#"):
                if any(pattern in line for pattern in bypass_patterns):
                    return True
        return False

    @staticmethod
    def extract_bypass_reason(line: str) -> str:
        """Extract the reason/justification from a bypass comment."""
        if "#" not in line:
            return ""
        comment_start = line.index("#")
        return line[comment_start:].strip()


class SecretViolation(NamedTuple):
    """Represents a secret detection violation."""

    file_path: str
    line_number: int
    column: int
    secret_name: str
    violation_type: str
    suggestion: str


# Constants
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB - prevent DoS attacks

# Bypass patterns for allowing intentional hardcoded secrets (e.g., test fixtures)
BYPASS_PATTERNS: Final[list[str]] = [
    "secret-ok:",
    "password-ok:",
    "hardcoded-ok:",
    "nosec",  # Common security scanner bypass
    "noqa: secrets",  # Another common bypass pattern
]

# Pre-compiled regex patterns for performance
COMPILED_SECRET_PATTERNS: Final[list[re.Pattern[str]]] = [
    # API Keys
    re.compile(r".*api[_-]?key.*", re.IGNORECASE),
    re.compile(r".*apikey.*", re.IGNORECASE),
    # Passwords
    re.compile(r".*password.*", re.IGNORECASE),
    re.compile(r".*passwd.*", re.IGNORECASE),
    re.compile(r".*pwd.*", re.IGNORECASE),
    # Tokens
    re.compile(r".*token.*", re.IGNORECASE),
    re.compile(r".*auth.*token.*", re.IGNORECASE),
    re.compile(r".*access.*token.*", re.IGNORECASE),
    re.compile(r".*refresh.*token.*", re.IGNORECASE),
    re.compile(r".*bearer.*", re.IGNORECASE),
    # AWS Credentials
    re.compile(r".*aws.*access.*key.*", re.IGNORECASE),
    re.compile(r".*aws.*secret.*key.*", re.IGNORECASE),
    re.compile(r".*aws.*session.*token.*", re.IGNORECASE),
    re.compile(r"AKIA[0-9A-Z]{16}"),  # AWS Access Key ID pattern
    # Database & Connection Strings
    re.compile(r".*connection.*string.*", re.IGNORECASE),
    re.compile(r".*database.*url.*", re.IGNORECASE),
    re.compile(r".*db.*url.*", re.IGNORECASE),
    re.compile(r".*dsn.*", re.IGNORECASE),
    # Generic Secrets
    re.compile(r".*secret.*", re.IGNORECASE),
    re.compile(r".*private.*key.*", re.IGNORECASE),
    re.compile(r".*encryption.*key.*", re.IGNORECASE),
    re.compile(r".*signing.*key.*", re.IGNORECASE),
    # OAuth & Authentication
    re.compile(r".*client.*secret.*", re.IGNORECASE),
    re.compile(r".*consumer.*secret.*", re.IGNORECASE),
    re.compile(r".*app.*secret.*", re.IGNORECASE),
    # SSH & Keys
    re.compile(r".*ssh.*key.*", re.IGNORECASE),
    re.compile(r".*rsa.*key.*", re.IGNORECASE),
    # Certificate & TLS
    re.compile(r".*certificate.*", re.IGNORECASE),
    re.compile(r".*cert.*key.*", re.IGNORECASE),
    re.compile(r".*tls.*key.*", re.IGNORECASE),
]


class PythonSecretValidator(ast.NodeVisitor):
    """AST visitor to validate secrets are not hardcoded in Python files."""

    def __init__(self, file_path: str, file_lines: list[str] | None = None):
        self.file_path = file_path
        self.violations: list[SecretViolation] = []
        self.file_lines = file_lines or []
        self.class_stack: list[ast.ClassDef] = []
        self.bypass_usage: list[tuple[str, int, str]] = []

        # Exception patterns - legitimate use cases that shouldn't be flagged
        self.exceptions = {
            "password_field",
            "password_validator",
            "password_hash",
            "password_pattern",
            "password_regex",
            "token_type",
            "token_validator",
            "secret_name",
            "secret_type",
            "api_key_name",
            "example_password",
            "sample_password",
            "test_password",
            "dummy_password",
            "fake_password",
            "password_min_length",
            "password_max_length",
            "token_expiry",
            "token_lifetime",
            "secret_length",
            "password_type",
            "password_updated_at",
            "password_created_at",
            "token_created_at",
            "password_error",
            "token_error",
            "secret_error",
        }

        # Metadata patterns - recognize configuration/metadata assignments
        self.metadata_patterns = {
            "password_strength": [
                "weak",
                "very_weak",
                "medium",
                "moderate",
                "strong",
                "very_strong",
            ],
            "secret_rotation": [
                "manual",
                "automatic",
                "disabled",
                "manual_or_operator",
            ],
            "auth_type": ["bearer", "api_key", "oauth", "basic", "none"],
            "token_type": ["bearer", "refresh", "access", "id_token"],
            "api_key": ["api_key"],
            "bearer": ["bearer"],
            "password": ["password"],
            "secret": ["secret"],
        }

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Track class definitions to detect Enum contexts."""
        self.class_stack.append(node)
        self.generic_visit(node)
        self.class_stack.pop()

    def visit_Assign(self, node: ast.Assign) -> None:
        """Visit assignments to detect hardcoded secrets."""
        for target in node.targets:
            if isinstance(target, ast.Name):
                field_name = target.id
                self._check_secret_assignment(
                    field_name, node.value, node.lineno, node.col_offset
                )
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        """Visit annotated assignments (field definitions with values)."""
        if isinstance(node.target, ast.Name) and node.value:
            field_name = node.target.id
            self._check_secret_assignment(
                field_name, node.value, node.lineno, node.col_offset
            )
        self.generic_visit(node)

    def visit_keyword(self, node: ast.keyword) -> None:
        """Visit keyword arguments in function calls."""
        if node.arg:
            self._check_secret_assignment(
                node.arg, node.value, node.value.lineno, node.value.col_offset
            )
        self.generic_visit(node)

    def _is_in_enum_class(self) -> bool:
        """Check if current assignment is inside an Enum class definition."""
        for class_node in self.class_stack:
            for base in class_node.bases:
                if isinstance(base, ast.Name) and "Enum" in base.id:
                    return True
                if isinstance(base, ast.Attribute) and "Enum" in base.attr:
                    return True
        return False

    def _is_metadata_assignment(self, var_name: str, value: str) -> bool:
        """Check if assignment is metadata (configuration), not an actual secret."""
        var_lower = var_name.lower()
        value_lower = value.lower()

        for pattern, valid_values in self.metadata_patterns.items():
            if pattern in var_lower:
                if value_lower in valid_values:
                    return True

        return False

    def _has_inline_bypass(self, line_number: int) -> bool:
        """Check if line has an inline bypass comment."""
        if not self.file_lines or line_number < 1 or line_number > len(self.file_lines):
            return False

        line = self.file_lines[line_number - 1]
        is_bypass = BypassChecker.check_line_bypass(line, BYPASS_PATTERNS)

        if is_bypass:
            reason = BypassChecker.extract_bypass_reason(line)
            self.bypass_usage.append((self.file_path, line_number, reason))

        return is_bypass

    def _check_secret_assignment(
        self, field_name: str, value_node: ast.AST, line_number: int, column: int
    ) -> None:
        """Check if a field assignment contains a hardcoded secret."""
        if field_name.lower() in self.exceptions:
            return

        if not self._matches_secret_patterns(field_name):
            return

        if self._is_in_enum_class():
            return

        if self._has_inline_bypass(line_number):
            return

        if self._is_hardcoded_value(value_node):
            value_str = ""
            if isinstance(value_node, ast.Constant) and isinstance(
                value_node.value, str
            ):
                value_str = value_node.value

            if value_str and self._is_metadata_assignment(field_name, value_str):
                return

            suggestion = (
                f"Use environment variable instead. "
                f"Example: os.getenv('{field_name.upper()}')"
            )

            self.violations.append(
                SecretViolation(
                    file_path=self.file_path,
                    line_number=line_number,
                    column=column,
                    secret_name=field_name,
                    violation_type="hardcoded_secret",
                    suggestion=suggestion,
                )
            )

    def _matches_secret_patterns(self, field_name: str) -> bool:
        """Check if field name matches any secret pattern."""
        return any(pattern.match(field_name) for pattern in COMPILED_SECRET_PATTERNS)

    def _is_hardcoded_value(self, value_node: ast.AST) -> bool:
        """Check if value is a hardcoded string (not from environment or config)."""
        if isinstance(value_node, ast.Constant) and isinstance(value_node.value, str):
            value = value_node.value
            if not value or value in ["", "YOUR_KEY_HERE", "CHANGEME", "TODO"]:
                return False
            if len(value) < 3:
                return False
            return True

        if isinstance(value_node, ast.JoinedStr):
            for joined_value in value_node.values:
                if isinstance(joined_value, ast.Constant) and isinstance(
                    joined_value.value, str
                ):
                    if len(joined_value.value) >= 3:
                        return True

        if isinstance(value_node, ast.Call):
            func_name = self._get_call_func_name(value_node.func)
            if func_name in [
                "getenv",
                "os.getenv",
                "environ.get",
                "os.environ.get",
                "get_service",
                "get",
            ]:
                return False

        if isinstance(value_node, ast.Subscript):
            if isinstance(value_node.value, ast.Attribute):
                if value_node.value.attr == "environ":
                    return False
            if isinstance(value_node.value, ast.Name):
                if value_node.value.id == "environ":
                    return False

        return False

    def _get_call_func_name(self, func_node: ast.AST) -> str:
        """Extract the function name from a call node."""
        if isinstance(func_node, ast.Name):
            return func_node.id
        elif isinstance(func_node, ast.Attribute):
            if isinstance(func_node.value, ast.Name):
                return f"{func_node.value.id}.{func_node.attr}"
            elif isinstance(func_node.value, ast.Attribute):
                if isinstance(func_node.value.value, ast.Name):
                    return f"{func_node.value.attr}.{func_node.attr}"
            return func_node.attr
        return ""


class SecretValidator:
    """Validates that Python files don't contain hardcoded secrets."""

    def __init__(self) -> None:
        self.violations: list[SecretViolation] = []
        self.checked_files = 0
        self.bypass_usage: list[tuple[str, int, str]] = []

    def validate_python_file(self, python_path: Path, content_lines: list[str]) -> bool:
        """Validate a Python file for hardcoded secrets."""
        if not python_path.exists():
            return True

        if not python_path.is_file():
            return True

        if not os.access(python_path, os.R_OK):
            print(f"Warning: Cannot read file: {python_path}")
            return True

        try:
            file_size = python_path.stat().st_size
            if file_size > MAX_FILE_SIZE:
                print(
                    f"Warning: File too large ({file_size} bytes), max: {MAX_FILE_SIZE}"
                )
                return True
        except OSError:
            return True

        try:
            with open(python_path, encoding="utf-8") as f:
                content = f.read()
        except (UnicodeDecodeError, PermissionError, OSError):
            return True

        if not content.strip():
            return True

        if self._has_bypass_comment(content_lines):
            return True

        self.checked_files += 1

        ast_validator = PythonSecretValidator(str(python_path), content_lines)
        try:
            tree = ast.parse(content, filename=str(python_path))
            ast_validator.visit(tree)

            self.violations.extend(ast_validator.violations)
            self.bypass_usage.extend(ast_validator.bypass_usage)

        except SyntaxError:
            pass
        except Exception as e:
            print(f"Warning: Error during AST validation of {python_path}: {e}")

        return len(ast_validator.violations) == 0

    def _has_bypass_comment(self, content_lines: list[str]) -> bool:
        """Check if file has a bypass comment at the top."""
        return BypassChecker.check_file_bypass(content_lines, BYPASS_PATTERNS)

    def print_results(self) -> None:
        """Print validation results."""
        if self.violations:
            print("Secret Validation FAILED")
            print("=" * 80)
            print(
                f"Found {len(self.violations)} hardcoded secrets in {self.checked_files} files:"
            )
            print()

            by_file: dict[str, list[SecretViolation]] = {}
            for violation in self.violations:
                if violation.file_path not in by_file:
                    by_file[violation.file_path] = []
                by_file[violation.file_path].append(violation)

            for file_path, file_violations in by_file.items():
                print(f"File: {file_path}")
                for violation in file_violations:
                    print(
                        f"  Line {violation.line_number}:{violation.column} - "
                        f"Secret '{violation.secret_name}' is hardcoded"
                    )
                    print(f"      {violation.suggestion}")
                print()

            print("How to fix:")
            print("   1. Move secrets to .env file:")
            print("      Example: API_KEY=your_secret_key")
            print("   2. Load from environment in code:")
            print("      Example: api_key = os.getenv('API_KEY')")
            print("   3. For test fixtures, add bypass comment:")
            print("      Example: # secret-ok: test fixture")
            print("   4. Or use inline bypass:")
            print("      Example: password = 'test'  # noqa: secrets")
            print()
        else:
            print(f"Secret Validation PASSED ({self.checked_files} files checked)")


def main() -> int:
    """Main entry point for the validation hook."""
    try:
        import argparse

        parser = argparse.ArgumentParser(
            description="Validate Python files for hardcoded secrets"
        )
        parser.add_argument("files", nargs="*", help="Python files to validate")
        parser.add_argument(
            "--report-bypasses",
            action="store_true",
            help="Report all bypass comment usage",
        )
        args = parser.parse_args()

        validator = SecretValidator()

        # If no files provided, scan src/ directory
        if not args.files:
            src_dir = Path(__file__).parent.parent.parent / "src"
            if src_dir.exists():
                python_files = list(src_dir.rglob("*.py"))
            else:
                python_files = []
        else:
            file_paths = [Path(f) for f in args.files]
            python_files = [f for f in file_paths if f.suffix == ".py"]

        if not python_files:
            print("Secret Validation PASSED (no Python files to check)")
            return 0

        success = True
        for python_path in python_files:
            try:
                with open(python_path, encoding="utf-8") as f:
                    content_lines = f.readlines()
            except (UnicodeDecodeError, PermissionError, OSError):
                content_lines = []

            if not validator.validate_python_file(python_path, content_lines):
                success = False

        validator.print_results()

        return 0 if success else 1

    except KeyboardInterrupt:
        print("\nError: Validation interrupted by user")
        return 1
    except Exception as e:
        print(f"Error: Unexpected error in main function: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
