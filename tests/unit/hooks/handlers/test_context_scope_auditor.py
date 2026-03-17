# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for ContextScopeAuditor (OMN-5237).

Tests cover:
- Tool scope validation (allowed/disallowed tools)
- Context budget tracking with tiktoken (cl100k_base)
- PERMISSIVE/WARN/STRICT/PARANOID enforcement modes
- Blocking behavior in STRICT and PARANOID modes
- Budget state persistence (load/save/clear)
- EnforcementMode helpers
- run_hook entry point with JSON input
- No-op when no active task (no correlation registry available)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from omniclaude.hooks.handlers.context_scope_auditor import (
    AuditResult,
    ContextScopeAuditor,
    EnforcementMode,
    clear_cumulative_tokens,
    load_cumulative_tokens,
    run_hook,
    save_cumulative_tokens,
)
from omniclaude.lib.utils.token_counter import TOKEN_SAFETY_MARGIN, count_tokens

pytestmark = pytest.mark.unit


# =============================================================================
# Helpers
# =============================================================================


def _make_registry(
    task_id: str | None = "task-001",
    scopes: dict[str, Any] | None = None,
    correlation_id: str | None = "00000000-0000-0000-0000-000000000001",
) -> MagicMock:
    """Build a mock CorrelationRegistry."""
    reg = MagicMock()
    reg.current_task_id = task_id
    reg.get_correlation_id.return_value = correlation_id

    if task_id is None:
        reg.task_dispatches = {}
    else:
        reg.task_dispatches = {
            task_id: {
                "task_id": task_id,
                "contract_id": "test-contract",
                "scopes": scopes or {},
            }
        }
    return reg


def _auditor(
    mode: str = EnforcementMode.PERMISSIVE,
    state_dir: Path | None = None,
    registry: MagicMock | None = None,
) -> ContextScopeAuditor:
    """Create a ContextScopeAuditor with an injected registry mock."""
    auditor = ContextScopeAuditor(enforcement_mode=mode, state_dir=state_dir)
    if registry is not None:
        auditor._load_correlation_registry = MagicMock(return_value=registry)  # type: ignore[method-assign]
    else:
        # No active task
        auditor._load_correlation_registry = MagicMock(return_value=None)  # type: ignore[method-assign]
    return auditor


# =============================================================================
# EnforcementMode tests
# =============================================================================


class TestEnforcementMode:
    """Tests for EnforcementMode helpers."""

    def test_valid_modes_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for mode in ("PERMISSIVE", "WARN", "STRICT", "PARANOID"):
            monkeypatch.setenv("OMNICLAUDE_AUDIT_ENFORCEMENT_MODE", mode)
            assert EnforcementMode.from_env() == mode

    def test_case_insensitive_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OMNICLAUDE_AUDIT_ENFORCEMENT_MODE", "strict")
        assert EnforcementMode.from_env() == EnforcementMode.STRICT

    def test_unknown_mode_defaults_to_permissive(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OMNICLAUDE_AUDIT_ENFORCEMENT_MODE", "INVALID_MODE")
        assert EnforcementMode.from_env() == EnforcementMode.PERMISSIVE

    def test_missing_env_defaults_to_permissive(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("OMNICLAUDE_AUDIT_ENFORCEMENT_MODE", raising=False)
        assert EnforcementMode.from_env() == EnforcementMode.PERMISSIVE

    def test_blocking_modes(self) -> None:
        assert EnforcementMode.is_blocking(EnforcementMode.STRICT) is True
        assert EnforcementMode.is_blocking(EnforcementMode.PARANOID) is True
        assert EnforcementMode.is_blocking(EnforcementMode.WARN) is False
        assert EnforcementMode.is_blocking(EnforcementMode.PERMISSIVE) is False


# =============================================================================
# Budget state persistence
# =============================================================================


class TestBudgetStatePersistence:
    """Tests for cumulative token state file helpers."""

    def test_load_returns_zero_when_no_file(self, tmp_path: Path) -> None:
        assert load_cumulative_tokens("task-x", tmp_path) == 0

    def test_save_and_load_roundtrip(self, tmp_path: Path) -> None:
        save_cumulative_tokens("task-a", 1234, tmp_path)
        assert load_cumulative_tokens("task-a", tmp_path) == 1234

    def test_save_overwrites_previous_value(self, tmp_path: Path) -> None:
        save_cumulative_tokens("task-b", 100, tmp_path)
        save_cumulative_tokens("task-b", 200, tmp_path)
        assert load_cumulative_tokens("task-b", tmp_path) == 200

    def test_clear_removes_state_file(self, tmp_path: Path) -> None:
        save_cumulative_tokens("task-c", 500, tmp_path)
        clear_cumulative_tokens("task-c", tmp_path)
        assert load_cumulative_tokens("task-c", tmp_path) == 0

    def test_clear_is_idempotent_when_no_file(self, tmp_path: Path) -> None:
        # Should not raise
        clear_cumulative_tokens("task-nonexistent", tmp_path)

    def test_separate_task_ids_are_independent(self, tmp_path: Path) -> None:
        save_cumulative_tokens("task-1", 100, tmp_path)
        save_cumulative_tokens("task-2", 200, tmp_path)
        assert load_cumulative_tokens("task-1", tmp_path) == 100
        assert load_cumulative_tokens("task-2", tmp_path) == 200


# =============================================================================
# ContextScopeAuditor — no active task
# =============================================================================


class TestNoActiveTask:
    """When no active task exists, the auditor allows all calls."""

    def test_allow_any_tool_when_no_task(self) -> None:
        auditor = _auditor(mode=EnforcementMode.STRICT)
        result = auditor.audit(tool_name="Bash", tool_input={"command": "ls"})
        assert result.should_block is False
        assert result.scope_violated is False
        assert result.budget_exceeded is False
        assert result.task_id is None


# =============================================================================
# ContextScopeAuditor — tool scope validation
# =============================================================================


class TestToolScopeValidation:
    """Tests for tool_scope enforcement."""

    def test_tool_in_scope_is_allowed(self, tmp_path: Path) -> None:
        reg = _make_registry(scopes={"tool_scope": ["Read", "Glob"]})
        auditor = _auditor(mode=EnforcementMode.STRICT, state_dir=tmp_path, registry=reg)
        result = auditor.audit("Read", {})
        assert result.scope_violated is False
        assert result.should_block is False

    def test_tool_not_in_scope_permissive_allows(self, tmp_path: Path) -> None:
        reg = _make_registry(scopes={"tool_scope": ["Read", "Glob"]})
        auditor = _auditor(mode=EnforcementMode.PERMISSIVE, state_dir=tmp_path, registry=reg)
        result = auditor.audit("Bash", {})
        assert result.scope_violated is True
        assert result.should_block is False  # permissive = log only

    def test_tool_not_in_scope_warn_does_not_block(self, tmp_path: Path) -> None:
        reg = _make_registry(scopes={"tool_scope": ["Read"]})
        auditor = _auditor(mode=EnforcementMode.WARN, state_dir=tmp_path, registry=reg)
        result = auditor.audit("Write", {})
        assert result.scope_violated is True
        assert result.should_block is False

    def test_tool_not_in_scope_strict_blocks(self, tmp_path: Path) -> None:
        reg = _make_registry(scopes={"tool_scope": ["Read"]})
        auditor = _auditor(mode=EnforcementMode.STRICT, state_dir=tmp_path, registry=reg)
        result = auditor.audit("Bash", {})
        assert result.scope_violated is True
        assert result.should_block is True

    def test_tool_not_in_scope_paranoid_blocks(self, tmp_path: Path) -> None:
        reg = _make_registry(scopes={"tool_scope": ["Read"]})
        auditor = _auditor(mode=EnforcementMode.PARANOID, state_dir=tmp_path, registry=reg)
        result = auditor.audit("Write", {})
        assert result.scope_violated is True
        assert result.should_block is True

    def test_no_tool_scope_declared_allows_any_tool(self, tmp_path: Path) -> None:
        """When scopes dict has no tool_scope key, any tool is allowed."""
        reg = _make_registry(scopes={})
        auditor = _auditor(mode=EnforcementMode.STRICT, state_dir=tmp_path, registry=reg)
        result = auditor.audit("Bash", {"command": "rm -rf /"})
        assert result.scope_violated is False
        assert result.should_block is False

    def test_empty_tool_scope_blocks_all_tools(self, tmp_path: Path) -> None:
        """An empty tool_scope list blocks every tool call in STRICT mode."""
        reg = _make_registry(scopes={"tool_scope": []})
        auditor = _auditor(mode=EnforcementMode.STRICT, state_dir=tmp_path, registry=reg)
        result = auditor.audit("Read", {})
        assert result.scope_violated is True
        assert result.should_block is True


# =============================================================================
# ContextScopeAuditor — context budget tracking
# =============================================================================


class TestContextBudgetTracking:
    """Tests for context_budget_tokens enforcement."""

    def test_within_budget_is_not_exceeded(self, tmp_path: Path) -> None:
        # Set a large budget so a small call never exceeds it
        reg = _make_registry(scopes={"context_budget_tokens": 100_000})
        auditor = _auditor(mode=EnforcementMode.STRICT, state_dir=tmp_path, registry=reg)
        result = auditor.audit("Read", {"file_path": "/tmp/a.txt"})
        assert result.budget_exceeded is False
        assert result.should_block is False

    def test_exceeding_budget_permissive_allows(self, tmp_path: Path) -> None:
        task_id = "task-budget-1"
        reg = _make_registry(task_id=task_id, scopes={"context_budget_tokens": 1})
        auditor = _auditor(mode=EnforcementMode.PERMISSIVE, state_dir=tmp_path, registry=reg)
        result = auditor.audit("Bash", {"command": "echo hello world"})
        # Any real text will exceed a 1-token budget
        assert result.budget_exceeded is True
        assert result.should_block is False  # permissive = never block

    def test_exceeding_budget_strict_blocks(self, tmp_path: Path) -> None:
        task_id = "task-budget-2"
        reg = _make_registry(task_id=task_id, scopes={"context_budget_tokens": 1})
        auditor = _auditor(mode=EnforcementMode.STRICT, state_dir=tmp_path, registry=reg)
        result = auditor.audit("Bash", {"command": "echo hello world"})
        assert result.budget_exceeded is True
        assert result.should_block is True

    def test_cumulative_tracking_across_calls(self, tmp_path: Path) -> None:
        """Budget accumulates across multiple audit calls for the same task."""
        task_id = "task-cumulative"
        # Count tokens for a known-small input
        small_input = {"x": "a"}
        tokens_per_call = count_tokens(json.dumps(small_input, default=str))
        # Budget slightly above one call but below two
        budget = int(tokens_per_call * 1.5 / TOKEN_SAFETY_MARGIN)

        reg = _make_registry(task_id=task_id, scopes={"context_budget_tokens": budget})
        auditor = _auditor(mode=EnforcementMode.STRICT, state_dir=tmp_path, registry=reg)

        # First call: within budget
        result1 = auditor.audit("Read", small_input)
        assert result1.budget_exceeded is False

        # Second call: should push us over the effective budget
        result2 = auditor.audit("Read", small_input)
        assert result2.budget_exceeded is True

    def test_no_budget_declared_skips_budget_check(self, tmp_path: Path) -> None:
        """When context_budget_tokens is absent, no budget tracking occurs."""
        reg = _make_registry(scopes={"tool_scope": ["Read"]})
        auditor = _auditor(mode=EnforcementMode.STRICT, state_dir=tmp_path, registry=reg)
        result = auditor.audit("Read", {"file_path": "/tmp/x"})
        assert result.budget_exceeded is False

    def test_safety_margin_applied(self, tmp_path: Path) -> None:
        """Effective budget is budget * TOKEN_SAFETY_MARGIN, not the raw budget."""
        task_id = "task-margin"
        # Use count_tokens to get exact token count for a specific input
        input_text = {"command": "ls -la /tmp"}
        raw_tokens = count_tokens(json.dumps(input_text, default=str))

        # Set budget such that raw_tokens > effective_budget but raw_tokens < budget
        # i.e. budget = raw_tokens / TOKEN_SAFETY_MARGIN (just at the margin)
        budget = int(raw_tokens / TOKEN_SAFETY_MARGIN)

        reg = _make_registry(task_id=task_id, scopes={"context_budget_tokens": budget})
        auditor = _auditor(mode=EnforcementMode.STRICT, state_dir=tmp_path, registry=reg)
        result = auditor.audit("Bash", input_text)
        # raw_tokens > effective_budget = budget * TOKEN_SAFETY_MARGIN
        # so this should exceed
        assert result.budget_exceeded is True


# =============================================================================
# ContextScopeAuditor — combined scope + budget
# =============================================================================


class TestCombinedAudit:
    """Tests for simultaneous scope and budget violations."""

    def test_both_violations_produce_block_in_strict(self, tmp_path: Path) -> None:
        task_id = "task-combined"
        reg = _make_registry(
            task_id=task_id,
            scopes={"tool_scope": ["Read"], "context_budget_tokens": 1},
        )
        auditor = _auditor(mode=EnforcementMode.STRICT, state_dir=tmp_path, registry=reg)
        result = auditor.audit("Bash", {"command": "echo hello world"})
        assert result.scope_violated is True
        assert result.budget_exceeded is True
        assert result.should_block is True

    def test_scope_ok_budget_exceeded_blocks_in_strict(self, tmp_path: Path) -> None:
        task_id = "task-scope-ok"
        reg = _make_registry(
            task_id=task_id,
            scopes={"tool_scope": ["Bash"], "context_budget_tokens": 1},
        )
        auditor = _auditor(mode=EnforcementMode.STRICT, state_dir=tmp_path, registry=reg)
        result = auditor.audit("Bash", {"command": "echo hello world"})
        assert result.scope_violated is False
        assert result.budget_exceeded is True
        assert result.should_block is True


# =============================================================================
# AuditResult repr
# =============================================================================


class TestAuditResult:
    """Tests for AuditResult."""

    def test_repr_includes_key_fields(self) -> None:
        result = AuditResult(
            task_id="t-1",
            tool_name="Bash",
            scope_violated=True,
            budget_exceeded=False,
            should_block=True,
            enforcement_mode=EnforcementMode.STRICT,
        )
        r = repr(result)
        assert "t-1" in r
        assert "Bash" in r
        assert "scope_violated=True" in r
        assert "should_block=True" in r


# =============================================================================
# run_hook entry point
# =============================================================================


class TestRunHook:
    """Tests for the run_hook JSON entry point."""

    def test_allow_returns_zero_and_passthrough(self, tmp_path: Path) -> None:
        hook_data = {"tool_name": "Read", "tool_input": {"file_path": "/tmp/x"}}
        raw = json.dumps(hook_data)

        # Patch auditor to always allow
        with patch(
            "omniclaude.hooks.handlers.context_scope_auditor.ContextScopeAuditor.audit"
        ) as mock_audit:
            mock_audit.return_value = AuditResult(
                task_id=None,
                tool_name="Read",
                scope_violated=False,
                budget_exceeded=False,
                should_block=False,
                enforcement_mode=EnforcementMode.PERMISSIVE,
            )
            exit_code = run_hook(stdin_data=raw)

        assert exit_code == 0

    def test_block_returns_two(self, tmp_path: Path) -> None:
        hook_data = {"tool_name": "Bash", "tool_input": {"command": "rm -rf /"}}
        raw = json.dumps(hook_data)

        with patch(
            "omniclaude.hooks.handlers.context_scope_auditor.ContextScopeAuditor.audit"
        ) as mock_audit:
            mock_audit.return_value = AuditResult(
                task_id="task-1",
                tool_name="Bash",
                scope_violated=True,
                budget_exceeded=False,
                should_block=True,
                enforcement_mode=EnforcementMode.STRICT,
            )
            exit_code = run_hook(stdin_data=raw)

        assert exit_code == 2

    def test_invalid_json_allows_with_exit_zero(self) -> None:
        exit_code = run_hook(stdin_data="not valid json {{{")
        assert exit_code == 0

    def test_empty_stdin_allows_with_exit_zero(self) -> None:
        exit_code = run_hook(stdin_data="{}")
        assert exit_code == 0


# =============================================================================
# Shared token_counter utility
# =============================================================================


class TestTokenCounter:
    """Tests for the shared count_tokens utility used by the auditor."""

    def test_count_tokens_nonempty(self) -> None:
        assert count_tokens("Hello, world!") > 0

    def test_count_tokens_empty(self) -> None:
        assert count_tokens("") == 0

    def test_count_tokens_deterministic(self) -> None:
        text = "The quick brown fox jumps over the lazy dog"
        assert count_tokens(text) == count_tokens(text)

    def test_safety_margin_is_less_than_one(self) -> None:
        assert 0.0 < TOKEN_SAFETY_MARGIN < 1.0
