# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for handler_delegation_prompt_builder — self-contained LLM prompts."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from omniclaude.hooks.handlers.handler_delegation_prompt_builder import (
    ModelDelegationContext,
    build_delegation_prompt,
    estimate_delegation_tokens,
)


def _make_context(**overrides: object) -> ModelDelegationContext:
    defaults: dict[str, object] = {
        "ticket_id": "OMN-7300",
        "ticket_title": "Add session checkpoint model",
        "ticket_description": "Create ModelSessionCheckpoint Pydantic model.",
        "repo": "omniclaude",
        "branch": "jonahgabriel/omn-7300-checkpoint-model",
        "relevant_files": [
            "src/omniclaude/hooks/model_session_checkpoint.py",
            "tests/unit/hooks/test_model_session_checkpoint.py",
        ],
        "test_command": "uv run pytest tests/unit -v --tb=short",
        "worktree_path": "/tmp/test-worktree/omniclaude",  # noqa: S108
    }
    defaults.update(overrides)
    return ModelDelegationContext(**defaults)  # type: ignore[arg-type]


@pytest.mark.unit
class TestBuildDelegationPrompt:
    """Tests for prompt generation."""

    def test_includes_ticket_id(self) -> None:
        prompt = build_delegation_prompt(_make_context())
        assert "OMN-7300" in prompt

    def test_includes_repo_name(self) -> None:
        prompt = build_delegation_prompt(_make_context())
        assert "omniclaude" in prompt

    def test_includes_ticket_description(self) -> None:
        prompt = build_delegation_prompt(_make_context())
        assert "ModelSessionCheckpoint Pydantic model" in prompt

    def test_includes_branch(self) -> None:
        prompt = build_delegation_prompt(_make_context())
        assert "jonahgabriel/omn-7300-checkpoint-model" in prompt

    def test_includes_relevant_files(self) -> None:
        prompt = build_delegation_prompt(_make_context())
        assert "model_session_checkpoint.py" in prompt
        assert "test_model_session_checkpoint.py" in prompt

    def test_includes_test_command(self) -> None:
        prompt = build_delegation_prompt(_make_context())
        assert "uv run pytest tests/unit -v --tb=short" in prompt

    def test_includes_worktree_path(self) -> None:
        prompt = build_delegation_prompt(_make_context())
        assert "Working Directory" in prompt

    def test_includes_commit_format(self) -> None:
        prompt = build_delegation_prompt(_make_context())
        assert "feat(omniclaude)" in prompt

    def test_no_pr_creation_instruction(self) -> None:
        prompt = build_delegation_prompt(_make_context())
        assert "Do NOT create a PR" in prompt

    def test_no_additional_context_section_when_empty(self) -> None:
        prompt = build_delegation_prompt(_make_context(additional_context=""))
        assert "Additional Context" not in prompt

    def test_additional_context_included(self) -> None:
        prompt = build_delegation_prompt(
            _make_context(additional_context="Follow the existing handler pattern.")
        )
        assert "Additional Context" in prompt
        assert "Follow the existing handler pattern" in prompt

    def test_no_relevant_files_section_when_empty(self) -> None:
        prompt = build_delegation_prompt(_make_context(relevant_files=[]))
        assert "Relevant Files" not in prompt

    def test_no_worktree_section_when_empty(self) -> None:
        prompt = build_delegation_prompt(_make_context(worktree_path=""))
        assert "Working Directory" not in prompt

    def test_title_included_when_present(self) -> None:
        prompt = build_delegation_prompt(_make_context())
        assert "Add session checkpoint model" in prompt

    def test_title_omitted_when_empty(self) -> None:
        prompt = build_delegation_prompt(_make_context(ticket_title=""))
        assert "**Title**" not in prompt

    def test_empty_description_keeps_ticket_and_execution_context(self) -> None:
        prompt = build_delegation_prompt(_make_context(ticket_description=""))

        assert "## Ticket: OMN-7300" in prompt
        assert "## Working Branch" in prompt
        assert "## Test Command" in prompt
        assert "## Instructions" in prompt

    def test_oversized_description_is_preserved_without_injection_truncation(
        self,
    ) -> None:
        # Pattern injection limits belong to context injection, not this builder.
        # This description exceeds even its maximum 10,000-token budget at the
        # delegation estimator's four-characters-per-token approximation.
        description = "Implement the delegation task.\n" * 2000 + "END OF TASK"
        context = _make_context(ticket_description=description)

        prompt = build_delegation_prompt(context)

        assert description in prompt
        assert prompt.index("END OF TASK") < prompt.index("## Working Branch")
        assert estimate_delegation_tokens(context) == len(prompt) // 4
        assert estimate_delegation_tokens(context) > 10000


@pytest.mark.unit
class TestEstimateDelegationTokens:
    """Tests for token estimation."""

    def test_returns_positive_integer(self) -> None:
        tokens = estimate_delegation_tokens(_make_context())
        assert isinstance(tokens, int)
        assert tokens > 0

    def test_longer_description_more_tokens(self) -> None:
        short = estimate_delegation_tokens(_make_context(ticket_description="Short."))
        long = estimate_delegation_tokens(_make_context(ticket_description="A" * 10000))
        assert long > short


@pytest.mark.unit
class TestModelDelegationContext:
    """Tests for the context model."""

    def test_frozen(self) -> None:
        ctx = _make_context()
        with pytest.raises(Exception):
            ctx.ticket_id = "changed"  # type: ignore[misc]

    def test_default_test_command(self) -> None:
        ctx = ModelDelegationContext(
            ticket_id="OMN-1",
            ticket_description="desc",
            repo="repo",
            branch="branch",
        )
        assert "pytest" in ctx.test_command

    @pytest.mark.parametrize("field", ["ticket_id", "ticket_description"])
    def test_ticket_fields_are_required(self, field: str) -> None:
        values = _make_context().model_dump()
        del values[field]

        with pytest.raises(ValidationError) as exc_info:
            ModelDelegationContext.model_validate(values)

        assert [(error["loc"], error["type"]) for error in exc_info.value.errors()] == [
            ((field,), "missing")
        ]

    @pytest.mark.parametrize("field", ["lane", "task_class"])
    def test_unsupported_dispatch_fields_are_rejected(self, field: str) -> None:
        values = _make_context().model_dump()
        values[field] = "unregistered"

        with pytest.raises(ValidationError) as exc_info:
            ModelDelegationContext.model_validate(values)

        assert [(error["loc"], error["type"]) for error in exc_info.value.errors()] == [
            ((field,), "extra_forbidden")
        ]
