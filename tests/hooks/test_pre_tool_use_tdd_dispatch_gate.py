# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Equivalence tests for hooks/pre_tool_use_tdd_dispatch_gate.py (OMN-12177).

Captures current pass/fail behavior as a regression baseline before refactoring.
Does NOT modify the script. Tests run_gate() directly.

Pass cases (exit 0):
    - ONEX_DISPATCH_TYPE=research-only: exempt, no markers required
    - ONEX_DISPATCH_TYPE=verification: exempt, no markers required
    - ONEX_DISPATCH_TYPE=implementation with both markers present
    - Non-Agent/Task tool names: pass through unconditionally
    - Malformed JSON: fail-open, exit 0

Fail cases (exit 2, block):
    - ONEX_DISPATCH_TYPE not set
    - ONEX_DISPATCH_TYPE=implementation missing both markers
    - ONEX_DISPATCH_TYPE=implementation missing only failing-test marker
    - ONEX_DISPATCH_TYPE=implementation missing only dod_evidence marker
    - ONEX_DISPATCH_TYPE=unknown_value: unrecognized type blocked
"""

from __future__ import annotations

import json
import os
import pathlib
import sys

import pytest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_REPO_ROOT = pathlib.Path(__file__).parents[2]
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))

from omniclaude.hooks.pre_tool_use_tdd_dispatch_gate import run_gate  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DISPATCH_ENV = "ONEX_DISPATCH_TYPE"


def _make_json(tool_name: str, prompt: str) -> str:
    return json.dumps({"tool_name": tool_name, "tool_input": {"prompt": prompt}})


def _impl_prompt_full() -> str:
    """A prompt containing both required markers."""
    return (
        "Implement the feature.\n"
        "# failing-test: tests/unit/test_foo.py::test_bar\n"
        "dod_evidence:\n"
        "  - type: test_pass\n"
        "    path: tests/unit/test_foo.py\n"
    )


def _impl_prompt_no_failing_test() -> str:
    return "Implement the feature.\ndod_evidence:\n  - type: test_pass\n"


def _impl_prompt_no_dod() -> str:
    return "Implement.\n# failing-test: tests/unit/test_foo.py::test_bar\n"


def _impl_prompt_neither() -> str:
    return "Just do the work, no markers.\n"


# ---------------------------------------------------------------------------
# Fixture: manage ONEX_DISPATCH_TYPE env var
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_dispatch_type():
    """Ensure ONEX_DISPATCH_TYPE is unset before each test."""
    old = os.environ.pop(_DISPATCH_ENV, None)
    yield
    if old is None:
        os.environ.pop(_DISPATCH_ENV, None)
    else:
        os.environ[_DISPATCH_ENV] = old


# ---------------------------------------------------------------------------
# Pass cases
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_research_only_passes_without_markers() -> None:
    """research-only is exempt — Agent call passes regardless of prompt content."""
    os.environ[_DISPATCH_ENV] = "research-only"
    code, out = run_gate(_make_json("Agent", "No markers at all."))
    assert code == 0


@pytest.mark.unit
def test_verification_passes_without_markers() -> None:
    """verification is exempt — Agent call passes regardless of prompt content."""
    os.environ[_DISPATCH_ENV] = "verification"
    code, out = run_gate(_make_json("Agent", "Just verifying."))
    assert code == 0


@pytest.mark.unit
def test_implementation_with_both_markers_passes() -> None:
    """implementation type with both markers present passes."""
    os.environ[_DISPATCH_ENV] = "implementation"
    code, out = run_gate(_make_json("Agent", _impl_prompt_full()))
    assert code == 0


@pytest.mark.unit
def test_implementation_task_tool_with_both_markers_passes() -> None:
    """Task tool with implementation type and both markers passes."""
    os.environ[_DISPATCH_ENV] = "implementation"
    code, out = run_gate(_make_json("Task", _impl_prompt_full()))
    assert code == 0


@pytest.mark.unit
def test_non_agent_task_tool_passes_through() -> None:
    """Non-Agent/Task tools are never blocked, regardless of DISPATCH_TYPE."""
    for tool in ("Bash", "Edit", "Write", "Read", "Grep"):
        code, _ = run_gate(_make_json(tool, "no markers"))
        assert code == 0, f"Expected 0 for {tool}"


@pytest.mark.unit
def test_malformed_json_fails_open() -> None:
    """Malformed JSON is treated as pass-through (fail-open)."""
    code, out = run_gate("not-valid-json{")
    assert code == 0


@pytest.mark.unit
def test_research_only_case_insensitive() -> None:
    """ONEX_DISPATCH_TYPE is lowercased before comparison."""
    os.environ[_DISPATCH_ENV] = "RESEARCH-ONLY"
    code, _ = run_gate(_make_json("Agent", "no markers"))
    assert code == 0


# ---------------------------------------------------------------------------
# Fail cases
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_dispatch_type_not_set_blocks_agent() -> None:
    """When ONEX_DISPATCH_TYPE is unset, Agent call is blocked."""
    # autouse fixture already cleared it
    code, out = run_gate(_make_json("Agent", _impl_prompt_full()))
    assert code == 2
    data = json.loads(out)
    assert data["decision"] == "block"
    assert "ONEX_DISPATCH_TYPE" in data["reason"]


@pytest.mark.unit
def test_dispatch_type_not_set_blocks_task() -> None:
    """When ONEX_DISPATCH_TYPE is unset, Task call is blocked."""
    code, out = run_gate(_make_json("Task", _impl_prompt_full()))
    assert code == 2


@pytest.mark.unit
def test_implementation_missing_both_markers_blocked() -> None:
    """implementation type with neither marker is blocked."""
    os.environ[_DISPATCH_ENV] = "implementation"
    code, out = run_gate(_make_json("Agent", _impl_prompt_neither()))
    assert code == 2
    data = json.loads(out)
    assert data["decision"] == "block"
    assert "# failing-test:" in data["reason"]
    assert "dod_evidence:" in data["reason"]


@pytest.mark.unit
def test_implementation_missing_failing_test_marker_blocked() -> None:
    """implementation type missing # failing-test: is blocked."""
    os.environ[_DISPATCH_ENV] = "implementation"
    code, out = run_gate(_make_json("Agent", _impl_prompt_no_failing_test()))
    assert code == 2
    data = json.loads(out)
    assert "# failing-test:" in data["reason"]


@pytest.mark.unit
def test_implementation_missing_dod_evidence_marker_blocked() -> None:
    """implementation type missing dod_evidence: is blocked."""
    os.environ[_DISPATCH_ENV] = "implementation"
    code, out = run_gate(_make_json("Agent", _impl_prompt_no_dod()))
    assert code == 2
    data = json.loads(out)
    assert "dod_evidence:" in data["reason"]


@pytest.mark.unit
def test_unknown_dispatch_type_blocked() -> None:
    """An unrecognized ONEX_DISPATCH_TYPE value is blocked."""
    os.environ[_DISPATCH_ENV] = "build-mode"
    code, out = run_gate(_make_json("Agent", _impl_prompt_full()))
    assert code == 2
    data = json.loads(out)
    assert data["decision"] == "block"
    assert "build-mode" in data["reason"]


@pytest.mark.unit
def test_block_output_is_valid_json() -> None:
    """Block output is always valid JSON with decision and reason fields."""
    os.environ[_DISPATCH_ENV] = "implementation"
    code, out = run_gate(_make_json("Agent", _impl_prompt_neither()))
    assert code == 2
    data = json.loads(out)
    assert "decision" in data
    assert "reason" in data


@pytest.mark.unit
def test_prompt_in_task_key_detected() -> None:
    """Marker detection works when prompt is in 'task' key, not 'prompt'."""
    os.environ[_DISPATCH_ENV] = "implementation"
    payload = json.dumps(
        {
            "tool_name": "Agent",
            "tool_input": {"task": _impl_prompt_full()},
        }
    )
    code, _ = run_gate(payload)
    assert code == 0


@pytest.mark.unit
def test_prompt_in_description_key_detected() -> None:
    """Marker detection works when prompt is in 'description' key."""
    os.environ[_DISPATCH_ENV] = "implementation"
    payload = json.dumps(
        {
            "tool_name": "Agent",
            "tool_input": {"description": _impl_prompt_full()},
        }
    )
    code, _ = run_gate(payload)
    assert code == 0
