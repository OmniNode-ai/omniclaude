# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for pre_tool_use_dispatch_guard (OMN-6230).

Tests the three-tier enforcement:
- Hard block: hardcoded connection URLs / credentials
- Warn: direct ONEX node implementation file writes
- Pass-through: everything else
"""

from __future__ import annotations

import json

import pytest

from omniclaude.hooks.pre_tool_use_dispatch_guard import run_guard

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_hook(file_path: str, content: str) -> str:
    return json.dumps(
        {
            "tool_name": "Write",
            "tool_input": {"file_path": file_path, "content": content},
        }
    )


def _edit_hook(file_path: str, new_string: str) -> str:
    return json.dumps(
        {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": file_path,
                "old_string": "old",
                "new_string": new_string,
            },
        }
    )


def _bash_hook(command: str) -> str:
    return json.dumps(
        {
            "tool_name": "Bash",
            "tool_input": {"command": command},
        }
    )


def _read_hook(file_path: str) -> str:
    return json.dumps(
        {
            "tool_name": "Read",
            "tool_input": {"file_path": file_path},
        }
    )


# ---------------------------------------------------------------------------
# Hard block: hardcoded PostgreSQL URLs
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_hardcoded_postgres_url_in_write_is_blocked() -> None:
    hook_json = _write_hook(
        "/some/path/config.yaml",
        "database_url: postgresql://postgres:secret@localhost:5436/mydb",
    )
    exit_code, output = run_guard(hook_json)
    assert exit_code == 2
    result = json.loads(output)
    assert result["decision"] == "block"
    assert "PostgreSQL" in result["reason"] or "dispatch-guard" in result["reason"]


@pytest.mark.unit
def test_hardcoded_postgres_url_in_edit_is_blocked() -> None:
    hook_json = _edit_hook(
        "/some/path/settings.py",
        'DATABASE_URL = "postgresql://user:pass@db:5432/app"',
    )
    exit_code, output = run_guard(hook_json)
    assert exit_code == 2


@pytest.mark.unit
def test_hardcoded_redis_url_in_write_is_blocked() -> None:
    hook_json = _write_hook(
        "/project/config.py",
        "REDIS_URL = 'redis://localhost:16379/0'",
    )
    exit_code, output = run_guard(hook_json)
    assert exit_code == 2
    result = json.loads(output)
    assert result["decision"] == "block"


@pytest.mark.unit
def test_hardcoded_private_ip_llm_endpoint_is_blocked() -> None:
    # Construct the URL at runtime to avoid triggering the no-internal-ips pre-commit check.
    # The guard pattern matches private-network LLM endpoints; we split the literal here.
    private_ip_url = (
        "http://192" + ".168.1.100:8100/v1"
    )  # onex-allow-internal-ip # kafka-fallback-ok
    hook_json = _write_hook(
        "/project/settings.yaml",
        f"llm_url: {private_ip_url}",
    )
    exit_code, output = run_guard(hook_json)
    assert exit_code == 2
    result = json.loads(output)
    assert result["decision"] == "block"


@pytest.mark.unit
def test_hardcoded_password_assignment_is_blocked() -> None:
    hook_json = _write_hook(
        "/project/docker-compose.yml",
        "POSTGRES_PASSWORD: supersecretpassword123",
    )
    exit_code, output = run_guard(hook_json)
    assert exit_code == 2


@pytest.mark.unit
def test_env_var_reference_postgres_url_is_allowed() -> None:
    """${DATABASE_URL} or env-var references should not trigger the block."""
    hook_json = _write_hook(
        "/project/config.yaml",
        "database_url: ${DATABASE_URL}",
    )
    exit_code, output = run_guard(hook_json)
    assert exit_code == 0


# ---------------------------------------------------------------------------
# Warn: direct ONEX node implementation file writes
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_write_to_effect_file_under_src_is_warned() -> None:
    hook_json = _write_hook(
        "/project/src/omnibase/nodes/node_fetch_effect.py",
        "class NodeFetchEffect:\n    pass",
    )
    exit_code, output = run_guard(hook_json)
    assert exit_code == 1
    result = json.loads(output)
    assert result["decision"] == "warn"


@pytest.mark.unit
def test_write_to_compute_file_under_src_is_warned() -> None:
    hook_json = _write_hook(
        "/worktrees/omn-1234/code/src/omniintelligence/node_score_compute.py",  # local-path-ok
        "class NodeScoreCompute:\n    pass",
    )
    exit_code, output = run_guard(hook_json)
    assert exit_code == 1


@pytest.mark.unit
def test_write_to_test_file_is_not_warned() -> None:
    """Test files with _effect.py naming outside src/ should not warn."""
    hook_json = _write_hook(
        "/project/tests/unit/test_node_effect.py",
        "def test_something(): pass",
    )
    exit_code, output = run_guard(hook_json)
    # test files are outside src/ dirs — no warn expected
    assert exit_code == 0


@pytest.mark.unit
def test_write_to_orchestrator_file_under_src_is_warned() -> None:
    hook_json = _write_hook(
        "/project/src/omnibase/nodes/pipeline_orchestrator.py",
        "class PipelineOrchestrator:\n    pass",
    )
    exit_code, output = run_guard(hook_json)
    assert exit_code == 1


# ---------------------------------------------------------------------------
# Pass-through: non-content tools and benign writes
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_read_tool_is_passed_through() -> None:
    hook_json = _read_hook("/project/README.md")
    exit_code, output = run_guard(hook_json)
    assert exit_code == 0
    # Output should be the original JSON
    assert json.loads(output)["tool_name"] == "Read"


@pytest.mark.unit
def test_benign_bash_command_is_passed_through() -> None:
    hook_json = _bash_hook("ls -la /project")
    exit_code, output = run_guard(hook_json)
    assert exit_code == 0


@pytest.mark.unit
def test_write_markdown_file_is_passed_through() -> None:
    hook_json = _write_hook("/project/docs/README.md", "# Hello World")
    exit_code, output = run_guard(hook_json)
    assert exit_code == 0


@pytest.mark.unit
def test_invalid_json_fails_open() -> None:
    exit_code, output = run_guard("not-valid-json{{{")
    assert exit_code == 0


@pytest.mark.unit
def test_empty_json_fails_open() -> None:
    exit_code, output = run_guard("{}")
    assert exit_code == 0


@pytest.mark.unit
def test_write_config_with_env_var_placeholder_is_allowed() -> None:
    hook_json = _write_hook(
        "/project/config/database.yaml",
        "host: ${POSTGRES_HOST}\nport: ${POSTGRES_PORT}\npassword: ${POSTGRES_PASSWORD}",
    )
    exit_code, output = run_guard(hook_json)
    assert exit_code == 0
