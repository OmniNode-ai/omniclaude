#!/usr/bin/env python3
"""
Post-Tool Use Metrics Collector

Fast rule-based quality scoring and performance metrics for PostToolUse hook.
Target: <12ms overhead per tool execution.

Success Classification:
- full_success: No errors, all checks pass
- partial_success: Warnings present but operation succeeded
- failed: Errors detected or operation failed

Quality Scoring (rule-based, 0-1):
- Naming conventions: 0.25 weight
- Type safety: 0.25 weight
- Documentation: 0.25 weight
- Error handling: 0.25 weight

Performance Metrics:
- execution_time_ms: Tool execution duration
- bytes_written: Content size
- lines_changed: Lines added/modified
- files_modified: Number of files affected
"""

import re
import time
from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class QualityMetrics:
    """Quality metrics for code analysis."""

    quality_score: float  # 0-1
    naming_conventions: str  # pass, warning, fail
    type_safety: str  # pass, warning, fail
    documentation: str  # pass, warning, fail
    error_handling: str  # pass, warning, fail


@dataclass
class PerformanceMetrics:
    """Performance metrics for tool execution."""

    execution_time_ms: float
    bytes_written: int
    lines_changed: int
    files_modified: int


@dataclass
class ExecutionAnalysis:
    """Analysis of execution behavior."""

    deviation_from_expected: str  # none, minor, major
    required_retries: int
    error_recovery_applied: bool


@dataclass
class Metadata:
    """Complete metadata for PostToolUse."""

    success_classification: str
    quality_metrics: QualityMetrics
    performance_metrics: PerformanceMetrics
    execution_analysis: ExecutionAnalysis

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for database storage."""
        return {
            "success_classification": self.success_classification,
            "quality_metrics": asdict(self.quality_metrics),
            "performance_metrics": asdict(self.performance_metrics),
            "execution_analysis": asdict(self.execution_analysis),
        }


# ONEX: exempt - single-responsibility metrics collector
# Rationale: 13 methods, but all serve the single purpose of quality/performance
# metric collection. Methods are highly cohesive (quality checks, performance
# extraction, execution analysis) and extracting would fragment the metrics API.
class PostToolMetricsCollector:
    """Fast metrics collection for PostToolUse hook."""

    def __init__(self):
        self.start_time = time.time()

    def collect_metrics(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        tool_output: dict[str, Any] | None,
        file_path: str | None = None,
        content: str | None = None,
    ) -> Metadata:
        """
        Collect all metrics for PostToolUse event.

        Args:
            tool_name: Name of tool executed
            tool_input: Tool input parameters
            tool_output: Tool output/result
            file_path: File path if applicable
            content: File content if available

        Returns:
            Metadata with all metrics collected
        """
        # Success classification
        success = self._classify_success(tool_name, tool_output)

        # Quality metrics (if content available)
        quality = (
            self._calculate_quality_metrics(file_path, content)
            if content
            else self._default_quality_metrics()
        )

        # Performance metrics
        performance = self._extract_performance_metrics(tool_input, tool_output, content)

        # Execution analysis
        analysis = self._analyze_execution(tool_output)

        return Metadata(
            success_classification=success,
            quality_metrics=quality,
            performance_metrics=performance,
            execution_analysis=analysis,
        )

    def _classify_success(self, tool_name: str, tool_output: dict[str, Any] | None) -> str:
        """
        Classify success level based on tool output.

        Returns:
            "full_success", "partial_success", or "failed"
        """
        if not tool_output:
            return "full_success"  # No output means successful

        # Convert to string for easy searching
        output_str = str(tool_output).lower()

        # Check for error indicators
        error_keywords = ["error", "exception", "failed", "failure", "traceback"]
        warning_keywords = ["warning", "warn", "caution"]

        has_error = any(keyword in output_str for keyword in error_keywords)
        has_warning = any(keyword in output_str for keyword in warning_keywords)

        # Check for success indicators in structured output
        if isinstance(tool_output, dict):
            success_field = tool_output.get("success", tool_output.get("ok", None))
            if success_field is False:
                return "failed"
            elif success_field is True and not has_warning:
                return "full_success"

        # Classify based on indicators
        if has_error:
            return "failed"
        elif has_warning:
            return "partial_success"
        else:
            return "full_success"

    def _calculate_quality_metrics(
        self, file_path: str | None, content: str | None
    ) -> QualityMetrics:
        """
        Calculate rule-based quality score.

        Weights:
        - Naming conventions: 0.25
        - Type safety: 0.25
        - Documentation: 0.25
        - Error handling: 0.25

        Returns:
            QualityMetrics with score and component results
        """
        if not content or not file_path:
            return self._default_quality_metrics()

        # Detect language
        language = self._detect_language(file_path)
        if language not in ["python", "typescript", "javascript"]:
            return self._default_quality_metrics()

        # Component scores
        naming_score, naming_status = self._check_naming_conventions(content, language)
        type_score, type_status = self._check_type_safety(content, language)
        doc_score, doc_status = self._check_documentation(content, language)
        error_score, error_status = self._check_error_handling(content, language)

        # Calculate weighted total
        total_score = (
            naming_score * 0.25 + type_score * 0.25 + doc_score * 0.25 + error_score * 0.25
        )

        return QualityMetrics(
            quality_score=round(total_score, 4),
            naming_conventions=naming_status,
            type_safety=type_status,
            documentation=doc_status,
            error_handling=error_status,
        )

    def _check_naming_conventions(self, content: str, language: str) -> tuple[float, str]:
        """
        Check naming conventions compliance.

        Returns:
            (score, status) where score is 0-1 and status is pass/warning/fail
        """
        if language == "python":
            # Check for common Python naming issues
            violations = 0

            # Check for camelCase variables (should be snake_case)
            camel_case_vars = re.findall(r"\b[a-z]+[A-Z][a-zA-Z]*\b", content)
            violations += len([v for v in camel_case_vars if not v.startswith("_")])

            # Check for SCREAMING_SNAKE_CASE in non-constant contexts
            lines = content.split("\n")
            for line in lines:
                if "=" in line and not line.strip().startswith("#"):
                    if re.search(r"\b[A-Z_]{2,}\b\s*=", line) and "class " not in line:
                        # Likely a constant, but check if it's inside a function
                        violations += 1  # Round up to avoid float type issue

            # Calculate score
            if violations == 0:
                return 1.0, "pass"
            elif violations <= 2:
                return 0.8, "warning"
            else:
                return 0.6, "fail"

        elif language in ["typescript", "javascript"]:
            # Check for TypeScript/JavaScript naming
            violations = 0

            # Check for snake_case variables (should be camelCase)
            snake_case_vars = re.findall(r"\b[a-z]+_[a-z_]+\b", content)
            violations += len(snake_case_vars)

            if violations == 0:
                return 1.0, "pass"
            elif violations <= 2:
                return 0.8, "warning"
            else:
                return 0.6, "fail"

        return 1.0, "pass"

    def _check_type_safety(self, content: str, language: str) -> tuple[float, str]:
        """
        Check type safety compliance.

        Returns:
            (score, status)
        """
        if language == "python":
            # Count function definitions
            func_defs = re.findall(r"^\s*def\s+\w+\s*\(", content, re.MULTILINE)
            total_funcs = len(func_defs)

            if total_funcs == 0:
                return 1.0, "pass"  # No functions, N/A

            # Count typed function definitions
            typed_funcs = re.findall(r"^\s*def\s+\w+\s*\([^)]*:\s*\w+", content, re.MULTILINE)
            type_ratio = len(typed_funcs) / total_funcs if total_funcs > 0 else 1.0

            if type_ratio >= 0.8:
                return 1.0, "pass"
            elif type_ratio >= 0.5:
                return 0.7, "warning"
            else:
                return 0.5, "fail"

        elif language == "typescript":
            # TypeScript should have type annotations
            # Check for 'any' usage (anti-pattern)
            any_usage = len(re.findall(r":\s*any\b", content))

            if any_usage == 0:
                return 1.0, "pass"
            elif any_usage <= 2:
                return 0.8, "warning"
            else:
                return 0.6, "fail"

        return 1.0, "pass"

    def _check_documentation(self, content: str, language: str) -> tuple[float, str]:
        """
        Check documentation quality.

        Returns:
            (score, status)
        """
        if language == "python":
            # Count functions/classes
            func_class_defs = re.findall(r"^\s*(def|class)\s+\w+", content, re.MULTILINE)
            total_defs = len(func_class_defs)

            if total_defs == 0:
                return 1.0, "pass"  # No definitions, N/A

            # Count docstrings - match """ or ''' after def/class
            # Look for both triple double quotes and triple single quotes
            docstring_pattern = r'(def|class)\s+\w+[^:]*:\s*\n\s*("""|\'\'\')'
            docstrings = re.findall(docstring_pattern, content, re.MULTILINE)
            doc_ratio = len(docstrings) / total_defs if total_defs > 0 else 1.0

            if doc_ratio >= 0.8:
                return 1.0, "pass"
            elif doc_ratio >= 0.5:
                return 0.7, "warning"
            else:
                return 0.5, "fail"

        elif language in ["typescript", "javascript"]:
            # Check for JSDoc comments
            func_defs = re.findall(r"(function|const\s+\w+\s*=\s*\([^)]*\)\s*=>)", content)
            total_funcs = len(func_defs)

            if total_funcs == 0:
                return 1.0, "pass"

            jsdoc_comments = re.findall(r"/\*\*", content)
            doc_ratio = len(jsdoc_comments) / total_funcs if total_funcs > 0 else 1.0

            if doc_ratio >= 0.6:
                return 1.0, "pass"
            elif doc_ratio >= 0.3:
                return 0.7, "warning"
            else:
                return 0.5, "fail"

        return 1.0, "pass"

    def _check_error_handling(self, content: str, language: str) -> tuple[float, str]:
        """
        Check error handling quality.

        Returns:
            (score, status)
        """
        if language == "python":
            # Check for bare except clauses (anti-pattern)
            bare_excepts = re.findall(r"^\s*except\s*:", content, re.MULTILINE)
            violations = len(bare_excepts)

            # Check for proper exception handling
            proper_excepts = re.findall(r"^\s*except\s+\w+", content, re.MULTILINE)

            if violations == 0:
                return 1.0, "pass"
            elif violations <= 1 and proper_excepts:
                return 0.7, "warning"
            else:
                return 0.5, "fail"

        elif language in ["typescript", "javascript"]:
            # Check for empty catch blocks (anti-pattern)
            empty_catches = re.findall(r"catch\s*\([^)]*\)\s*\{\s*\}", content)
            violations = len(empty_catches)

            if violations == 0:
                return 1.0, "pass"
            elif violations <= 1:
                return 0.7, "warning"
            else:
                return 0.5, "fail"

        return 1.0, "pass"

    def _extract_performance_metrics(
        self,
        tool_input: dict[str, Any],
        tool_output: dict[str, Any] | None,
        content: str | None,
    ) -> PerformanceMetrics:
        """
        Extract performance metrics from tool execution.

        Returns:
            PerformanceMetrics with timing and size data
        """
        # Calculate execution time (from start of collection)
        execution_time_ms = (time.time() - self.start_time) * 1000

        # Calculate bytes written
        bytes_written = 0
        if content:
            bytes_written = len(content.encode("utf-8"))
        elif tool_input.get("content"):
            bytes_written = len(str(tool_input["content"]).encode("utf-8"))

        # Calculate lines changed (count non-empty lines)
        lines_changed = 0
        if content:
            lines = [line for line in content.split("\n") if line.strip()]
            lines_changed = len(lines)
        elif tool_input.get("content"):
            lines = [line for line in str(tool_input["content"]).split("\n") if line.strip()]
            lines_changed = len(lines)

        # Files modified (always 1 for Write/Edit, 0 otherwise)
        files_modified = 1 if tool_input.get("file_path") else 0

        return PerformanceMetrics(
            execution_time_ms=round(execution_time_ms, 2),
            bytes_written=bytes_written,
            lines_changed=lines_changed,
            files_modified=files_modified,
        )

    def _analyze_execution(self, tool_output: dict[str, Any] | None) -> ExecutionAnalysis:
        """
        Analyze execution behavior for deviations and retries.

        Returns:
            ExecutionAnalysis with deviation classification
        """
        # Simple heuristics based on output
        deviation = "none"
        retries = 0
        recovery = False

        if tool_output:
            output_str = str(tool_output).lower()

            # Check for retry indicators
            if "retry" in output_str or "attempt" in output_str:
                retries = 1
                deviation = "minor"

            # Check for recovery indicators
            if "recovered" in output_str or "fallback" in output_str:
                recovery = True
                deviation = "minor"

            # Check for major deviations
            if "error" in output_str or "failed" in output_str:
                deviation = "major"

        return ExecutionAnalysis(
            deviation_from_expected=deviation,
            required_retries=retries,
            error_recovery_applied=recovery,
        )

    def _default_quality_metrics(self) -> QualityMetrics:
        """Return default quality metrics when content unavailable."""
        return QualityMetrics(
            quality_score=1.0,
            naming_conventions="pass",
            type_safety="pass",
            documentation="pass",
            error_handling="pass",
        )

    def _detect_language(self, file_path: str) -> str | None:
        """Detect programming language from file extension."""
        ext = file_path.lower().split(".")[-1] if "." in file_path else ""

        mapping = {
            "py": "python",
            "ts": "typescript",
            "tsx": "typescript",
            "js": "javascript",
            "jsx": "javascript",
        }

        return mapping.get(ext)

    def get_elapsed_ms(self) -> float:
        """Get elapsed time since collector creation."""
        return (time.time() - self.start_time) * 1000


def collect_post_tool_metrics(tool_info: dict[str, Any]) -> dict[str, Any]:
    """
    Convenience function to collect metrics from tool info JSON.

    Args:
        tool_info: Tool info dictionary from PostToolUse hook

    Returns:
        Dictionary with enhanced metadata
    """
    collector = PostToolMetricsCollector()

    # Extract data from tool_info
    tool_name = tool_info.get("tool_name", "unknown")
    tool_input = tool_info.get("tool_input", {})
    tool_output = tool_info.get("tool_response")
    file_path = tool_input.get("file_path")
    content = tool_input.get("content") or tool_input.get("new_string")

    # Collect metrics
    metadata = collector.collect_metrics(
        tool_name=tool_name,
        tool_input=tool_input,
        tool_output=tool_output,
        file_path=file_path,
        content=content,
    )

    return metadata.to_dict()


if __name__ == "__main__":
    # Test the metrics collector
    import json
    import sys

    print("Testing PostToolMetricsCollector...", file=sys.stderr)

    # Test case 1: Successful Write with Python code
    test_tool_info = {
        "tool_name": "Write",
        "tool_input": {
            "file_path": "/test/example.py",
            "content": """def calculate_sum(a: int, b: int) -> int:
    \"\"\"Calculate sum of two numbers.\"\"\"
    try:
        return a + b
    except TypeError as e:
        raise ValueError(f"Invalid input: {e}")
""",
        },
        "tool_response": {"success": True},
    }

    metrics = collect_post_tool_metrics(test_tool_info)
    print(json.dumps(metrics, indent=2), file=sys.stderr)

    # Test case 2: Failed operation
    test_tool_info_fail = {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": "/test/bad.py",
            "old_string": "foo",
            "new_string": "bar",
        },
        "tool_response": {"error": "File not found"},
    }

    metrics_fail = collect_post_tool_metrics(test_tool_info_fail)
    print(json.dumps(metrics_fail, indent=2), file=sys.stderr)

    print("\n✅ Test complete!", file=sys.stderr)
