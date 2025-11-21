"""
Task Schema Definitions for Parallel Dispatch

Provides reusable schema definitions and examples for both agent types.
Use this file as a reference when creating task definitions.
"""

import tempfile
from pathlib import Path
from typing import Any, Dict, List, Literal

from pydantic import BaseModel, Field


# ============================================================================
# Agent-Specific Input Schemas
# ============================================================================


class CoderTaskInput(BaseModel):
    """Input schema for CoderAgent tasks."""

    contract_description: str = Field(
        ..., description="Natural language description of what to generate"
    )
    node_type: Literal["Effect", "Compute", "Reducer", "Orchestrator"] = Field(
        ..., description="ONEX node type to generate"
    )
    output_path: str = Field(
        ..., description="Absolute path where generated code should be written"
    )
    context_files: List[str] = Field(
        default_factory=list, description="Absolute paths to related files for context"
    )
    validation_level: Literal["strict", "moderate", "lenient"] = Field(
        default="moderate", description="How strictly to validate ONEX compliance"
    )


class DebugTaskInput(BaseModel):
    """Input schema for DebugAgent tasks."""

    problem_description: str = Field(
        ..., description="Description of the bug or issue to investigate"
    )
    affected_files: List[str] = Field(
        ..., description="Absolute paths to files potentially involved"
    )
    error_traces: List[str] = Field(
        default_factory=list,
        description="Stack traces, error messages, or log excerpts",
    )
    analysis_depth: Literal["quick", "standard", "deep"] = Field(
        default="standard", description="How deeply to analyze the issue"
    )
    hypothesis: str = Field(
        default="", description="Initial hypothesis about root cause (optional)"
    )


# ============================================================================
# Task Definition Examples
# ============================================================================

EXAMPLE_CODER_TASKS = [
    {
        "task_id": "generate-effect-node",
        "agent": "coder",
        "description": "Generate database writer Effect node",
        "input_data": {
            "contract_description": "Create an Effect node that writes user data to PostgreSQL database",
            "node_type": "Effect",
            "output_path": "/path/to/node_database_writer_effect.py",
            "context_files": [
                "/path/to/model_user.py",
                "/path/to/model_contract_effect.py",
            ],
            "validation_level": "strict",
        },
        "dependencies": [],
    },
    {
        "task_id": "generate-compute-node",
        "agent": "coder",
        "description": "Generate data transformer Compute node",
        "input_data": {
            "contract_description": "Create a Compute node that transforms raw API data to internal format",
            "node_type": "Compute",
            "output_path": "/path/to/node_data_transformer_compute.py",
            "context_files": ["/path/to/model_api_response.py"],
            "validation_level": "moderate",
        },
        "dependencies": [],
    },
]

EXAMPLE_DEBUG_TASKS = [
    {
        "task_id": "debug-authentication-failure",
        "agent": "debug",
        "description": "Investigate authentication failures in production",
        "input_data": {
            "problem_description": "Users reporting intermittent 401 errors during login",
            "affected_files": [
                "/path/to/auth/authentication.py",
                "/path/to/auth/token_manager.py",
                "/path/to/middleware/auth_middleware.py",
            ],
            "error_traces": [
                "TokenExpiredError: JWT token expired at 2025-10-06T12:00:00Z",
                "AuthenticationError: Invalid token signature",
            ],
            "analysis_depth": "deep",
            "hypothesis": "Token refresh mechanism may have race condition",
        },
        "dependencies": [],
    },
    {
        "task_id": "debug-performance-degradation",
        "agent": "debug",
        "description": "Analyze API response time degradation",
        "input_data": {
            "problem_description": "API endpoints responding 2x slower than baseline",
            "affected_files": [
                "/path/to/api/endpoints.py",
                "/path/to/database/query_builder.py",
            ],
            "error_traces": [],
            "analysis_depth": "standard",
        },
        "dependencies": [],
    },
]

EXAMPLE_MIXED_WORKFLOW = {
    "tasks": [
        {
            "task_id": "debug-existing-code",
            "agent": "debug",
            "description": "Analyze existing implementation for issues",
            "input_data": {
                "problem_description": "Existing Effect node has inconsistent error handling",
                "affected_files": ["/path/to/node_database_writer_effect.py"],
                "analysis_depth": "standard",
            },
            "dependencies": [],
        },
        {
            "task_id": "generate-fixed-node",
            "agent": "coder",
            "description": "Generate corrected Effect node based on debug findings",
            "input_data": {
                "contract_description": "Create Effect node with proper error handling",
                "node_type": "Effect",
                "output_path": "/path/to/node_database_writer_effect_v2.py",
                "validation_level": "strict",
            },
            "dependencies": ["debug-existing-code"],  # Wait for debug results
        },
    ],
    "config": {"max_workers": 5, "timeout_seconds": 300, "trace_dir": "./traces"},
}


# ============================================================================
# Task Builder Utilities
# ============================================================================


class TaskBuilder:
    """Helper class for building task definitions."""

    @staticmethod
    def create_coder_task(
        task_id: str,
        description: str,
        contract_description: str,
        node_type: Literal["Effect", "Compute", "Reducer", "Orchestrator"],
        output_path: str,
        context_files: List[str] = None,
        validation_level: str = "moderate",
        dependencies: List[str] = None,
    ) -> Dict[str, Any]:
        """Create a properly formatted CoderAgent task."""
        return {
            "task_id": task_id,
            "agent": "coder",
            "description": description,
            "input_data": {
                "contract_description": contract_description,
                "node_type": node_type,
                "output_path": output_path,
                "context_files": context_files or [],
                "validation_level": validation_level,
            },
            "dependencies": dependencies or [],
        }

    @staticmethod
    def create_debug_task(
        task_id: str,
        description: str,
        problem_description: str,
        affected_files: List[str],
        error_traces: List[str] = None,
        analysis_depth: str = "standard",
        hypothesis: str = "",
        dependencies: List[str] = None,
    ) -> Dict[str, Any]:
        """Create a properly formatted DebugAgent task."""
        return {
            "task_id": task_id,
            "agent": "debug",
            "description": description,
            "input_data": {
                "problem_description": problem_description,
                "affected_files": affected_files,
                "error_traces": error_traces or [],
                "analysis_depth": analysis_depth,
                "hypothesis": hypothesis,
            },
            "dependencies": dependencies or [],
        }


# ============================================================================
# Validation Helpers
# ============================================================================


def validate_task_dependencies(tasks: List[Dict[str, Any]]) -> List[str]:
    """Validate that all task dependencies reference existing tasks."""
    task_ids = {task["task_id"] for task in tasks}
    errors = []

    for task in tasks:
        for dep_id in task.get("dependencies", []):
            if dep_id not in task_ids:
                errors.append(
                    f"Task '{task['task_id']}' depends on unknown task '{dep_id}'"
                )

    return errors


def detect_circular_dependencies(tasks: List[Dict[str, Any]]) -> List[str]:
    """Detect circular dependencies in task graph."""
    errors = []
    task_map = {task["task_id"]: task for task in tasks}

    def has_cycle(task_id: str, visited: set, path: List[str]) -> bool:
        if task_id in path:
            return True
        if task_id in visited:
            return False

        visited.add(task_id)
        path.append(task_id)

        task = task_map.get(task_id)
        if task:
            for dep_id in task.get("dependencies", []):
                if has_cycle(dep_id, visited, path.copy()):
                    return True

        return False

    for task in tasks:
        if has_cycle(task["task_id"], set(), []):
            errors.append(
                f"Circular dependency detected involving task '{task['task_id']}'"
            )

    return errors


# ============================================================================
# Usage Examples
# ============================================================================

if __name__ == "__main__":
    """
    Example usage of task builders and validators.
    """
    from pprint import pprint

    # Build tasks using TaskBuilder
    builder = TaskBuilder()

    task1 = builder.create_coder_task(
        task_id="gen-effect-1",
        description="Generate database Effect node",
        contract_description="Database writer for user records",
        node_type="Effect",
        output_path=str(Path(tempfile.gettempdir()) / "node_db_writer_effect.py"),
    )

    task2 = builder.create_debug_task(
        task_id="debug-auth-1",
        description="Debug authentication issues",
        problem_description="Login failures in production",
        affected_files=["/path/to/auth.py"],
    )

    tasks = [task1, task2]

    # Validate
    dep_errors = validate_task_dependencies(tasks)
    cycle_errors = detect_circular_dependencies(tasks)

    print("=== Generated Tasks ===")
    pprint(tasks)

    print("\n=== Validation Results ===")
    print(f"Dependency errors: {dep_errors or 'None'}")
    print(f"Circular dependencies: {cycle_errors or 'None'}")
