#!/usr/bin/env python3
"""
Tool Selection Intelligence - Heuristic-based tool selection reasoning

Captures tool selection rationale, alternative tools considered, and execution expectations
using fast heuristic analysis. Target overhead: <10ms per invocation.

This module provides decision intelligence for PreToolUse hooks without AI inference.
"""

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class ToolSelectionReasoning:
    """Captured reasoning for tool selection."""

    tool_chosen: str
    selection_reason: str
    alternative_tools_considered: List[Dict[str, str]] = field(default_factory=list)
    context_info: Dict[str, Any] = field(default_factory=dict)
    expected_execution_path: str = ""
    estimated_time_ms: int = 0
    expected_side_effects: List[str] = field(default_factory=list)
    analysis_time_ms: float = 0.0


@dataclass
class QualityCheckMetadata:
    """Quality check metadata for enhanced logging."""

    checks_passed: List[str] = field(default_factory=list)
    checks_warnings: List[str] = field(default_factory=list)
    checks_failed: List[str] = field(default_factory=list)
    violations_found: int = 0
    corrections_suggested: int = 0
    enforcement_mode: str = "warn"


class ToolSelectionIntelligence:
    """
    Heuristic-based tool selection reasoning engine.

    Provides fast (<10ms) analysis of tool selection decisions using
    file system checks and pattern matching.
    """

    # Tool selection reason mappings
    TOOL_REASONS = {
        "Write": "file_creation_required",
        "Edit": "file_modification_required",
        "Read": "information_gathering",
        "Bash": "command_execution_required",
        "Glob": "file_pattern_matching",
        "Grep": "content_search_required",
        "NotebookEdit": "notebook_cell_modification",
    }

    # Expected execution times (heuristic estimates in milliseconds)
    TOOL_EXECUTION_TIMES = {
        "Write": 50,
        "Edit": 40,
        "Read": 30,
        "Bash": 200,
        "Glob": 100,
        "Grep": 150,
        "NotebookEdit": 60,
    }

    # Side effects by tool type
    TOOL_SIDE_EFFECTS = {
        "Write": ["file_created", "disk_write"],
        "Edit": ["file_modified", "disk_write"],
        "Read": ["file_read"],
        "Bash": ["command_execution", "system_state_change"],
        "Glob": ["filesystem_scan"],
        "Grep": ["content_scan"],
        "NotebookEdit": ["notebook_modified", "disk_write"],
    }

    def __init__(self):
        """Initialize tool selection intelligence."""
        self.start_time = None

    def analyze_tool_selection(
        self, tool_name: str, tool_input: Dict[str, Any]
    ) -> ToolSelectionReasoning:
        """
        Analyze tool selection and generate reasoning metadata.

        Args:
            tool_name: Name of the tool being used
            tool_input: Tool input parameters

        Returns:
            ToolSelectionReasoning with complete analysis
        """
        self.start_time = time.time()

        # Get base selection reason
        selection_reason = self._infer_selection_reason(tool_name, tool_input)

        # Gather context information
        context_info = self._gather_context_info(tool_name, tool_input)

        # Determine alternative tools
        alternatives = self._get_alternative_tools(tool_name, context_info, tool_input)

        # Predict execution path
        execution_path = self._predict_execution_path(tool_name, context_info)

        # Get side effects
        side_effects = self.TOOL_SIDE_EFFECTS.get(tool_name, [])

        # Estimate execution time
        estimated_time = self.TOOL_EXECUTION_TIMES.get(tool_name, 100)

        # Calculate analysis overhead
        analysis_time_ms = (time.time() - self.start_time) * 1000

        return ToolSelectionReasoning(
            tool_chosen=tool_name,
            selection_reason=selection_reason,
            alternative_tools_considered=alternatives,
            context_info=context_info,
            expected_execution_path=execution_path,
            estimated_time_ms=estimated_time,
            expected_side_effects=side_effects,
            analysis_time_ms=analysis_time_ms,
        )

    def _infer_selection_reason(
        self, tool_name: str, tool_input: Dict[str, Any]
    ) -> str:
        """
        Infer why this tool was selected using heuristics.

        Args:
            tool_name: Tool being used
            tool_input: Tool parameters

        Returns:
            Human-readable selection reason
        """
        # Use base reason from mapping
        base_reason = self.TOOL_REASONS.get(tool_name, "unknown_tool_purpose")

        # Add context-specific refinements
        if tool_name == "Write":
            file_path = tool_input.get("file_path", "")
            if file_path and Path(file_path).exists():
                return "file_overwrite_required"
            return base_reason

        elif tool_name == "Edit":
            if "old_string" in tool_input:
                return "targeted_string_replacement"
            return base_reason

        elif tool_name == "Bash":
            command = tool_input.get("command", "")
            if command.startswith("git"):
                return "version_control_operation"
            elif command.startswith(("npm", "yarn", "pip", "poetry")):
                return "package_management"
            elif command.startswith(("pytest", "jest", "vitest")):
                return "test_execution"
            return base_reason

        return base_reason

    def _gather_context_info(
        self, tool_name: str, tool_input: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Gather context information about the operation.

        Fast file system checks to understand the environment.
        Target: <5ms

        Args:
            tool_name: Tool being used
            tool_input: Tool parameters

        Returns:
            Context information dictionary
        """
        context = {}

        # File-related tools need file context
        if tool_name in ("Write", "Edit", "Read", "NotebookEdit"):
            file_path = tool_input.get("file_path", "")
            if file_path:
                try:
                    path = Path(file_path)
                    context["file_exists"] = path.exists()
                    context["file_writable"] = (
                        os.access(path.parent, os.W_OK)
                        if not path.exists()
                        else os.access(path, os.W_OK)
                    )
                    context["directory_exists"] = path.parent.exists()

                    if path.exists():
                        context["file_size_bytes"] = path.stat().st_size
                        context["file_extension"] = path.suffix
                    else:
                        context["file_extension"] = (
                            path.suffix if path.suffix else "unknown"
                        )

                except Exception:
                    # Fast fail - don't block on context gathering
                    context["file_exists"] = False
                    context["file_writable"] = False
                    context["directory_exists"] = False

        # Bash commands - extract command type
        elif tool_name == "Bash":
            command = tool_input.get("command", "")
            context["command_type"] = self._classify_bash_command(command)
            context["is_destructive"] = self._is_destructive_command(command)

        # Search tools - extract search scope
        elif tool_name in ("Glob", "Grep"):
            pattern = tool_input.get("pattern", "")
            context["pattern_complexity"] = (
                "complex" if "*" in pattern or "?" in pattern else "simple"
            )
            context["search_scope"] = tool_input.get("path", "current_directory")

        return context

    def _classify_bash_command(self, command: str) -> str:
        """Classify bash command type for context."""
        if not command:
            return "unknown"

        first_word = command.split()[0] if command.split() else ""

        if first_word in ("git", "svn", "hg"):
            return "version_control"
        elif first_word in ("npm", "yarn", "pip", "poetry", "cargo"):
            return "package_manager"
        elif first_word in ("pytest", "jest", "vitest", "cargo test"):
            return "test_runner"
        elif first_word in ("docker", "kubectl"):
            return "container_management"
        elif first_word in ("ls", "cd", "pwd", "cat", "head", "tail"):
            return "file_inspection"
        else:
            return "general_command"

    def _is_destructive_command(self, command: str) -> bool:
        """Check if bash command is potentially destructive."""
        destructive_patterns = ["rm", "rmdir", "del", "truncate", "> ", ">>"]
        return any(pattern in command for pattern in destructive_patterns)

    def _get_alternative_tools(
        self, tool_name: str, context: Dict[str, Any], tool_input: Dict[str, Any]
    ) -> List[Dict[str, str]]:
        """
        Determine alternative tools that could have been used.

        Uses heuristics based on tool type and context.

        Args:
            tool_name: Tool being used
            context: Context information
            tool_input: Tool parameters

        Returns:
            List of alternative tools with reasons not used
        """
        alternatives = []

        if tool_name == "Write":
            # Write could have been Edit if file exists
            if context.get("file_exists", False):
                alternatives.append(
                    {
                        "tool": "Edit",
                        "reason_not_used": "full_rewrite_preferred_over_partial_edit",
                    }
                )

        elif tool_name == "Edit":
            # Edit could have been Write for full rewrites
            if context.get("file_exists", True):
                alternatives.append(
                    {
                        "tool": "Write",
                        "reason_not_used": "targeted_edit_preferred_over_full_rewrite",
                    }
                )

        elif tool_name == "Bash":
            command = tool_input.get("command", "")

            # Bash for reading could have been Read
            if command.startswith("cat "):
                alternatives.append(
                    {
                        "tool": "Read",
                        "reason_not_used": "command_output_needed_not_raw_file",
                    }
                )

            # Bash for finding could have been Glob
            if command.startswith("find "):
                alternatives.append(
                    {"tool": "Glob", "reason_not_used": "complex_find_logic_required"}
                )

            # Bash for searching could have been Grep
            if command.startswith("grep "):
                alternatives.append(
                    {"tool": "Grep", "reason_not_used": "command_line_grep_preferred"}
                )

        elif tool_name == "Read":
            # Read could have been Bash cat
            alternatives.append(
                {
                    "tool": "Bash",
                    "reason_not_used": "direct_read_more_efficient_than_cat",
                }
            )

        elif tool_name == "Glob":
            # Glob could have been Bash find
            alternatives.append(
                {"tool": "Bash", "reason_not_used": "glob_pattern_simpler_than_find"}
            )

        elif tool_name == "Grep":
            # Grep could have been Bash grep
            alternatives.append(
                {
                    "tool": "Bash",
                    "reason_not_used": "structured_grep_preferred_over_command",
                }
            )

        return alternatives

    def _predict_execution_path(self, tool_name: str, context: Dict[str, Any]) -> str:
        """
        Predict execution path based on tool and context.

        Args:
            tool_name: Tool being used
            context: Context information

        Returns:
            Expected execution path description
        """
        if tool_name == "Write":
            if context.get("file_exists", False):
                return "overwrite_existing_file"
            else:
                return "create_new_file"

        elif tool_name == "Edit":
            return "modify_file_content"

        elif tool_name == "Read":
            return "read_file_content"

        elif tool_name == "Bash":
            if context.get("is_destructive", False):
                return "execute_destructive_command"
            else:
                return "execute_safe_command"

        elif tool_name == "Glob":
            return "scan_filesystem_for_pattern"

        elif tool_name == "Grep":
            return "search_file_contents"

        elif tool_name == "NotebookEdit":
            return "modify_notebook_cell"

        return "unknown_execution_path"


def create_enhanced_metadata(
    tool_name: str,
    tool_input: Dict[str, Any],
    quality_checks: Optional[QualityCheckMetadata] = None,
) -> Dict[str, Any]:
    """
    Create enhanced metadata for PreToolUse logging.

    Combines tool selection reasoning with quality check results.
    Target: <10ms total overhead.

    Args:
        tool_name: Tool being invoked
        tool_input: Tool parameters
        quality_checks: Quality check results (optional)

    Returns:
        Enhanced metadata dictionary ready for logging
    """
    # Analyze tool selection (target: <8ms)
    intelligence = ToolSelectionIntelligence()
    reasoning = intelligence.analyze_tool_selection(tool_name, tool_input)

    # Build enhanced metadata structure
    metadata = {
        "tool_selection": {
            "tool_chosen": reasoning.tool_chosen,
            "selection_reason": reasoning.selection_reason,
            "alternative_tools_considered": reasoning.alternative_tools_considered,
        },
        "context_info": reasoning.context_info,
        "execution_expectations": {
            "expected_path": reasoning.expected_execution_path,
            "estimated_time_ms": reasoning.estimated_time_ms,
            "expected_side_effects": reasoning.expected_side_effects,
        },
        "performance": {"analysis_time_ms": round(reasoning.analysis_time_ms, 2)},
    }

    # Add quality check results if available
    if quality_checks:
        metadata["quality_checks"] = {
            "checks_passed": quality_checks.checks_passed,
            "checks_warnings": quality_checks.checks_warnings,
            "checks_failed": quality_checks.checks_failed,
            "violations_found": quality_checks.violations_found,
            "corrections_suggested": quality_checks.corrections_suggested,
            "enforcement_mode": quality_checks.enforcement_mode,
        }

    return metadata


# Performance testing
if __name__ == "__main__":
    import json
    import tempfile

    print("Testing Tool Selection Intelligence\n" + "=" * 60)

    # Create secure temp file for testing
    temp_test_file = tempfile.NamedTemporaryFile(
        mode="w", delete=False, suffix=".py", prefix="test_new_file_"
    )
    temp_test_path = temp_test_file.name
    temp_test_file.close()

    # Test cases
    test_cases = [
        {
            "name": "Write (new file)",
            "tool_name": "Write",
            "tool_input": {
                "file_path": temp_test_path,
                "content": "# Test content",
            },
        },
        {
            "name": "Edit (existing file)",
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "/etc/hosts",
                "old_string": "localhost",
                "new_string": "127.0.0.1",
            },
        },
        {
            "name": "Bash (git command)",
            "tool_name": "Bash",
            "tool_input": {"command": "git status"},
        },
        {
            "name": "Read",
            "tool_name": "Read",
            "tool_input": {"file_path": "/etc/hosts"},
        },
    ]

    for test_case in test_cases:
        print(f"\n{test_case['name']}")
        print("-" * 60)

        # Create quality check metadata
        quality_checks = QualityCheckMetadata(
            checks_passed=["naming_convention", "syntax_valid"],
            checks_warnings=["missing_docstring"],
            violations_found=3,
            corrections_suggested=2,
            enforcement_mode="warn",
        )

        # Generate enhanced metadata
        metadata = create_enhanced_metadata(
            tool_name=test_case["tool_name"],
            tool_input=test_case["tool_input"],
            quality_checks=quality_checks,
        )

        print(json.dumps(metadata, indent=2))
        print(f"Performance: {metadata['performance']['analysis_time_ms']:.2f}ms")

    # Cleanup temp file
    try:
        os.unlink(temp_test_path)
    except Exception:
        pass

    print("\n" + "=" * 60)
    print("✅ All tests completed!")
