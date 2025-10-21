#!/usr/bin/env python3
"""
Test Suite for Interactive Validation Mode

Tests the interactive validation system components:
- InteractiveValidator checkpoints
- Session state management
- Editor integration (mocked)
- User choice handling
- QuietValidator fallback
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from interactive_validator import (
    CheckpointResult,
    CheckpointType,
    Colors,
    InteractiveValidator,
    QuietValidator,
    SessionState,
    UserChoice,
    create_validator,
)


class TestSessionState:
    """Test session state management"""

    def test_session_state_creation(self):
        """Test creating session state"""
        state = SessionState(session_id="test_123", workflow_name="test_workflow")

        assert state.session_id == "test_123"
        assert state.workflow_name == "test_workflow"
        assert len(state.checkpoints_completed) == 0
        assert len(state.checkpoints_pending) == 0

    def test_session_state_serialization(self):
        """Test session state to/from dict conversion"""
        state = SessionState(session_id="test_123", workflow_name="test_workflow")

        # Add a checkpoint result
        result = CheckpointResult(choice=UserChoice.APPROVE)
        state.checkpoint_results["test_checkpoint"] = result
        state.checkpoints_completed.append("test_checkpoint")

        # Serialize and deserialize
        state_dict = state.to_dict()
        restored_state = SessionState.from_dict(state_dict)

        assert restored_state.session_id == state.session_id
        assert restored_state.workflow_name == state.workflow_name
        assert len(restored_state.checkpoint_results) == 1
        assert "test_checkpoint" in restored_state.checkpoint_results

    def test_checkpoint_result_enum_conversion(self):
        """Test enum values are properly converted in serialization"""
        state = SessionState(session_id="test", workflow_name="test")
        result = CheckpointResult(
            choice=UserChoice.EDIT, modified_output={"test": "data"}
        )
        state.checkpoint_results["edit_test"] = result

        # Serialize
        state_dict = state.to_dict()
        assert state_dict["checkpoint_results"]["edit_test"]["choice"] == "e"

        # Deserialize
        restored = SessionState.from_dict(state_dict)
        assert restored.checkpoint_results["edit_test"].choice == UserChoice.EDIT


class TestQuietValidator:
    """Test QuietValidator (non-interactive mode)"""

    def test_quiet_validator_auto_approves(self):
        """Test that QuietValidator auto-approves all checkpoints"""
        validator = QuietValidator()

        result = validator.checkpoint(
            checkpoint_id="test_1",
            checkpoint_type=CheckpointType.TASK_BREAKDOWN,
            step_number=1,
            total_steps=3,
            step_name="Test Checkpoint",
            output_data={"test": "data"},
        )

        assert result.choice == UserChoice.APPROVE
        assert result.modified_output is None
        assert result.user_feedback is None


class TestCreateValidator:
    """Test validator factory function"""

    def test_create_quiet_validator(self):
        """Test creating non-interactive validator"""
        validator = create_validator(interactive=False)
        assert isinstance(validator, QuietValidator)

    def test_create_interactive_validator(self):
        """Test creating interactive validator"""
        validator = create_validator(interactive=True)
        assert isinstance(validator, InteractiveValidator)

    def test_create_with_session_file(self, tmp_path):
        """Test creating validator with session file"""
        session_file = tmp_path / "test_session.json"

        # Create initial session
        state = SessionState(session_id="test", workflow_name="test")
        with open(session_file, "w") as f:
            json.dump(state.to_dict(), f)

        # Load validator with session
        validator = create_validator(interactive=True, session_file=session_file)

        assert isinstance(validator, InteractiveValidator)
        assert validator.session_state.session_id == "test"


class TestInteractiveValidator:
    """Test InteractiveValidator with mocked user input"""

    def test_checkpoint_with_approve(self):
        """Test checkpoint with user approval"""
        validator = InteractiveValidator()

        with patch("builtins.input", return_value="a"):
            result = validator.checkpoint(
                checkpoint_id="test_approve",
                checkpoint_type=CheckpointType.TASK_BREAKDOWN,
                step_number=1,
                total_steps=3,
                step_name="Test Approval",
                output_data={"test": "data"},
            )

        assert result.choice == UserChoice.APPROVE
        assert "test_approve" in validator.session_state.checkpoints_completed

    def test_checkpoint_with_skip(self):
        """Test checkpoint with skip"""
        validator = InteractiveValidator()

        with patch("builtins.input", return_value="s"):
            result = validator.checkpoint(
                checkpoint_id="test_skip",
                checkpoint_type=CheckpointType.TASK_BREAKDOWN,
                step_number=1,
                total_steps=3,
                step_name="Test Skip",
                output_data={"test": "data"},
            )

        assert result.choice == UserChoice.SKIP

    def test_checkpoint_with_batch_approve(self):
        """Test checkpoint with batch approve"""
        validator = InteractiveValidator()

        with patch("builtins.input", return_value="b"):
            result1 = validator.checkpoint(
                checkpoint_id="test_batch_1",
                checkpoint_type=CheckpointType.TASK_BREAKDOWN,
                step_number=1,
                total_steps=3,
                step_name="Test Batch 1",
                output_data={"test": "data"},
            )

        assert result1.choice == UserChoice.APPROVE
        assert validator.session_state.batch_approve_remaining is True

        # Next checkpoint should auto-approve
        result2 = validator.checkpoint(
            checkpoint_id="test_batch_2",
            checkpoint_type=CheckpointType.AGENT_EXECUTION,
            step_number=2,
            total_steps=3,
            step_name="Test Batch 2",
            output_data={"test": "data"},
        )

        assert result2.choice == UserChoice.APPROVE
        # No input should have been requested

    def test_checkpoint_with_retry_feedback(self):
        """Test checkpoint with retry and feedback"""
        validator = InteractiveValidator()

        # Mock input sequence: 'r' for retry, then feedback lines, then empty lines
        input_sequence = iter(
            [
                "r",  # Choose retry
                "This is feedback line 1",
                "This is feedback line 2",
                "",  # First empty line
                "",  # Second empty line to finish
            ]
        )

        with patch("builtins.input", lambda *args, **kwargs: next(input_sequence)):
            result = validator.checkpoint(
                checkpoint_id="test_retry",
                checkpoint_type=CheckpointType.TASK_BREAKDOWN,
                step_number=1,
                total_steps=3,
                step_name="Test Retry",
                output_data={"test": "data"},
            )

        assert result.choice == UserChoice.RETRY
        assert result.user_feedback is not None
        assert "feedback line 1" in result.user_feedback
        assert "feedback line 2" in result.user_feedback

    def test_checkpoint_with_quorum_result(self):
        """Test checkpoint with quorum validation result"""
        validator = InteractiveValidator()

        quorum_result = {"decision": "PASS", "confidence": 0.87, "deficiencies": []}

        with patch("builtins.input", return_value="a"):
            result = validator.checkpoint(
                checkpoint_id="test_quorum",
                checkpoint_type=CheckpointType.TASK_BREAKDOWN,
                step_number=1,
                total_steps=3,
                step_name="Test with Quorum",
                output_data={"test": "data"},
                quorum_result=quorum_result,
            )

        assert result.choice == UserChoice.APPROVE

    def test_checkpoint_with_deficiencies(self):
        """Test checkpoint with deficiencies list"""
        validator = InteractiveValidator()

        deficiencies = ["Wrong node type", "Missing requirement: database pooling"]

        with patch("builtins.input", return_value="a"):
            result = validator.checkpoint(
                checkpoint_id="test_deficiencies",
                checkpoint_type=CheckpointType.TASK_BREAKDOWN,
                step_number=1,
                total_steps=3,
                step_name="Test with Deficiencies",
                output_data={"test": "data"},
                deficiencies=deficiencies,
            )

        assert result.choice == UserChoice.APPROVE

    def test_session_state_persistence(self, tmp_path):
        """Test session state is saved to file"""
        session_file = tmp_path / "test_session.json"
        validator = InteractiveValidator(session_file=session_file)

        with patch("builtins.input", return_value="a"):
            validator.checkpoint(
                checkpoint_id="test_persist",
                checkpoint_type=CheckpointType.TASK_BREAKDOWN,
                step_number=1,
                total_steps=3,
                step_name="Test Persistence",
                output_data={"test": "data"},
            )

        # Check session file was created
        assert session_file.exists()

        # Load and verify
        with open(session_file, "r") as f:
            saved_state = json.load(f)

        assert "test_persist" in saved_state["checkpoints_completed"]

    def test_invalid_choice_retry(self):
        """Test handling of invalid user input"""
        validator = InteractiveValidator()

        # Mock input sequence: invalid input, then valid approval
        input_sequence = iter(["x", "a"])  # Invalid choice  # Valid approval

        with patch("builtins.input", lambda *args, **kwargs: next(input_sequence)):
            result = validator.checkpoint(
                checkpoint_id="test_invalid",
                checkpoint_type=CheckpointType.TASK_BREAKDOWN,
                step_number=1,
                total_steps=3,
                step_name="Test Invalid Input",
                output_data={"test": "data"},
            )

        assert result.choice == UserChoice.APPROVE

    def test_colors_disabled_for_non_tty(self):
        """Test colors are disabled when not on TTY"""
        Colors.disable()

        assert Colors.RED == ""
        assert Colors.GREEN == ""
        assert Colors.BOLD == ""


class TestEditorIntegration:
    """Test editor integration (mocked)"""

    def test_edit_output_success(self, tmp_path):
        """Test successful edit workflow"""
        validator = InteractiveValidator()

        original_data = {"test": "original"}
        modified_data = {"test": "modified"}

        # Mock editor subprocess and file operations
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            with patch("builtins.open", create=True) as mock_open:
                # Mock reading the modified file
                mock_file = MagicMock()
                mock_file.read.return_value = json.dumps(modified_data)
                mock_open.return_value.__enter__.return_value = mock_file

                result = validator._edit_output(original_data)

        assert result == modified_data

    def test_edit_output_editor_error(self):
        """Test editor exits with error"""
        validator = InteractiveValidator()

        original_data = {"test": "original"}

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)

            result = validator._edit_output(original_data)

        assert result is None

    def test_edit_output_invalid_json(self, tmp_path):
        """Test handling of invalid JSON after edit"""
        validator = InteractiveValidator()

        original_data = {"test": "original"}

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            with patch("builtins.open", create=True) as mock_open:
                # Mock reading invalid JSON
                mock_file = MagicMock()
                mock_file.read.return_value = "invalid json content"
                mock_open.return_value.__enter__.return_value = mock_file

                result = validator._edit_output(original_data)

        # Should return as text when JSON parsing fails
        assert result == "invalid json content"


class TestDispatchRunnerIntegration:
    """Test integration with dispatch_runner"""

    @pytest.mark.asyncio
    async def test_interactive_flag_parsing(self):
        """Test command-line flag parsing"""
        import sys

        # Save original argv
        original_argv = sys.argv.copy()

        try:
            # Test --interactive flag
            sys.argv = ["dispatch_runner.py", "--interactive"]
            enable_interactive = "--interactive" in sys.argv or "-i" in sys.argv
            assert enable_interactive is True

            # Test -i flag
            sys.argv = ["dispatch_runner.py", "-i"]
            enable_interactive = "--interactive" in sys.argv or "-i" in sys.argv
            assert enable_interactive is True

            # Test no flag
            sys.argv = ["dispatch_runner.py"]
            enable_interactive = "--interactive" in sys.argv or "-i" in sys.argv
            assert enable_interactive is False

        finally:
            # Restore original argv
            sys.argv = original_argv

    @pytest.mark.asyncio
    async def test_resume_session_flag_parsing(self):
        """Test --resume-session flag parsing"""
        import sys

        original_argv = sys.argv.copy()

        try:
            sys.argv = ["dispatch_runner.py", "--resume-session", "/tmp/session.json"]

            resume_session_file = None
            if "--resume-session" in sys.argv:
                idx = sys.argv.index("--resume-session")
                if idx + 1 < len(sys.argv):
                    resume_session_file = Path(sys.argv[idx + 1])

            assert resume_session_file == Path("/tmp/session.json")

        finally:
            sys.argv = original_argv


def run_tests():
    """Run all tests"""
    pytest.main([__file__, "-v", "--tb=short"])


if __name__ == "__main__":
    # Run tests
    run_tests()
