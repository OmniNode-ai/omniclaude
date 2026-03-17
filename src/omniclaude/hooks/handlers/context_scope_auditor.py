# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Context scope audit PreToolUse hook (OMN-5237).

Runs AFTER the poly enforcer for every tool call within an active task.
Audits two independent dimensions:

1. **Tool scope** — if the active task declared a ``tool_scope`` list in its
   contract, the requested tool must appear in that list.  Violations emit
   ``AuditScopeViolationEvent`` (topic: ``audit-scope-violation.v1``) and,
   in STRICT/PARANOID modes, block the tool call (exit 2).

2. **Context budget** — tracks cumulative token usage across injected memory
   blocks, retrieved context, and tool-result payloads for the active task.
   If the running total exceeds ``context_budget_tokens`` the hook emits
   ``AuditContextBudgetEvent`` (topic: ``audit-context-budget-exceeded.v1``)
   and, in STRICT/PARANOID modes, blocks the tool call.

Token Accounting
----------------
The budget covers:
    - Injected memory blocks (retrieved via omnimemory / RAG)
    - Retrieved context payloads (from tool results passed into the prompt)
    - Tool result payloads (content returned by executed tools)

It does NOT count:
    - The base system prompt / CLAUDE.md instructions
    - Model reasoning tokens or chain-of-thought
    - The tool call itself (only its result payload)

Enforcement Modes
-----------------
Controlled by ``OMNICLAUDE_AUDIT_ENFORCEMENT_MODE`` env var:
    ``PERMISSIVE`` — log only; never block                     (default)
    ``WARN``       — log + emit event; never block
    ``STRICT``     — log + emit event; block on violation (exit 2)
    ``PARANOID``   — like STRICT plus additional rollback signal emitted

Hook Placement
--------------
Registered in hooks.json after poly enforcer so the poly enforcer can set
task context (push_task) before this hook reads it.

No Circular Dependency
----------------------
This module imports only from:
    - stdlib
    - omniclaude.lib.utils.token_counter (leaf utility)
    - omniclaude.hooks.schemas_audit (pure Pydantic models)
    - omniclaude.hooks.topics (TopicBase StrEnum)
    - plugins.onex.hooks.lib.correlation_manager (loaded at call time)
"""

from __future__ import annotations

import json
import logging
import os
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from omniclaude.hooks.schemas_audit import (
    AuditContextBudgetEvent,
    AuditEnforcementAction,
    AuditScopeViolationEvent,
    AuditScopeViolationType,
)
from omniclaude.hooks.topics import TopicBase
from omniclaude.lib.utils.token_counter import TOKEN_SAFETY_MARGIN, count_tokens

logger = logging.getLogger(__name__)

# =============================================================================
# Enforcement mode
# =============================================================================


class EnforcementMode:
    """Supported enforcement modes for the context scope auditor."""

    PERMISSIVE = "PERMISSIVE"
    WARN = "WARN"
    STRICT = "STRICT"
    PARANOID = "PARANOID"

    _BLOCKING = {STRICT, PARANOID}

    @classmethod
    def from_env(cls) -> str:
        """Read mode from OMNICLAUDE_AUDIT_ENFORCEMENT_MODE env var.

        Returns:
            Normalized mode string; defaults to ``PERMISSIVE``.
        """
        raw = os.environ.get("OMNICLAUDE_AUDIT_ENFORCEMENT_MODE", "PERMISSIVE")
        normalized = raw.strip().upper()
        valid = {cls.PERMISSIVE, cls.WARN, cls.STRICT, cls.PARANOID}
        if normalized not in valid:
            logger.warning(
                "Unknown OMNICLAUDE_AUDIT_ENFORCEMENT_MODE %r; defaulting to PERMISSIVE",
                raw,
            )
            return cls.PERMISSIVE
        return normalized

    @classmethod
    def is_blocking(cls, mode: str) -> bool:
        """Return True if this mode should block tool calls on violation."""
        return mode in cls._BLOCKING

    @classmethod
    def to_enforcement_action(cls, mode: str, violated: bool) -> AuditEnforcementAction:
        """Map an enforcement mode + violation flag to an AuditEnforcementAction.

        Args:
            mode: Enforcement mode string.
            violated: Whether a violation was detected.

        Returns:
            The corresponding AuditEnforcementAction.
        """
        if not violated:
            return AuditEnforcementAction.LOG
        mapping = {
            cls.PERMISSIVE: AuditEnforcementAction.LOG,
            cls.WARN: AuditEnforcementAction.WARN,
            cls.STRICT: AuditEnforcementAction.BLOCK,
            cls.PARANOID: AuditEnforcementAction.ROLLBACK,
        }
        return mapping.get(mode, AuditEnforcementAction.LOG)


# =============================================================================
# Budget tracking
# =============================================================================

# State directory for persisting per-task cumulative token counts.
# Stored alongside correlation state so TTL cleanup applies.
_DEFAULT_STATE_DIR = Path.home() / ".claude" / "hooks" / ".state"
_BUDGET_STATE_FILE_PATTERN = "context_budget_{task_id}.json"


def _budget_state_path(task_id: str, state_dir: Path | None = None) -> Path:
    """Return path to the per-task budget state file."""
    d = state_dir if state_dir is not None else _DEFAULT_STATE_DIR
    return d / _BUDGET_STATE_FILE_PATTERN.format(task_id=task_id)


def load_cumulative_tokens(task_id: str, state_dir: Path | None = None) -> int:
    """Load the cumulative token count for a task from disk.

    Returns 0 if no state file exists or the file is corrupt.

    Args:
        task_id: Task identifier.
        state_dir: Override for state directory (for testing).

    Returns:
        Cumulative token count.
    """
    path = _budget_state_path(task_id, state_dir)
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return int(data.get("cumulative_tokens", 0))
    except Exception:  # noqa: BLE001
        pass
    return 0


def save_cumulative_tokens(
    task_id: str, cumulative_tokens: int, state_dir: Path | None = None
) -> None:
    """Persist the cumulative token count for a task to disk.

    Creates the parent directory if it does not exist. Never raises.

    Args:
        task_id: Task identifier.
        cumulative_tokens: Updated cumulative token count.
        state_dir: Override for state directory (for testing).
    """
    path = _budget_state_path(task_id, state_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "task_id": task_id,
                    "cumulative_tokens": cumulative_tokens,
                    "updated_at": datetime.now(UTC).isoformat(),
                }
            ),
            encoding="utf-8",
        )
    except Exception:  # noqa: BLE001
        pass


def clear_cumulative_tokens(task_id: str, state_dir: Path | None = None) -> None:
    """Remove the cumulative token state file for a task.

    Called when a task completes (pop_task) to avoid stale state.

    Args:
        task_id: Task identifier.
        state_dir: Override for state directory (for testing).
    """
    path = _budget_state_path(task_id, state_dir)
    try:
        if path.exists():
            path.unlink()
    except Exception:  # noqa: BLE001
        pass


# =============================================================================
# Event emission
# =============================================================================


def _emit_event(event_type: str, payload: dict[str, Any]) -> None:
    """Fire-and-forget event emission via emit_client_wrapper.

    Never raises; logs failures at DEBUG level.

    Args:
        event_type: Event type string (Kafka topic key).
        payload: Event payload dict.
    """
    try:
        from emit_client_wrapper import emit_event  # noqa: PLC0415
    except ImportError:
        logger.debug("emit_client_wrapper not available; event dropped: %s", event_type)
        return
    try:
        emit_event(event_type, payload)
    except Exception:  # noqa: BLE001
        logger.debug("Event emission failed for %s", event_type, exc_info=True)


def _emit_scope_violation(
    task_id: str,
    declared_scope: list[str],
    actual_tool: str,
    action: AuditEnforcementAction,
    correlation_id: str | None,
) -> None:
    """Emit an AuditScopeViolationEvent for a tool scope violation.

    Args:
        task_id: Active task identifier.
        declared_scope: Tools declared in the task contract.
        actual_tool: Tool name that was invoked.
        action: Enforcement action being taken.
        correlation_id: Correlation ID for tracing.
    """
    now = datetime.now(UTC)
    try:
        evt = AuditScopeViolationEvent(
            task_id=uuid.UUID(task_id) if _is_valid_uuid(task_id) else uuid.uuid4(),
            violation_type=AuditScopeViolationType.TOOL,
            declared_scope=declared_scope,
            actual_access=actual_tool,
            enforcement_action=action,
            correlation_id=(
                uuid.UUID(correlation_id)
                if correlation_id and _is_valid_uuid(correlation_id)
                else uuid.uuid4()
            ),
            emitted_at=now,
        )
        _emit_event(
            TopicBase.AUDIT_SCOPE_VIOLATION,
            evt.model_dump(mode="json"),
        )
    except Exception:  # noqa: BLE001
        logger.debug("Failed to emit scope violation event", exc_info=True)


def _emit_budget_event(
    task_id: str,
    budget_tokens: int,
    actual_tokens: int,
    exceeded: bool,
    correlation_id: str | None,
) -> None:
    """Emit an AuditContextBudgetEvent for context budget tracking.

    Args:
        task_id: Active task identifier.
        budget_tokens: Declared budget from task contract.
        actual_tokens: Cumulative tokens consumed so far.
        exceeded: Whether the budget was exceeded.
        correlation_id: Correlation ID for tracing.
    """
    now = datetime.now(UTC)
    try:
        evt = AuditContextBudgetEvent(
            task_id=uuid.UUID(task_id) if _is_valid_uuid(task_id) else uuid.uuid4(),
            budget_tokens=max(1, budget_tokens),
            actual_tokens=max(0, actual_tokens),
            exceeded=exceeded,
            correlation_id=(
                uuid.UUID(correlation_id)
                if correlation_id and _is_valid_uuid(correlation_id)
                else uuid.uuid4()
            ),
            emitted_at=now,
        )
        _emit_event(
            TopicBase.AUDIT_CONTEXT_BUDGET_EXCEEDED,
            evt.model_dump(mode="json"),
        )
    except Exception:  # noqa: BLE001
        logger.debug("Failed to emit context budget event", exc_info=True)


def _is_valid_uuid(value: str) -> bool:
    """Return True if value is a valid UUID string."""
    try:
        uuid.UUID(value)
        return True
    except (ValueError, AttributeError):
        return False


# =============================================================================
# Context scope auditor
# =============================================================================


class ContextScopeAuditor:
    """PreToolUse hook that audits tool scope and context budget.

    Reads task scope constraints from the correlation manager and applies
    them to each tool call. Emits audit events for violations and, in
    STRICT/PARANOID mode, blocks the tool call.

    Usage::

        auditor = ContextScopeAuditor()
        result = auditor.audit(tool_name="Bash", tool_input={}, tool_result_text=None)
        if result.should_block:
            sys.exit(2)

    Attributes:
        enforcement_mode: Active enforcement mode (PERMISSIVE/WARN/STRICT/PARANOID).
        state_dir: Directory for budget state files.
    """

    def __init__(
        self,
        enforcement_mode: str | None = None,
        state_dir: Path | None = None,
    ) -> None:
        """Initialize the context scope auditor.

        Args:
            enforcement_mode: Override enforcement mode (default: from env).
            state_dir: Override state directory (default: ~/.claude/hooks/.state).
        """
        self.enforcement_mode = (
            enforcement_mode if enforcement_mode is not None else EnforcementMode.from_env()
        )
        self.state_dir = state_dir

    def _load_correlation_registry(self) -> Any | None:
        """Load CorrelationRegistry from the plugin lib.

        Returns None if the registry cannot be loaded (non-fatal).
        """
        try:
            from plugins.onex.hooks.lib.correlation_manager import (  # noqa: PLC0415
                get_registry,
            )

            return get_registry()
        except Exception:  # noqa: BLE001
            logger.debug("CorrelationRegistry not available", exc_info=True)
            return None

    def _get_task_scopes(self) -> tuple[str | None, dict[str, Any]]:
        """Read current task ID and scope constraints from the registry.

        Returns:
            Tuple of (task_id, scopes_dict).
            ``task_id`` is None if no active task.
            ``scopes_dict`` is the raw scopes dict from dispatch metadata;
            may be empty.
        """
        registry = self._load_correlation_registry()
        if registry is None:
            return None, {}

        task_id: str | None = registry.current_task_id
        if task_id is None:
            return None, {}

        dispatches: dict[str, Any] = registry.task_dispatches
        meta = dispatches.get(task_id, {})
        scopes: dict[str, Any] = meta.get("scopes", {})
        return task_id, scopes

    def _get_correlation_id(self) -> str | None:
        """Return the current correlation ID from the registry."""
        registry = self._load_correlation_registry()
        if registry is None:
            return None
        return registry.get_correlation_id()

    def audit(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        tool_result_text: str | None = None,
    ) -> AuditResult:
        """Audit a tool call for scope and budget compliance.

        Performs two independent checks:
        1. Tool scope — is this tool in the declared ``tool_scope`` list?
        2. Context budget — does this call (plus accumulated tokens) exceed
           ``context_budget_tokens``?

        Either check can produce a block decision. Both checks run regardless
        of whether the first one blocks (so both events are always emitted).

        Args:
            tool_name: Name of the tool being invoked (e.g. ``"Bash"``).
            tool_input: Tool input parameters dict (for token counting).
            tool_result_text: Optional tool result text to count against the
                budget (provided by PostToolUse callers; None for PreToolUse).

        Returns:
            AuditResult describing what happened and whether to block.
        """
        task_id, scopes = self._get_task_scopes()
        correlation_id = self._get_correlation_id()

        scope_violated = False
        budget_exceeded = False
        block = False

        # ------------------------------------------------------------------
        # Check 1: tool scope
        # ------------------------------------------------------------------
        tool_scope: list[str] | None = scopes.get("tool_scope")
        if tool_scope is not None and tool_name not in tool_scope:
            scope_violated = True
            action = EnforcementMode.to_enforcement_action(
                self.enforcement_mode, violated=True
            )
            logger.warning(
                "Tool scope violation: tool=%r not in declared scope=%r (task=%s, mode=%s)",
                tool_name,
                tool_scope,
                task_id,
                self.enforcement_mode,
            )
            if self.enforcement_mode != EnforcementMode.PERMISSIVE:
                _emit_scope_violation(
                    task_id=task_id or "",
                    declared_scope=tool_scope,
                    actual_tool=tool_name,
                    action=action,
                    correlation_id=correlation_id,
                )
            if EnforcementMode.is_blocking(self.enforcement_mode):
                block = True

        # ------------------------------------------------------------------
        # Check 2: context budget
        # ------------------------------------------------------------------
        context_budget_tokens: int | None = scopes.get("context_budget_tokens")
        if task_id is not None and context_budget_tokens is not None:
            # Measure this call's contribution to the budget:
            # tool_input JSON + optional result text
            call_text = json.dumps(tool_input, default=str)
            if tool_result_text:
                call_text += tool_result_text
            call_tokens = count_tokens(call_text)

            cumulative = load_cumulative_tokens(task_id, self.state_dir)
            new_cumulative = cumulative + call_tokens

            # Apply safety margin when evaluating the hard budget
            effective_budget = int(context_budget_tokens * TOKEN_SAFETY_MARGIN)
            exceeded = new_cumulative > effective_budget

            # Persist updated running total
            save_cumulative_tokens(task_id, new_cumulative, self.state_dir)

            if exceeded:
                budget_exceeded = True
                logger.warning(
                    "Context budget exceeded: task=%s tokens=%d budget=%d (effective=%d mode=%s)",
                    task_id,
                    new_cumulative,
                    context_budget_tokens,
                    effective_budget,
                    self.enforcement_mode,
                )
                if self.enforcement_mode != EnforcementMode.PERMISSIVE:
                    _emit_budget_event(
                        task_id=task_id,
                        budget_tokens=context_budget_tokens,
                        actual_tokens=new_cumulative,
                        exceeded=True,
                        correlation_id=correlation_id,
                    )
                if EnforcementMode.is_blocking(self.enforcement_mode):
                    block = True
            else:
                logger.debug(
                    "Context budget OK: task=%s tokens=%d/%d (effective budget=%d)",
                    task_id,
                    new_cumulative,
                    context_budget_tokens,
                    effective_budget,
                )

        return AuditResult(
            task_id=task_id,
            tool_name=tool_name,
            scope_violated=scope_violated,
            budget_exceeded=budget_exceeded,
            should_block=block,
            enforcement_mode=self.enforcement_mode,
        )


class AuditResult:
    """Result of a context scope audit check.

    Attributes:
        task_id: Active task ID (None if no active task).
        tool_name: Tool name that was checked.
        scope_violated: Whether a tool scope violation was detected.
        budget_exceeded: Whether the context budget was exceeded.
        should_block: Whether the tool call should be blocked (exit 2).
        enforcement_mode: Enforcement mode that produced this result.
    """

    def __init__(
        self,
        task_id: str | None,
        tool_name: str,
        scope_violated: bool,
        budget_exceeded: bool,
        should_block: bool,
        enforcement_mode: str,
    ) -> None:
        self.task_id = task_id
        self.tool_name = tool_name
        self.scope_violated = scope_violated
        self.budget_exceeded = budget_exceeded
        self.should_block = should_block
        self.enforcement_mode = enforcement_mode

    def __repr__(self) -> str:
        return (
            f"AuditResult(task_id={self.task_id!r}, tool={self.tool_name!r}, "
            f"scope_violated={self.scope_violated}, budget_exceeded={self.budget_exceeded}, "
            f"should_block={self.should_block}, mode={self.enforcement_mode!r})"
        )


# =============================================================================
# Hook entry point
# =============================================================================


def run_hook(stdin_data: str | None = None) -> int:
    """Hook entry point for PreToolUse invocation.

    Reads tool invocation JSON from stdin (or ``stdin_data`` for testing),
    audits the call, and returns an exit code.

    Exit codes:
        0 — allow the tool call
        2 — block the tool call (STRICT/PARANOID mode violations only)

    Args:
        stdin_data: Optional stdin override for testing. If None, reads
            from sys.stdin.

    Returns:
        Exit code (0 or 2).
    """
    raw = stdin_data if stdin_data is not None else sys.stdin.read()
    try:
        hook_data = json.loads(raw)
    except json.JSONDecodeError:
        logger.debug("context_scope_auditor: invalid JSON from stdin, allowing")
        print(raw, end="")  # noqa: T201 — hook protocol: pass through to stdout
        return 0

    tool_name: str = hook_data.get("tool_name", "")
    tool_input: dict[str, Any] = hook_data.get("tool_input", {})

    auditor = ContextScopeAuditor()
    result = auditor.audit(tool_name=tool_name, tool_input=tool_input)

    if result.should_block:
        reasons: list[str] = []
        if result.scope_violated:
            reasons.append(f"tool {tool_name!r} is not in the declared tool_scope")
        if result.budget_exceeded:
            reasons.append("context budget exceeded for active task")
        reason_str = "; ".join(reasons) or "audit violation detected"
        block_json = json.dumps(
            {
                "decision": "block",
                "reason": (
                    f"context_scope_auditor blocked {tool_name!r}: {reason_str}. "
                    f"Enforcement mode: {result.enforcement_mode}."
                ),
            }
        )
        print(block_json)  # noqa: T201 — hook protocol: emit block decision to stdout
        return 2

    # Allow: pass through the original hook_data
    print(raw, end="")  # noqa: T201 — hook protocol: pass through to stdout
    return 0


if __name__ == "__main__":
    sys.exit(run_hook())


# =============================================================================
# Exports
# =============================================================================

__all__ = [
    "AuditResult",
    "ContextScopeAuditor",
    "EnforcementMode",
    "clear_cumulative_tokens",
    "count_tokens",
    "load_cumulative_tokens",
    "run_hook",
    "save_cumulative_tokens",
]
