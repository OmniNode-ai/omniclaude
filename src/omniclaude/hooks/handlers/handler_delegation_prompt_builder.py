# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Delegation prompt builder for ticket-work local LLM dispatch.

Builds self-contained prompts that include full ticket context (description,
relevant files, test commands, branch info) so a local LLM can implement a
ticket without access to Linear, GitHub, or any external services.

The generated prompt is suitable for:
- Direct OpenAI-compatible API calls to local vLLM endpoints
- Headless ``claude -p`` dispatch with model override
- Any other text-in/text-out LLM interface

See Also:
    - ``node_delegation_orchestrator/`` for the dispatch routing (OMN-7103)
    - ``ticket_work/SKILL.md`` for the orchestrating skill
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ModelDelegationContext(BaseModel):
    """Context for building a delegation prompt.

    All fields needed to create a self-contained prompt that a local LLM
    can execute without external service access.

    Attributes:
        ticket_id: Linear ticket ID (e.g., OMN-7283).
        ticket_title: Short title of the ticket.
        ticket_description: Full ticket description/body.
        repo: Repository name (e.g., omniclaude).
        branch: Git branch to work on.
        relevant_files: Paths to files the LLM should read/modify.
        test_command: Command to run tests after implementation.
        worktree_path: Absolute path to the worktree.
        additional_context: Extra context (e.g., related tickets, patterns to follow).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    ticket_id: str = Field(description="Linear ticket ID")
    ticket_title: str = Field(default="", description="Short title")
    ticket_description: str = Field(description="Full ticket description")
    repo: str = Field(description="Repository name")
    branch: str = Field(description="Git branch to work on")
    relevant_files: list[str] = Field(
        default_factory=list,
        description="File paths the LLM should read/modify",
    )
    test_command: str = Field(
        default="uv run pytest tests/ -v --tb=short",
        description="Command to verify the implementation",
    )
    worktree_path: str = Field(
        default="",
        description="Absolute path to the worktree",
    )
    additional_context: str = Field(
        default="",
        description="Extra context (related tickets, patterns to follow)",
    )


def build_delegation_prompt(context: ModelDelegationContext) -> str:
    """Build a self-contained prompt for local LLM delegation.

    The prompt includes all information needed for the LLM to understand
    the task, locate relevant code, implement changes, and verify them.

    Args:
        context: Structured context for the delegation.

    Returns:
        A complete prompt string suitable for a local LLM.
    """
    sections: list[str] = []

    # Header
    sections.append(
        f"You are implementing ticket {context.ticket_id} in the "
        f"{context.repo} repository."
    )

    # Ticket description
    sections.append(f"## Ticket: {context.ticket_id}")
    if context.ticket_title:
        sections.append(f"**Title**: {context.ticket_title}")
    sections.append("")
    sections.append(context.ticket_description)

    # Branch
    sections.append(f"\n## Working Branch\n\n`{context.branch}`")

    # Worktree path
    if context.worktree_path:
        sections.append(f"\n## Working Directory\n\n`{context.worktree_path}`")

    # Relevant files
    if context.relevant_files:
        file_list = "\n".join(f"- `{f}`" for f in context.relevant_files)
        sections.append(f"\n## Relevant Files\n\n{file_list}")

    # Additional context
    if context.additional_context:
        sections.append(f"\n## Additional Context\n\n{context.additional_context}")

    # Test command
    sections.append(f"\n## Test Command\n\n```bash\n{context.test_command}\n```")

    # Instructions
    sections.append(
        "\n## Instructions\n\n"
        "1. Read the relevant files to understand the current codebase state\n"
        "2. Implement the changes described in the ticket\n"
        "3. Follow existing code patterns and conventions in the repository\n"
        "4. Run the test command to verify your changes pass\n"
        "5. If tests pass, stage and commit with message: "
        f"`feat({context.repo}): {context.ticket_id} "
        "-- <brief description>`\n"
        "6. Push the branch\n"
        "7. Do NOT create a PR -- the orchestrator handles that"
    )

    return "\n".join(sections)


def estimate_delegation_tokens(context: ModelDelegationContext) -> int:
    """Estimate the token count for a delegation prompt.

    Rough estimate: ~4 chars per token for English text. Used by the
    pipeline fill skill to decide whether a task fits within the local
    LLM's context window.

    Args:
        context: The delegation context.

    Returns:
        Estimated token count.
    """
    prompt = build_delegation_prompt(context)
    return len(prompt) // 4


__all__ = [
    "ModelDelegationContext",
    "build_delegation_prompt",
    "estimate_delegation_tokens",
]
