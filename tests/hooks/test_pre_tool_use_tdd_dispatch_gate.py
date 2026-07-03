# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for pre_tool_use_tdd_dispatch_gate (OMN-12181).

Covers all pass/fail paths for the TDD dispatch gate enforcement hook:

Pass cases (exit 0):
    - ONEX_DISPATCH_TYPE=research-only: exempt, no markers required
    - ONEX_DISPATCH_TYPE=verification: exempt, no markers required
    - ONEX_DISPATCH_TYPE=implementation with both markers present
    - ONEX_DISPATCH_TYPE=implementation with Task tool and both markers present
    - Non-Agent/Task tool names pass through unconditionally
    - Malformed JSON fails open (exit 0)
    - ONEX_DISPATCH_TYPE value is lowercased before comparison

Fail cases (exit 2, block):
    - ONEX_DISPATCH_TYPE not set: blocked with instructions
    - ONEX_DISPATCH_TYPE=implementation missing both markers
    - ONEX_DISPATCH_TYPE=implementation missing only # failing-test: marker
    - ONEX_DISPATCH_TYPE=implementation missing only dod_evidence: marker
    - ONEX_DISPATCH_TYPE=<unknown>: unrecognized type blocked
    - Block output is always valid JSON with decision + reason fields

Prompt key coverage:
    - Marker detection works in 'prompt', 'task', 'description' keys
"""

from __future__ import annotations

import json
import os
import pathlib
import sys

import pytest

_REPO_ROOT = pathlib.Path(__file__).parents[2]
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))

from omniclaude.hooks.pre_tool_use_tdd_dispatch_gate import run_gate  # noqa: E402

_DISPATCH_ENV = "ONEX_DISPATCH_TYPE"


def _make_json(tool_name: str, prompt: str) -> str:
    return json.dumps({"tool_name": tool_name, "tool_input": {"prompt": prompt}})


def _impl_prompt_full() -> str:
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


@pytest.fixture(autouse=True)
def _clear_dispatch_type():
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
    os.environ[_DISPATCH_ENV] = "research-only"
    code, _ = run_gate(_make_json("Agent", "No markers at all."))
    assert code == 0


@pytest.mark.unit
def test_verification_passes_without_markers() -> None:
    os.environ[_DISPATCH_ENV] = "verification"
    code, _ = run_gate(_make_json("Agent", "Just verifying."))
    assert code == 0


@pytest.mark.unit
def test_implementation_with_both_markers_passes() -> None:
    os.environ[_DISPATCH_ENV] = "implementation"
    code, _ = run_gate(_make_json("Agent", _impl_prompt_full()))
    assert code == 0


@pytest.mark.unit
def test_implementation_task_tool_with_both_markers_passes() -> None:
    os.environ[_DISPATCH_ENV] = "implementation"
    code, _ = run_gate(_make_json("Task", _impl_prompt_full()))
    assert code == 0


@pytest.mark.unit
def test_non_agent_task_tool_passes_through() -> None:
    for tool in ("Bash", "Edit", "Write", "Read", "Grep"):
        code, _ = run_gate(_make_json(tool, "no markers"))
        assert code == 0, f"Expected exit 0 for non-dispatch tool {tool}"


@pytest.mark.unit
def test_malformed_json_fails_open() -> None:
    code, _ = run_gate("not-valid-json{")
    assert code == 0


@pytest.mark.unit
def test_dispatch_type_is_lowercased_before_comparison() -> None:
    os.environ[_DISPATCH_ENV] = "RESEARCH-ONLY"
    code, _ = run_gate(_make_json("Agent", "no markers"))
    assert code == 0


@pytest.mark.unit
def test_passthrough_preserves_original_json() -> None:
    os.environ[_DISPATCH_ENV] = "research-only"
    payload = _make_json("Agent", "Research task.")
    code, out = run_gate(payload)
    assert code == 0
    assert json.loads(out) == json.loads(payload)


# ---------------------------------------------------------------------------
# Fail cases
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_dispatch_type_not_set_blocks_agent() -> None:
    code, out = run_gate(_make_json("Agent", _impl_prompt_full()))
    assert code == 2
    data = json.loads(out)
    assert data["decision"] == "block"
    assert "ONEX_DISPATCH_TYPE" in data["reason"]


@pytest.mark.unit
def test_dispatch_type_not_set_blocks_task() -> None:
    code, out = run_gate(_make_json("Task", _impl_prompt_full()))
    assert code == 2
    data = json.loads(out)
    assert data["decision"] == "block"


@pytest.mark.unit
def test_implementation_missing_both_markers_blocked() -> None:
    os.environ[_DISPATCH_ENV] = "implementation"
    code, out = run_gate(_make_json("Agent", _impl_prompt_neither()))
    assert code == 2
    data = json.loads(out)
    assert data["decision"] == "block"
    assert "# failing-test:" in data["reason"]
    assert "dod_evidence:" in data["reason"]


@pytest.mark.unit
def test_implementation_missing_failing_test_marker_blocked() -> None:
    os.environ[_DISPATCH_ENV] = "implementation"
    code, out = run_gate(_make_json("Agent", _impl_prompt_no_failing_test()))
    assert code == 2
    data = json.loads(out)
    assert "# failing-test:" in data["reason"]


@pytest.mark.unit
def test_implementation_missing_dod_evidence_marker_blocked() -> None:
    os.environ[_DISPATCH_ENV] = "implementation"
    code, out = run_gate(_make_json("Agent", _impl_prompt_no_dod()))
    assert code == 2
    data = json.loads(out)
    assert "dod_evidence:" in data["reason"]


@pytest.mark.unit
def test_unknown_dispatch_type_blocked() -> None:
    os.environ[_DISPATCH_ENV] = "build-mode"
    code, out = run_gate(_make_json("Agent", _impl_prompt_full()))
    assert code == 2
    data = json.loads(out)
    assert data["decision"] == "block"
    assert "build-mode" in data["reason"]


@pytest.mark.unit
def test_block_output_is_valid_json_with_required_fields() -> None:
    os.environ[_DISPATCH_ENV] = "implementation"
    code, out = run_gate(_make_json("Agent", _impl_prompt_neither()))
    assert code == 2
    data = json.loads(out)
    assert "decision" in data
    assert "reason" in data


# ---------------------------------------------------------------------------
# Prompt key coverage
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_markers_detected_in_task_key() -> None:
    os.environ[_DISPATCH_ENV] = "implementation"
    payload = json.dumps(
        {"tool_name": "Agent", "tool_input": {"task": _impl_prompt_full()}}
    )
    code, _ = run_gate(payload)
    assert code == 0


@pytest.mark.unit
def test_markers_detected_in_description_key() -> None:
    os.environ[_DISPATCH_ENV] = "implementation"
    payload = json.dumps(
        {"tool_name": "Agent", "tool_input": {"description": _impl_prompt_full()}}
    )
    code, _ = run_gate(payload)
    assert code == 0


@pytest.mark.unit
def test_implementation_empty_tool_input_blocked() -> None:
    os.environ[_DISPATCH_ENV] = "implementation"
    payload = json.dumps({"tool_name": "Agent", "tool_input": {}})
    code, out = run_gate(payload)
    assert code == 2
    data = json.loads(out)
    assert data["decision"] == "block"
