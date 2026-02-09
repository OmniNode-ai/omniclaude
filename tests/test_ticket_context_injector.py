#!/usr/bin/env python3
"""Unit tests for ticket_context_injector.py module.

Tests the ticket context injection functionality used by SessionStart hooks
to inject active ticket context from the /ticket-work workflow.

Part of OMN-1830: Hook integration and session continuity.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

# Import the module under test
# conftest.py already adds plugins/onex/hooks/lib to sys.path
import ticket_context_injector
import yaml
from ticket_context_injector import (
    build_ticket_context,
    find_active_ticket,
)


class TestFindActiveTicket:
    """Tests for find_active_ticket() function."""

    def test_find_active_ticket_no_directory(self, tmp_path: Path) -> None:
        """Returns None when tickets directory doesn't exist."""
        nonexistent_dir = tmp_path / "nonexistent" / "tickets"

        result = find_active_ticket(tickets_dir=nonexistent_dir)

        assert result is None

    def test_find_active_ticket_empty_directory(self, tmp_path: Path) -> None:
        """Returns None when directory exists but has no tickets."""
        tickets_dir = tmp_path / "tickets"
        tickets_dir.mkdir(parents=True)

        result = find_active_ticket(tickets_dir=tickets_dir)

        assert result is None

    def test_find_active_ticket_single_ticket(self, tmp_path: Path) -> None:
        """Returns the ticket ID when one ticket exists."""
        tickets_dir = tmp_path / "tickets"
        ticket_id = "OMN-1234"
        ticket_dir = tickets_dir / ticket_id
        ticket_dir.mkdir(parents=True)

        # Create contract.yaml
        contract_path = ticket_dir / "contract.yaml"
        contract_data = {
            "ticket_id": ticket_id,
            "title": "Test Ticket",
            "repo": "omniclaude",
            "branch": "feature/test",
            "phase": "implementation",
        }
        with contract_path.open("w") as f:
            yaml.dump(contract_data, f)

        result = find_active_ticket(tickets_dir=tickets_dir)

        assert result == ticket_id

    def test_find_active_ticket_most_recent(self, tmp_path: Path) -> None:
        """Returns the most recently modified ticket when multiple exist."""
        tickets_dir = tmp_path / "tickets"
        tickets_dir.mkdir(parents=True)

        # Create older ticket
        old_ticket_id = "OMN-1000"
        old_ticket_dir = tickets_dir / old_ticket_id
        old_ticket_dir.mkdir()
        old_contract = old_ticket_dir / "contract.yaml"
        with old_contract.open("w") as f:
            yaml.dump({"ticket_id": old_ticket_id, "title": "Old Ticket"}, f)

        # Sleep briefly to ensure different mtime
        time.sleep(0.05)

        # Create newer ticket
        new_ticket_id = "OMN-2000"
        new_ticket_dir = tickets_dir / new_ticket_id
        new_ticket_dir.mkdir()
        new_contract = new_ticket_dir / "contract.yaml"
        with new_contract.open("w") as f:
            yaml.dump({"ticket_id": new_ticket_id, "title": "New Ticket"}, f)

        result = find_active_ticket(tickets_dir=tickets_dir)

        assert result == new_ticket_id

    def test_find_active_ticket_path_is_file_not_directory(
        self, tmp_path: Path
    ) -> None:
        """Returns None when tickets path is a file, not a directory."""
        tickets_file = tmp_path / "tickets"
        tickets_file.touch()  # Create as file, not directory

        result = find_active_ticket(tickets_dir=tickets_file)

        assert result is None

    def test_find_active_ticket_skips_files_in_tickets_dir(
        self, tmp_path: Path
    ) -> None:
        """Ignores files in tickets directory (only searches subdirectories)."""
        tickets_dir = tmp_path / "tickets"
        tickets_dir.mkdir(parents=True)

        # Create a file directly in tickets_dir (should be ignored)
        random_file = tickets_dir / "random.txt"
        random_file.touch()

        # Create a valid ticket in subdirectory
        ticket_id = "OMN-5555"
        ticket_dir = tickets_dir / ticket_id
        ticket_dir.mkdir()
        contract = ticket_dir / "contract.yaml"
        with contract.open("w") as f:
            yaml.dump({"ticket_id": ticket_id}, f)

        result = find_active_ticket(tickets_dir=tickets_dir)

        assert result == ticket_id

    def test_find_active_ticket_skips_dirs_without_contract(
        self, tmp_path: Path
    ) -> None:
        """Skips ticket directories that don't have contract.yaml."""
        tickets_dir = tmp_path / "tickets"
        tickets_dir.mkdir(parents=True)

        # Create directory without contract.yaml
        no_contract_dir = tickets_dir / "OMN-0001"
        no_contract_dir.mkdir()

        # Create directory with contract.yaml
        valid_ticket_id = "OMN-0002"
        valid_dir = tickets_dir / valid_ticket_id
        valid_dir.mkdir()
        contract = valid_dir / "contract.yaml"
        with contract.open("w") as f:
            yaml.dump({"ticket_id": valid_ticket_id}, f)

        result = find_active_ticket(tickets_dir=tickets_dir)

        assert result == valid_ticket_id


class TestBuildTicketContext:
    """Tests for build_ticket_context() function."""

    def test_build_ticket_context_missing_contract(self, tmp_path: Path) -> None:
        """Returns empty string when contract doesn't exist."""
        tickets_dir = tmp_path / "tickets"
        tickets_dir.mkdir(parents=True)

        result = build_ticket_context(
            ticket_id="OMN-9999",
            tickets_dir=tickets_dir,
        )

        assert result == ""

    def test_build_ticket_context_valid_contract(self, tmp_path: Path) -> None:
        """Returns formatted markdown for valid contract."""
        tickets_dir = tmp_path / "tickets"
        ticket_id = "OMN-1234"
        ticket_dir = tickets_dir / ticket_id
        ticket_dir.mkdir(parents=True)

        # Create contract with all fields
        contract_data = {
            "ticket_id": ticket_id,
            "title": "Implement Feature X",
            "repo": "omniclaude",
            "branch": "feature/omn-1234",
            "phase": "implementation",
            "questions": [
                {"question": "What is X?", "answer": "Answer here"},
                {"question": "How to do Y?", "answer": None},  # Pending
            ],
            "gates": [
                {"name": "spec-approval", "status": "approved"},
                {"name": "implementation", "status": "pending"},
            ],
        }
        contract_path = ticket_dir / "contract.yaml"
        with contract_path.open("w") as f:
            yaml.dump(contract_data, f)

        result = build_ticket_context(ticket_id, tickets_dir)

        # Verify all expected content
        assert f"## Active Ticket: {ticket_id}" in result
        assert "**Implement Feature X**" in result
        assert "- Repository: omniclaude" in result
        assert "- Branch: feature/omn-1234" in result
        assert "- Phase: implementation" in result
        assert "- Pending Questions: 1" in result  # One with null answer
        assert "- Pending Gates: 1" in result  # One not approved
        assert f"Run `/ticket-work {ticket_id}` to continue." in result

    def test_build_ticket_context_missing_fields(self, tmp_path: Path) -> None:
        """Handles contracts with missing optional fields gracefully."""
        tickets_dir = tmp_path / "tickets"
        ticket_id = "OMN-MINIMAL"
        ticket_dir = tickets_dir / ticket_id
        ticket_dir.mkdir(parents=True)

        # Minimal contract - only ticket_id
        contract_data = {
            "ticket_id": ticket_id,
        }
        contract_path = ticket_dir / "contract.yaml"
        with contract_path.open("w") as f:
            yaml.dump(contract_data, f)

        result = build_ticket_context(ticket_id, tickets_dir)

        # Should use defaults
        assert f"## Active Ticket: {ticket_id}" in result
        assert "**Untitled**" in result  # Default title
        assert "- Repository: unknown" in result  # Default repo
        assert "- Branch: not created" in result  # Default when branch is None
        assert "- Phase: unknown" in result  # Default phase
        assert "- Pending Questions: 0" in result  # No questions
        assert "- Pending Gates: 0" in result  # No gates

    def test_build_ticket_context_empty_branch(self, tmp_path: Path) -> None:
        """Handles empty string branch as 'not created'."""
        tickets_dir = tmp_path / "tickets"
        ticket_id = "OMN-NOBRANCH"
        ticket_dir = tickets_dir / ticket_id
        ticket_dir.mkdir(parents=True)

        contract_data = {
            "ticket_id": ticket_id,
            "title": "No Branch Yet",
            "branch": "",  # Empty string
        }
        contract_path = ticket_dir / "contract.yaml"
        with contract_path.open("w") as f:
            yaml.dump(contract_data, f)

        result = build_ticket_context(ticket_id, tickets_dir)

        assert "- Branch: not created" in result

    def test_build_ticket_context_invalid_yaml(self, tmp_path: Path) -> None:
        """Returns empty string for invalid YAML content."""
        tickets_dir = tmp_path / "tickets"
        ticket_id = "OMN-INVALID"
        ticket_dir = tickets_dir / ticket_id
        ticket_dir.mkdir(parents=True)

        # Write invalid YAML
        contract_path = ticket_dir / "contract.yaml"
        with contract_path.open("w") as f:
            f.write("this: is: not: valid: yaml: {{{}}")

        result = build_ticket_context(ticket_id, tickets_dir)

        # Should return empty string on parse error
        assert result == ""

    def test_build_ticket_context_empty_yaml_file(self, tmp_path: Path) -> None:
        """Returns empty string for empty YAML file."""
        tickets_dir = tmp_path / "tickets"
        ticket_id = "OMN-EMPTY"
        ticket_dir = tickets_dir / ticket_id
        ticket_dir.mkdir(parents=True)

        # Create empty contract file
        contract_path = ticket_dir / "contract.yaml"
        contract_path.touch()

        result = build_ticket_context(ticket_id, tickets_dir)

        assert result == ""

    def test_build_ticket_context_counts_empty_string_answers_as_pending(
        self, tmp_path: Path
    ) -> None:
        """Counts questions with empty string answers as pending."""
        tickets_dir = tmp_path / "tickets"
        ticket_id = "OMN-PENDING"
        ticket_dir = tickets_dir / ticket_id
        ticket_dir.mkdir(parents=True)

        contract_data = {
            "ticket_id": ticket_id,
            "title": "Test",
            "questions": [
                {"question": "Q1", "answer": ""},  # Empty string = pending
                {"question": "Q2", "answer": None},  # None = pending
                {"question": "Q3", "answer": "Valid answer"},  # Not pending
            ],
        }
        contract_path = ticket_dir / "contract.yaml"
        with contract_path.open("w") as f:
            yaml.dump(contract_data, f)

        result = build_ticket_context(ticket_id, tickets_dir)

        assert "- Pending Questions: 2" in result

    def test_build_ticket_context_counts_non_approved_gates(
        self, tmp_path: Path
    ) -> None:
        """Counts gates with status != 'approved' as pending."""
        tickets_dir = tmp_path / "tickets"
        ticket_id = "OMN-GATES"
        ticket_dir = tickets_dir / ticket_id
        ticket_dir.mkdir(parents=True)

        contract_data = {
            "ticket_id": ticket_id,
            "title": "Test Gates",
            "gates": [
                {"name": "gate1", "status": "approved"},
                {"name": "gate2", "status": "pending"},
                {"name": "gate3", "status": "blocked"},
                {"name": "gate4", "status": ""},  # Empty string != approved
            ],
        }
        contract_path = ticket_dir / "contract.yaml"
        with contract_path.open("w") as f:
            yaml.dump(contract_data, f)

        result = build_ticket_context(ticket_id, tickets_dir)

        assert "- Pending Gates: 3" in result  # All except gate1


class TestOutputHelpers:
    """Tests for output helper functions."""

    def test_create_error_output_returns_success(self) -> None:
        """_create_error_output returns success=True for hook compatibility."""
        # Access internal function via module
        result = ticket_context_injector._create_error_output(retrieval_ms=100)

        # CRITICAL: Always success=True for hook compatibility
        assert result["success"] is True
        assert result["ticket_context"] == ""
        assert result["ticket_id"] is None
        assert result["retrieval_ms"] == 100

    def test_create_error_output_tracks_retrieval_time(self) -> None:
        """_create_error_output properly tracks retrieval_ms parameter."""
        result = ticket_context_injector._create_error_output(retrieval_ms=42)
        assert result["retrieval_ms"] == 42

        result_zero = ticket_context_injector._create_error_output(retrieval_ms=0)
        assert result_zero["retrieval_ms"] == 0


class TestCliMain:
    """Tests for CLI main() function via subprocess."""

    def _run_cli(self, input_json: str, tickets_dir: Path | None = None) -> dict:
        """Helper to run the CLI and parse output."""
        script_path = (
            Path(__file__).parent.parent
            / "plugins"
            / "onex"
            / "hooks"
            / "lib"
            / "ticket_context_injector.py"
        )

        result = subprocess.run(
            [sys.executable, str(script_path)],
            input=input_json,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,  # We check returncode manually below
        )

        # Should always exit 0 for hook compatibility
        assert result.returncode == 0, (
            f"CLI returned {result.returncode}: {result.stderr}"
        )

        return json.loads(result.stdout)

    def test_cli_main_no_input(self, tmp_path: Path) -> None:
        """CLI returns success with empty context for empty input."""
        # Use isolated empty tickets_dir to avoid reading real ~/.claude/tickets/
        empty_tickets_dir = tmp_path / "empty_tickets"
        empty_tickets_dir.mkdir(parents=True)
        input_json = json.dumps({"tickets_dir": str(empty_tickets_dir)})
        output = self._run_cli(input_json)

        assert output["success"] is True
        assert output["ticket_context"] == ""
        assert output["ticket_id"] is None
        assert "retrieval_ms" in output

    def test_cli_main_nonexistent_tickets_dir(self, tmp_path: Path) -> None:
        """CLI handles nonexistent tickets directory gracefully."""
        # Use isolated nonexistent tickets_dir to avoid reading real ~/.claude/tickets/
        # Note: Empty string input means we can't pass tickets_dir via JSON,
        # so we use a directory that doesn't exist yet (tmp_path subdir)
        nonexistent_dir = tmp_path / "nonexistent_tickets"
        # Don't create it - passing empty string simulates no JSON input,
        # but we need to test with an isolated dir. Use minimal JSON instead.
        input_json = json.dumps({"tickets_dir": str(nonexistent_dir)})
        output = self._run_cli(input_json)

        assert output["success"] is True
        assert output["ticket_context"] == ""

    def test_cli_main_invalid_json(self) -> None:
        """CLI handles invalid JSON input gracefully (exits 0)."""
        output = self._run_cli("this is not json {{{")

        # CRITICAL: Must still succeed for hook compatibility
        assert output["success"] is True
        assert output["ticket_context"] == ""

    def test_cli_main_with_custom_tickets_dir(self, tmp_path: Path) -> None:
        """CLI respects custom tickets_dir parameter."""
        tickets_dir = tmp_path / "custom_tickets"
        ticket_id = "OMN-CLI-TEST"
        ticket_dir = tickets_dir / ticket_id
        ticket_dir.mkdir(parents=True)

        # Create contract
        contract_data = {
            "ticket_id": ticket_id,
            "title": "CLI Test Ticket",
            "repo": "test-repo",
            "branch": "feature/cli-test",
            "phase": "testing",
        }
        contract_path = ticket_dir / "contract.yaml"
        with contract_path.open("w") as f:
            yaml.dump(contract_data, f)

        input_json = json.dumps({"tickets_dir": str(tickets_dir)})
        output = self._run_cli(input_json)

        assert output["success"] is True
        assert output["ticket_id"] == ticket_id
        assert "CLI Test Ticket" in output["ticket_context"]
        assert "feature/cli-test" in output["ticket_context"]

    def test_cli_main_with_explicit_ticket_id(self, tmp_path: Path) -> None:
        """CLI uses explicit ticket_id if provided."""
        tickets_dir = tmp_path / "tickets"

        # Create two tickets
        old_ticket_id = "OMN-OLD"
        old_dir = tickets_dir / old_ticket_id
        old_dir.mkdir(parents=True)
        with (old_dir / "contract.yaml").open("w") as f:
            yaml.dump({"ticket_id": old_ticket_id, "title": "Old"}, f)

        time.sleep(0.05)

        new_ticket_id = "OMN-NEW"
        new_dir = tickets_dir / new_ticket_id
        new_dir.mkdir(parents=True)
        with (new_dir / "contract.yaml").open("w") as f:
            yaml.dump({"ticket_id": new_ticket_id, "title": "New"}, f)

        # Request the old ticket explicitly (not the most recent)
        input_json = json.dumps(
            {
                "tickets_dir": str(tickets_dir),
                "ticket_id": old_ticket_id,
            }
        )
        output = self._run_cli(input_json)

        assert output["success"] is True
        assert output["ticket_id"] == old_ticket_id
        assert "Old" in output["ticket_context"]

    def test_cli_main_nonexistent_explicit_ticket(self, tmp_path: Path) -> None:
        """CLI returns empty context when explicit ticket_id doesn't exist."""
        tickets_dir = tmp_path / "tickets"
        tickets_dir.mkdir(parents=True)

        input_json = json.dumps(
            {
                "tickets_dir": str(tickets_dir),
                "ticket_id": "OMN-NONEXISTENT",
            }
        )
        output = self._run_cli(input_json)

        assert output["success"] is True
        # ticket_id is preserved even when context building fails
        assert output["ticket_id"] == "OMN-NONEXISTENT"
        assert output["ticket_context"] == ""

    def test_cli_main_retrieval_time_tracked(self, tmp_path: Path) -> None:
        """CLI tracks retrieval time in milliseconds."""
        output = self._run_cli("{}")

        assert "retrieval_ms" in output
        assert isinstance(output["retrieval_ms"], int)
        assert output["retrieval_ms"] >= 0


class TestIntegrationScenarios:
    """Integration tests for realistic usage scenarios."""

    def test_full_workflow_find_and_build(self, tmp_path: Path) -> None:
        """Complete workflow: find active ticket and build context."""
        tickets_dir = tmp_path / "tickets"
        ticket_id = "OMN-1830"
        ticket_dir = tickets_dir / ticket_id
        ticket_dir.mkdir(parents=True)

        # Realistic contract from /ticket-work workflow
        contract_data = {
            "ticket_id": ticket_id,
            "title": "Hook Integration for Session Continuity",
            "repo": "omniclaude",
            "branch": "feature/omn-1830-hook-integration",
            "phase": "implementation",
            "questions": [
                {
                    "question": "What hooks need to be modified?",
                    "answer": "SessionStart, UserPromptSubmit",
                },
                {
                    "question": "How should context be injected?",
                    "answer": None,
                },
            ],
            "gates": [
                {"name": "spec-approval", "status": "approved"},
                {"name": "implementation-complete", "status": "pending"},
                {"name": "pr-review", "status": "pending"},
            ],
        }
        contract_path = ticket_dir / "contract.yaml"
        with contract_path.open("w") as f:
            yaml.dump(contract_data, f)

        # Step 1: Find active ticket
        found_ticket = find_active_ticket(tickets_dir)
        assert found_ticket == ticket_id

        # Step 2: Build context
        context = build_ticket_context(found_ticket, tickets_dir)

        # Verify context is usable
        assert len(context) > 0
        assert ticket_id in context
        assert "Hook Integration" in context
        assert "Pending Questions: 1" in context
        assert "Pending Gates: 2" in context

    def test_handles_malformed_questions_list(self, tmp_path: Path) -> None:
        """Gracefully handles questions that aren't list of dicts."""
        tickets_dir = tmp_path / "tickets"
        ticket_id = "OMN-MALFORMED"
        ticket_dir = tickets_dir / ticket_id
        ticket_dir.mkdir(parents=True)

        # Questions is a string instead of list
        contract_data = {
            "ticket_id": ticket_id,
            "title": "Malformed Questions",
            "questions": "This should be a list",
        }
        contract_path = ticket_dir / "contract.yaml"
        with contract_path.open("w") as f:
            yaml.dump(contract_data, f)

        result = build_ticket_context(ticket_id, tickets_dir)

        # Should still work, just with 0 pending questions
        assert "Pending Questions: 0" in result

    def test_handles_malformed_gates_list(self, tmp_path: Path) -> None:
        """Gracefully handles gates that aren't list of dicts."""
        tickets_dir = tmp_path / "tickets"
        ticket_id = "OMN-BADGATES"
        ticket_dir = tickets_dir / ticket_id
        ticket_dir.mkdir(parents=True)

        # Gates contains non-dict items
        contract_data = {
            "ticket_id": ticket_id,
            "title": "Bad Gates",
            "gates": ["gate1", "gate2"],  # Strings instead of dicts
        }
        contract_path = ticket_dir / "contract.yaml"
        with contract_path.open("w") as f:
            yaml.dump(contract_data, f)

        result = build_ticket_context(ticket_id, tickets_dir)

        # Should still work, just with 0 pending gates
        assert "Pending Gates: 0" in result
