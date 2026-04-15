# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for TDD dispatch gate hook (OMN-8846).

Validates that Agent/Task dispatches are blocked unless ONEX_DISPATCH_TYPE
is set and, for implementation type, the prompt contains both a failing-test
reference and a dod_evidence block.

Four cases:
1. research-only   → exit 0 (no TDD required)
2. implementation + TDD clause present → exit 0
3. implementation + TDD clause absent  → exit 2
4. unset/unknown type                  → exit 2
"""

from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.unit

from omniclaude.hooks.pre_tool_use_tdd_dispatch_gate import run_gate  # noqa: E402


def _make_hook_json(prompt: str, tool_name: str = "Agent") -> str:
    return json.dumps(
        {
            "tool_name": tool_name,
            "tool_input": {"prompt": prompt},
        }
    )


class TestResearchOnly:
    """ONEX_DISPATCH_TYPE=research-only — always passes, no TDD required."""

    def test_research_only_exits_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ONEX_DISPATCH_TYPE", "research-only")
        payload = _make_hook_json("Investigate the foo subsystem. # research-only")
        exit_code, _ = run_gate(payload)
        assert exit_code == 0

    def test_research_only_passes_through_json(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ONEX_DISPATCH_TYPE", "research-only")
        payload = _make_hook_json("Some research task. # research-only")
        _, output = run_gate(payload)
        assert json.loads(output)["tool_name"] == "Agent"


class TestImplementationWithTDD:
    """ONEX_DISPATCH_TYPE=implementation with TDD clause — must pass."""

    def test_implementation_with_tdd_exits_zero(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ONEX_DISPATCH_TYPE", "implementation")
        prompt = (
            "Implement the foo feature. OMN-8846.\n"
            "# failing-test: tests/test_foo.py::test_foo_does_thing\n"
            "dod_evidence:\n"
            "  - test_foo_does_thing passes\n"
        )
        payload = _make_hook_json(prompt)
        exit_code, _ = run_gate(payload)
        assert exit_code == 0

    def test_implementation_with_tdd_passes_json(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ONEX_DISPATCH_TYPE", "implementation")
        prompt = (
            "Implement bar. OMN-9000.\n"
            "# failing-test: tests/test_bar.py::test_bar\n"
            "dod_evidence:\n  - bar test passes\n"
        )
        payload = _make_hook_json(prompt)
        _, output = run_gate(payload)
        assert json.loads(output)["tool_name"] == "Agent"


class TestImplementationWithoutTDD:
    """ONEX_DISPATCH_TYPE=implementation without TDD clause — must block."""

    def test_missing_failing_test_exits_two(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ONEX_DISPATCH_TYPE", "implementation")
        prompt = "Implement the foo feature. OMN-8846.\ndod_evidence:\n  - foo works\n"
        payload = _make_hook_json(prompt)
        exit_code, _ = run_gate(payload)
        assert exit_code == 2

    def test_missing_dod_evidence_exits_two(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ONEX_DISPATCH_TYPE", "implementation")
        prompt = (
            "Implement the foo feature. OMN-8846.\n"
            "# failing-test: tests/test_foo.py::test_foo\n"
        )
        payload = _make_hook_json(prompt)
        exit_code, _ = run_gate(payload)
        assert exit_code == 2

    def test_block_output_contains_message(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ONEX_DISPATCH_TYPE", "implementation")
        prompt = "Implement bar. OMN-8846."
        payload = _make_hook_json(prompt)
        exit_code, output = run_gate(payload)
        assert exit_code == 2
        data = json.loads(output)
        assert data.get("decision") == "block"
        assert (
            "failing-test" in data["reason"].lower() or "tdd" in data["reason"].lower()
        )


class TestUnknownDispatchType:
    """Unset or unknown ONEX_DISPATCH_TYPE — must block."""

    def test_unset_env_exits_two(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ONEX_DISPATCH_TYPE", raising=False)
        payload = _make_hook_json("Do something. OMN-8846.")
        exit_code, _ = run_gate(payload)
        assert exit_code == 2

    def test_unknown_value_exits_two(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ONEX_DISPATCH_TYPE", "foobar")
        payload = _make_hook_json("Do something. OMN-8846.")
        exit_code, _ = run_gate(payload)
        assert exit_code == 2

    def test_block_message_instructs_how_to_fix(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ONEX_DISPATCH_TYPE", raising=False)
        payload = _make_hook_json("Do something.")
        exit_code, output = run_gate(payload)
        assert exit_code == 2
        data = json.loads(output)
        assert "ONEX_DISPATCH_TYPE" in data["reason"]

    def test_non_agent_task_passes_through(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Non-Agent/Task tools are not subject to this gate."""
        monkeypatch.delenv("ONEX_DISPATCH_TYPE", raising=False)
        payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"}})
        exit_code, _ = run_gate(payload)
        assert exit_code == 0

    def test_verification_type_exits_zero(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ONEX_DISPATCH_TYPE", "verification")
        payload = _make_hook_json("Verify the output of OMN-8846.")
        exit_code, _ = run_gate(payload)
        assert exit_code == 0
