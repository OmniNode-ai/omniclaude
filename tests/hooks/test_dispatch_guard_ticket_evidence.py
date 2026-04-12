# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for pre_tool_use_dispatch_guard_ticket_evidence (OMN-8490).

Covers:
    Block cases (exit 2):
        - Agent() call without any OMN-XXXX reference
        - Task() call without any OMN-XXXX reference
        - Agent() with OMN ref but missing .evidence/ directory
        - Task() with OMN ref but missing .evidence/ directory
        - Agent() with OMN ref and .evidence/ dir but wrong ticket subdir

    Pass-through cases (exit 0):
        - Agent() with OMN ref AND matching .evidence/OMN-XXXX/ directory present
        - Task() with OMN ref AND matching .evidence/OMN-XXXX/ directory present
        - Agent() with # research-only marker (no ticket required)
        - Task() with # research-only marker (no ticket required)
        - Non-Agent/Task tool names pass through unconditionally
        - Multiple OMN refs: at least one has matching .evidence/ dir

    Edge cases:
        - Malformed JSON passes through (fail-open)
        - Disabled via env var DISPATCH_TICKET_GUARD_DISABLED=1
        - project_dir override via CLAUDE_PROJECT_DIR env var
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
import tempfile
import unittest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
_REPO_ROOT = pathlib.Path(__file__).parents[2]
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))

from omniclaude.hooks.pre_tool_use_dispatch_guard_ticket_evidence import (  # noqa: E402
    run_guard,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_hook_json(tool_name: str, prompt: str) -> str:
    return json.dumps(
        {
            "tool_name": tool_name,
            "tool_input": {"prompt": prompt},
        }
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDispatchGuardTicketEvidence(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.project_dir = pathlib.Path(self._tmpdir.name)
        self._old_env = {
            "CLAUDE_PROJECT_DIR": os.environ.get("CLAUDE_PROJECT_DIR"),
            "DISPATCH_TICKET_GUARD_DISABLED": os.environ.get(
                "DISPATCH_TICKET_GUARD_DISABLED"
            ),
        }
        os.environ["CLAUDE_PROJECT_DIR"] = str(self.project_dir)
        os.environ.pop("DISPATCH_TICKET_GUARD_DISABLED", None)

    def tearDown(self) -> None:
        self._tmpdir.cleanup()
        for k, v in self._old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def _make_evidence(self, ticket: str) -> None:
        evidence_dir = self.project_dir / ".evidence" / ticket
        evidence_dir.mkdir(parents=True, exist_ok=True)

    # --- Block: no ticket ref ------------------------------------------------

    def test_agent_no_ticket_ref_blocked(self) -> None:
        payload = _make_hook_json("Agent", "Do some work without a ticket.")
        code, output = run_guard(payload)
        self.assertEqual(code, 2)
        data = json.loads(output)
        self.assertEqual(data["decision"], "block")
        self.assertIn("OMN-", data["reason"])

    def test_task_no_ticket_ref_blocked(self) -> None:
        payload = _make_hook_json("Task", "Refactor the codebase.")
        code, output = run_guard(payload)
        self.assertEqual(code, 2)
        data = json.loads(output)
        self.assertEqual(data["decision"], "block")

    # --- Block: ticket ref present but evidence dir missing ------------------

    def test_agent_ticket_ref_no_evidence_dir_blocked(self) -> None:
        payload = _make_hook_json("Agent", "Work on OMN-8490.")
        code, output = run_guard(payload)
        self.assertEqual(code, 2)
        data = json.loads(output)
        self.assertEqual(data["decision"], "block")
        self.assertIn("OMN-8490", data["reason"])

    def test_task_ticket_ref_no_evidence_dir_blocked(self) -> None:
        payload = _make_hook_json("Task", "Implement OMN-1234 acceptance criteria.")
        code, output = run_guard(payload)
        self.assertEqual(code, 2)

    def test_agent_wrong_ticket_evidence_dir_blocked(self) -> None:
        self._make_evidence("OMN-9999")
        payload = _make_hook_json("Agent", "OMN-8490 — add feature.")
        code, output = run_guard(payload)
        self.assertEqual(code, 2)
        data = json.loads(output)
        self.assertIn("OMN-8490", data["reason"])

    # --- Pass: ticket ref + matching evidence --------------------------------

    def test_agent_with_ticket_and_evidence_allowed(self) -> None:
        self._make_evidence("OMN-8490")
        payload = _make_hook_json("Agent", "Implement OMN-8490.")
        code, output = run_guard(payload)
        self.assertEqual(code, 0)

    def test_task_with_ticket_and_evidence_allowed(self) -> None:
        self._make_evidence("OMN-1234")
        payload = _make_hook_json("Task", "OMN-1234 — write the unit tests.")
        code, output = run_guard(payload)
        self.assertEqual(code, 0)

    # --- Pass: research-only marker ------------------------------------------

    def test_agent_research_only_exemption(self) -> None:
        payload = _make_hook_json(
            "Agent", "# research-only\nExplore the codebase structure."
        )
        code, output = run_guard(payload)
        self.assertEqual(code, 0)

    def test_task_research_only_exemption(self) -> None:
        payload = _make_hook_json(
            "Task", "# research-only\nRead all docs for OMN context."
        )
        code, output = run_guard(payload)
        self.assertEqual(code, 0)

    # --- Pass: non-dispatch tools -------------------------------------------

    def test_non_agent_task_tool_passes_through(self) -> None:
        for tool in ("Bash", "Edit", "Write", "Read"):
            payload = _make_hook_json(tool, "no ticket here")
            code, _output = run_guard(payload)
            self.assertEqual(code, 0, f"Expected pass-through for {tool}")

    # --- Pass: multiple tickets, at least one has evidence ------------------

    def test_multiple_tickets_one_has_evidence_allowed(self) -> None:
        self._make_evidence("OMN-8490")
        payload = _make_hook_json(
            "Agent", "Reference OMN-1111 and OMN-8490 for context."
        )
        code, output = run_guard(payload)
        self.assertEqual(code, 0)

    def test_multiple_tickets_none_have_evidence_blocked(self) -> None:
        payload = _make_hook_json(
            "Agent", "Reference OMN-1111 and OMN-8490 for context."
        )
        code, output = run_guard(payload)
        self.assertEqual(code, 2)

    # --- Edge: malformed JSON fails open ------------------------------------

    def test_malformed_json_passes_through(self) -> None:
        code, output = run_guard("not-valid-json{")
        self.assertEqual(code, 0)

    # --- Edge: disabled env var ----------------------------------------------

    def test_disabled_env_var_bypasses_guard(self) -> None:
        os.environ["DISPATCH_TICKET_GUARD_DISABLED"] = "1"
        payload = _make_hook_json("Agent", "No ticket, no evidence.")
        code, output = run_guard(payload)
        self.assertEqual(code, 0)

    # --- Edge: prompt in different input keys --------------------------------

    def test_prompt_in_task_key(self) -> None:
        self._make_evidence("OMN-5678")
        payload = json.dumps(
            {
                "tool_name": "Agent",
                "tool_input": {"task": "Implement OMN-5678 feature."},
            }
        )
        code, output = run_guard(payload)
        self.assertEqual(code, 0)

    def test_prompt_in_description_key(self) -> None:
        payload = json.dumps(
            {
                "tool_name": "Agent",
                "tool_input": {"description": "Do the thing."},
            }
        )
        code, output = run_guard(payload)
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
