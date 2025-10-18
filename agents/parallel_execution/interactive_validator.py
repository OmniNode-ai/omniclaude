#!/usr/bin/env python3
"""
Interactive Validation System for Human-in-the-Loop Workflow Control

Provides interactive checkpoints for reviewing and approving agent outputs
during workflow execution, with support for editing, retrying, and skipping steps.

Features:
- Interactive checkpoints at major workflow steps
- Editor integration for output modification
- Retry mode with user feedback
- Session state save/load for resuming interrupted workflows
- Colorful terminal UI with progress indicators
- Configurable timeout with auto-approval
"""

import json
import os
import sys
import tempfile
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field, asdict
from enum import Enum
from datetime import datetime


class UserChoice(Enum):
    """User choices at interactive checkpoints"""

    APPROVE = "a"
    EDIT = "e"
    RETRY = "r"
    SKIP = "s"
    QUIT = "q"
    BATCH_APPROVE = "b"


class CheckpointType(Enum):
    """Types of interactive checkpoints"""

    CONTEXT_GATHERING = "context_gathering"
    TASK_BREAKDOWN = "task_breakdown"
    AGENT_EXECUTION = "agent_execution"
    FINAL_COMPILATION = "final_compilation"


@dataclass
class CheckpointResult:
    """Result of an interactive checkpoint"""

    choice: UserChoice
    modified_output: Optional[Any] = None
    user_feedback: Optional[str] = None
    retry_count: int = 0
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class SessionState:
    """Session state for resuming interrupted workflows"""

    session_id: str
    workflow_name: str
    checkpoints_completed: List[str] = field(default_factory=list)
    checkpoints_pending: List[str] = field(default_factory=list)
    checkpoint_results: Dict[str, CheckpointResult] = field(default_factory=dict)
    batch_approve_remaining: bool = False
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        data = asdict(self)
        # Convert enum values to strings
        for checkpoint_id, result in data.get("checkpoint_results", {}).items():
            if isinstance(result.get("choice"), UserChoice):
                result["choice"] = result["choice"].value
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SessionState":
        """Create from dictionary"""
        # Convert choice strings back to enums
        checkpoint_results = {}
        for checkpoint_id, result_data in data.get("checkpoint_results", {}).items():
            result_data = result_data.copy()
            if "choice" in result_data:
                result_data["choice"] = UserChoice(result_data["choice"])
            checkpoint_results[checkpoint_id] = CheckpointResult(**result_data)

        data["checkpoint_results"] = checkpoint_results
        return cls(**data)


class Colors:
    """ANSI color codes for terminal output"""

    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"

    # Foreground colors
    BLACK = "\033[30m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"

    # Background colors
    BG_RED = "\033[41m"
    BG_GREEN = "\033[42m"
    BG_YELLOW = "\033[43m"
    BG_BLUE = "\033[44m"

    @classmethod
    def disable(cls):
        """Disable colors (for non-TTY output)"""
        for attr in dir(cls):
            if not attr.startswith("_") and attr.isupper():
                setattr(cls, attr, "")


class InteractiveValidator:
    """
    Interactive validation system for human-in-the-loop workflow control.

    Provides checkpoints at major workflow steps where users can:
    - Approve outputs and continue
    - Edit outputs before continuing
    - Retry with feedback
    - Skip validation
    - Quit workflow
    - Batch approve remaining steps
    """

    def __init__(
        self,
        session_state: Optional[SessionState] = None,
        auto_approve_timeout: Optional[int] = None,
        enable_colors: bool = True,
        session_file: Optional[Path] = None,
    ):
        """
        Initialize interactive validator.

        Args:
            session_state: Existing session state for resuming
            auto_approve_timeout: Timeout in seconds for auto-approval (None = disabled)
            enable_colors: Enable colored terminal output
            session_file: Path to session state file for save/load
        """
        self.session_state = session_state or SessionState(
            session_id=datetime.now().strftime("%Y%m%d_%H%M%S"), workflow_name="workflow"
        )
        self.auto_approve_timeout = auto_approve_timeout
        self.session_file = (
            session_file or Path(tempfile.gettempdir()) / f"interactive_session_{self.session_state.session_id}.json"
        )

        # Disable colors if not TTY or explicitly disabled
        if not enable_colors or not sys.stdout.isatty():
            Colors.disable()

        self.editor = os.environ.get("EDITOR", "nano")
        self.max_retries = 3

    def checkpoint(
        self,
        checkpoint_id: str,
        checkpoint_type: CheckpointType,
        step_number: int,
        total_steps: int,
        step_name: str,
        output_data: Any,
        quorum_result: Optional[Dict[str, Any]] = None,
        deficiencies: Optional[List[str]] = None,
    ) -> CheckpointResult:
        """
        Present interactive checkpoint to user.

        Args:
            checkpoint_id: Unique identifier for this checkpoint
            checkpoint_type: Type of checkpoint
            step_number: Current step number
            total_steps: Total number of steps
            step_name: Human-readable step name
            output_data: Output data to display and potentially modify
            quorum_result: Optional quorum validation result
            deficiencies: Optional list of issues/deficiencies

        Returns:
            CheckpointResult with user choice and any modifications
        """
        # Check if batch approve is active
        if self.session_state.batch_approve_remaining:
            print(f"{Colors.DIM}[Batch Approve] Auto-approving checkpoint: {step_name}{Colors.RESET}")
            result = CheckpointResult(choice=UserChoice.APPROVE)
            self._save_checkpoint_result(checkpoint_id, result)
            return result

        # Display checkpoint header
        self._display_checkpoint_header(step_number, total_steps, step_name)

        # Display quorum result if available
        if quorum_result:
            self._display_quorum_result(quorum_result)

        # Display deficiencies if available
        if deficiencies:
            self._display_deficiencies(deficiencies)

        # Display output data
        self._display_output(output_data, checkpoint_type)

        # Get user choice
        while True:
            choice = self._prompt_user_choice()

            if choice == UserChoice.APPROVE:
                result = CheckpointResult(choice=UserChoice.APPROVE)
                self._save_checkpoint_result(checkpoint_id, result)
                return result

            elif choice == UserChoice.EDIT:
                modified_output = self._edit_output(output_data)
                if modified_output is not None:
                    result = CheckpointResult(choice=UserChoice.EDIT, modified_output=modified_output)
                    self._save_checkpoint_result(checkpoint_id, result)
                    return result
                # If edit was cancelled, continue loop

            elif choice == UserChoice.RETRY:
                feedback = self._get_retry_feedback()
                result = CheckpointResult(choice=UserChoice.RETRY, user_feedback=feedback)
                self._save_checkpoint_result(checkpoint_id, result)
                return result

            elif choice == UserChoice.SKIP:
                result = CheckpointResult(choice=UserChoice.SKIP)
                self._save_checkpoint_result(checkpoint_id, result)
                return result

            elif choice == UserChoice.BATCH_APPROVE:
                self.session_state.batch_approve_remaining = True
                result = CheckpointResult(choice=UserChoice.APPROVE)
                self._save_checkpoint_result(checkpoint_id, result)
                print(f"{Colors.GREEN}✓ Batch approve enabled - remaining steps will auto-approve{Colors.RESET}\n")
                return result

            elif choice == UserChoice.QUIT:
                self._save_session_state()
                print(f"\n{Colors.YELLOW}Workflow interrupted. Session saved to: {self.session_file}{Colors.RESET}")
                print(f"Resume with: --resume-session {self.session_file}")
                sys.exit(0)

    def _display_checkpoint_header(self, step_number: int, total_steps: int, step_name: str):
        """Display checkpoint header with progress"""
        box_width = 60
        header = f" Step {step_number}/{total_steps}: {step_name} "
        padding = (box_width - len(header)) // 2

        print(f"\n{Colors.BOLD}{Colors.CYAN}┌{'─' * box_width}┐{Colors.RESET}")
        print(
            f"{Colors.BOLD}{Colors.CYAN}│{' ' * padding}{header}{' ' * (box_width - padding - len(header))}│{Colors.RESET}"
        )
        print(f"{Colors.BOLD}{Colors.CYAN}└{'─' * box_width}┘{Colors.RESET}\n")

    def _display_quorum_result(self, quorum_result: Dict[str, Any]):
        """Display quorum validation result"""
        decision = quorum_result.get("decision", "UNKNOWN")
        confidence = quorum_result.get("confidence", 0.0)

        # Color based on decision
        if decision == "PASS":
            color = Colors.GREEN
            symbol = "✓"
        elif decision == "RETRY":
            color = Colors.YELLOW
            symbol = "⚠"
        else:
            color = Colors.RED
            symbol = "✗"

        print(
            f"{Colors.BOLD}Quorum Decision:{Colors.RESET} {color}{symbol} {decision} ({confidence:.0%} confidence){Colors.RESET}"
        )

    def _display_deficiencies(self, deficiencies: List[str]):
        """Display deficiencies/issues found"""
        if not deficiencies:
            return

        print(f"\n{Colors.BOLD}{Colors.YELLOW}Deficiencies found:{Colors.RESET}")
        for i, deficiency in enumerate(deficiencies, 1):
            print(f"  {Colors.YELLOW}{i}.{Colors.RESET} {deficiency}")
        print()

    def _display_output(self, output_data: Any, checkpoint_type: CheckpointType):
        """Display output data in formatted form"""
        print(f"{Colors.BOLD}Output Data:{Colors.RESET}")

        # Format based on type
        if isinstance(output_data, (dict, list)):
            output_str = json.dumps(output_data, indent=2)
        else:
            output_str = str(output_data)

        # Limit output length for display
        max_lines = 30
        lines = output_str.split("\n")
        if len(lines) > max_lines:
            print("\n".join(lines[:max_lines]))
            print(f"{Colors.DIM}... ({len(lines) - max_lines} more lines, use [E]dit to view all){Colors.RESET}")
        else:
            print(output_str)
        print()

    def _prompt_user_choice(self) -> UserChoice:
        """Prompt user for choice at checkpoint"""
        options = (
            f"{Colors.BOLD}Options:{Colors.RESET}\n"
            f"  {Colors.GREEN}[A]pprove{Colors.RESET}  {Colors.CYAN}[E]dit{Colors.RESET}  "
            f"{Colors.YELLOW}[R]etry{Colors.RESET}  {Colors.MAGENTA}[S]kip{Colors.RESET}  "
            f"{Colors.BLUE}[B]atch approve{Colors.RESET}  {Colors.RED}[Q]uit{Colors.RESET}\n"
        )
        print(options)

        while True:
            try:
                choice_str = input(f"{Colors.BOLD}Your choice:{Colors.RESET} ").strip().lower()

                if not choice_str:
                    continue

                # Map input to enum
                choice_map = {
                    "a": UserChoice.APPROVE,
                    "e": UserChoice.EDIT,
                    "r": UserChoice.RETRY,
                    "s": UserChoice.SKIP,
                    "b": UserChoice.BATCH_APPROVE,
                    "q": UserChoice.QUIT,
                }

                if choice_str in choice_map:
                    return choice_map[choice_str]
                else:
                    print(f"{Colors.RED}Invalid choice. Please select A, E, R, S, B, or Q.{Colors.RESET}")

            except (EOFError, KeyboardInterrupt):
                print(f"\n{Colors.YELLOW}Interrupted. Use [Q]uit to save session state.{Colors.RESET}")
                return UserChoice.QUIT

    def _edit_output(self, output_data: Any) -> Optional[Any]:
        """
        Open output in editor for user modification.

        Args:
            output_data: Data to edit

        Returns:
            Modified data, or None if edit was cancelled
        """
        # Create temporary file with output
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp_file:
            tmp_path = Path(tmp_file.name)

            if isinstance(output_data, (dict, list)):
                json.dump(output_data, tmp_file, indent=2)
            else:
                tmp_file.write(str(output_data))

        try:
            # Open in editor
            print(f"\n{Colors.CYAN}Opening editor: {self.editor}{Colors.RESET}")
            result = subprocess.run([self.editor, str(tmp_path)])

            if result.returncode != 0:
                print(f"{Colors.RED}Editor exited with error code {result.returncode}{Colors.RESET}")
                return None

            # Read modified content
            with open(tmp_path, "r") as f:
                modified_content = f.read()

            # Try to parse as JSON
            try:
                modified_data = json.loads(modified_content)
                print(f"{Colors.GREEN}✓ Successfully parsed modified JSON{Colors.RESET}")
                return modified_data
            except json.JSONDecodeError:
                # Not JSON, return as string
                print(f"{Colors.YELLOW}⚠ Modified content is not valid JSON, returning as text{Colors.RESET}")
                return modified_content

        except Exception as e:
            print(f"{Colors.RED}Error during edit: {e}{Colors.RESET}")
            return None

        finally:
            # Clean up temp file
            tmp_path.unlink(missing_ok=True)

    def _get_retry_feedback(self) -> str:
        """
        Get feedback from user for retry.

        Returns:
            User feedback as string
        """
        print(f"\n{Colors.BOLD}Enter feedback for retry:{Colors.RESET}")
        print(f"{Colors.DIM}(Press Enter twice to finish){Colors.RESET}\n")

        lines = []
        empty_count = 0

        while True:
            try:
                line = input("> ")

                if not line:
                    empty_count += 1
                    if empty_count >= 2:
                        break
                else:
                    empty_count = 0
                    lines.append(line)

            except (EOFError, KeyboardInterrupt):
                break

        feedback = "\n".join(lines)

        if feedback:
            print(f"\n{Colors.GREEN}✓ Feedback captured ({len(feedback)} characters){Colors.RESET}")
        else:
            print(f"\n{Colors.YELLOW}⚠ No feedback provided{Colors.RESET}")

        return feedback

    def _save_checkpoint_result(self, checkpoint_id: str, result: CheckpointResult):
        """Save checkpoint result to session state"""
        self.session_state.checkpoint_results[checkpoint_id] = result
        self.session_state.checkpoints_completed.append(checkpoint_id)
        self._save_session_state()

    def _save_session_state(self):
        """Save session state to file"""
        try:
            with open(self.session_file, "w") as f:
                json.dump(self.session_state.to_dict(), f, indent=2)
        except Exception as e:
            print(f"{Colors.RED}Warning: Failed to save session state: {e}{Colors.RESET}", file=sys.stderr)

    @classmethod
    def load_session(cls, session_file: Path) -> "InteractiveValidator":
        """
        Load session from file.

        Args:
            session_file: Path to session state file

        Returns:
            InteractiveValidator with loaded session state
        """
        with open(session_file, "r") as f:
            state_data = json.load(f)

        session_state = SessionState.from_dict(state_data)
        return cls(session_state=session_state, session_file=session_file)


class QuietValidator:
    """
    Non-interactive validator that auto-approves all checkpoints.

    Used as a drop-in replacement for InteractiveValidator when
    --interactive flag is not set.
    """

    def checkpoint(
        self,
        checkpoint_id: str,
        checkpoint_type: CheckpointType,
        step_number: int,
        total_steps: int,
        step_name: str,
        output_data: Any,
        quorum_result: Optional[Dict[str, Any]] = None,
        deficiencies: Optional[List[str]] = None,
    ) -> CheckpointResult:
        """Auto-approve checkpoint without user interaction"""
        return CheckpointResult(choice=UserChoice.APPROVE)


def create_validator(
    interactive: bool = False, session_file: Optional[Path] = None, auto_approve_timeout: Optional[int] = None
) -> InteractiveValidator | QuietValidator:
    """
    Factory function to create appropriate validator.

    Args:
        interactive: Enable interactive mode
        session_file: Path to session file for resuming
        auto_approve_timeout: Timeout for auto-approval

    Returns:
        InteractiveValidator or QuietValidator
    """
    if not interactive:
        return QuietValidator()

    if session_file and session_file.exists():
        print(f"Resuming session from: {session_file}")
        return InteractiveValidator.load_session(session_file)

    return InteractiveValidator(auto_approve_timeout=auto_approve_timeout, session_file=session_file)


if __name__ == "__main__":
    """Test the interactive validator"""

    validator = create_validator(interactive=True)

    # Test checkpoint
    test_output = {
        "node_type": "Effect",
        "name": "PostgreSQLAdapter",
        "description": "Adapter for PostgreSQL database operations",
        "methods": ["connect", "execute_query", "close"],
    }

    test_quorum = {"decision": "PASS", "confidence": 0.87, "deficiencies": []}

    result = validator.checkpoint(
        checkpoint_id="test_1",
        checkpoint_type=CheckpointType.TASK_BREAKDOWN,
        step_number=1,
        total_steps=4,
        step_name="Task Breakdown Validation",
        output_data=test_output,
        quorum_result=test_quorum,
    )

    print(f"\nResult: {result.choice.name}")
    if result.modified_output:
        print("Modified output:")
        print(json.dumps(result.modified_output, indent=2))
    if result.user_feedback:
        print(f"User feedback: {result.user_feedback}")
