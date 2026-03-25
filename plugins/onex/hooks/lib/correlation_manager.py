#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""
Correlation ID Manager - Persist correlation IDs across hook invocations

Enables tracing: User prompt -> Agent detection -> Tool execution

Task hierarchy extension (OMN-5235): Tracks parent-child dispatch
relationships via a task stack and dispatch metadata registry.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# TTL for task dispatch metadata (1 hour, matches correlation file TTL)
_TASK_DISPATCH_TTL_SECONDS = 3600


class DuplicateTaskError(Exception):
    """Raised when a task_id is pushed that already exists on the stack."""


class CorrelationRegistry:
    """Registry for correlation IDs across hook invocations.

    Extends flat session tracking with a task stack that records
    parent-child dispatch relationships. The task stack is persisted
    alongside the existing correlation state.
    """

    def __init__(
        self,
        state_dir: Path | None = None,
        *,
        emit_fn: Any | None = None,
    ):
        """Initialize correlation manager.

        Args:
            state_dir: Directory for state files (default: $ONEX_STATE_DIR/hooks/.state)
            emit_fn: Optional callable(event_type, payload) for event emission.
                     If None, events are logged but not emitted.
        """
        if state_dir is None:
            from plugins.onex.hooks.lib.onex_state import ensure_state_dir

            state_dir = ensure_state_dir("hooks", ".state")

        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)

        # State file for current session correlation ID
        self.correlation_file = self.state_dir / "correlation_id.json"

        # Injected emit function (avoids circular imports with emit_client_wrapper)
        self._emit_fn = emit_fn

        # Cleanup old state files (older than 1 hour)
        self._cleanup_old_state()

    def _cleanup_old_state(self) -> None:
        """Remove state files older than 1 hour."""
        try:
            if self.correlation_file.exists():
                mtime = self.correlation_file.stat().st_mtime
                age_seconds = time.time() - mtime

                # Remove if older than 1 hour
                if age_seconds > 3600:
                    self.correlation_file.unlink()
        except Exception:
            pass  # Ignore cleanup errors

    def _load_state(self) -> dict[str, Any]:
        """Load persisted state from disk.

        Returns:
            State dict, or empty dict if file missing/corrupt.
        """
        try:
            if self.correlation_file.exists():
                with open(self.correlation_file, encoding="utf-8") as f:
                    result: dict[str, Any] = json.load(f)
                    return result
        except Exception as e:
            logger.warning("Failed to load correlation state: %s", e)
        return {}

    def _save_state(self, state: dict[str, Any]) -> None:
        """Persist state to disk."""
        try:
            with open(self.correlation_file, "w", encoding="utf-8") as f:
                json.dump(state, f)
        except Exception as e:
            logger.warning("Failed to save correlation state: %s", e)

    def _emit_event(self, event_type: str, payload: dict[str, Any]) -> bool:
        """Emit an event through the injected emit function.

        Returns True if emitted, False otherwise. Never raises.
        """
        if self._emit_fn is None:
            logger.debug("No emit_fn configured, event dropped: %s", event_type)
            return False
        try:
            return bool(self._emit_fn(event_type, payload))
        except Exception:
            logger.debug("Event emission failed for %s", event_type, exc_info=True)
            return False

    def _cleanup_expired_dispatches(self, state: dict[str, Any]) -> None:
        """Remove task dispatch records older than TTL.

        Mutates state in place. Does NOT persist -- caller must save.
        """
        dispatches: dict[str, Any] = state.get("task_dispatches", {})
        if not dispatches:
            return

        now = time.time()
        expired = [
            tid
            for tid, meta in dispatches.items()
            if now - meta.get("pushed_at_epoch", 0) > _TASK_DISPATCH_TTL_SECONDS
        ]
        for tid in expired:
            del dispatches[tid]
            # Also remove from stack if somehow still present
            stack: list[str] = state.get("task_stack", [])
            if tid in stack:
                stack.remove(tid)

    # -----------------------------------------------------------------
    # Existing flat correlation API
    # -----------------------------------------------------------------

    def set_correlation_id(
        self,
        correlation_id: str,
        agent_name: str | None = None,
        agent_domain: str | None = None,
        prompt_preview: str | None = None,
    ) -> None:
        """Store correlation ID and context for current session.

        Args:
            correlation_id: Correlation ID from UserPromptSubmit
            agent_name: Detected agent name
            agent_domain: Agent domain
            prompt_preview: First 100 chars of prompt
        """
        existing_state = self._load_state()

        # Increment prompt count
        prompt_count = existing_state.get("prompt_count", 0) + 1

        state = {
            **existing_state,
            "correlation_id": correlation_id,
            "agent_name": agent_name,
            "agent_domain": agent_domain,
            "prompt_preview": prompt_preview,
            "prompt_count": prompt_count,
            "created_at": existing_state.get("created_at")
            or datetime.now(UTC).isoformat(),
            "last_accessed": datetime.now(UTC).isoformat(),
        }

        # Preserve task hierarchy fields
        state.setdefault("task_stack", [])
        state.setdefault("task_dispatches", {})

        self._save_state(state)

    def get_correlation_context(self) -> dict[str, Any] | None:
        """Retrieve current correlation context.

        Returns:
            Dict with correlation_id, agent_name, etc., or None if not found
        """
        try:
            if not self.correlation_file.exists():
                return None

            # Check if file is fresh (< 1 hour old)
            mtime = self.correlation_file.stat().st_mtime
            age_seconds = time.time() - mtime
            if age_seconds > 3600:
                return None

            state = self._load_state()
            if not state:
                return None

            # Update last accessed time
            state["last_accessed"] = datetime.now(UTC).isoformat()
            self._save_state(state)

            return state

        except Exception:
            return None

    def get_correlation_id(self) -> str | None:
        """Get just the correlation ID.

        Returns:
            Correlation ID string or None
        """
        context = self.get_correlation_context()
        return context.get("correlation_id") if context else None

    def clear(self) -> None:
        """Clear stored correlation state."""
        try:
            if self.correlation_file.exists():
                self.correlation_file.unlink()
        except Exception:
            pass

    # -----------------------------------------------------------------
    # Task hierarchy API (OMN-5235)
    # -----------------------------------------------------------------

    @property
    def current_task_id(self) -> str | None:
        """Top of the task stack, or None if empty."""
        state = self._load_state()
        stack: list[str] = state.get("task_stack", [])
        return stack[-1] if stack else None

    @property
    def parent_task_id(self) -> str | None:
        """Second-from-top of the task stack, or None."""
        state = self._load_state()
        stack: list[str] = state.get("task_stack", [])
        return stack[-2] if len(stack) >= 2 else None

    @property
    def task_stack(self) -> list[str]:
        """Current task stack (copy)."""
        state = self._load_state()
        result: list[str] = list(state.get("task_stack", []))
        return result

    @property
    def task_dispatches(self) -> dict[str, dict[str, Any]]:
        """Current task dispatch metadata (copy)."""
        state = self._load_state()
        result: dict[str, dict[str, Any]] = dict(state.get("task_dispatches", {}))
        return result

    def push_task(
        self,
        task_id: str,
        contract_id: str,
        scopes: dict[str, Any] | None = None,
    ) -> None:
        """Push a task onto the stack, recording dispatch metadata.

        Emits ``audit.dispatch.validated`` BEFORE modifying the task stack
        (durability-first: the event survives even if the process crashes
        before the state file is written).

        Args:
            task_id: Unique identifier for the dispatched task.
            contract_id: Contract governing the task.
            scopes: Optional dict of scope constraints (tool_scope,
                     memory_scope, retrieval_sources, etc.).

        Raises:
            DuplicateTaskError: If *task_id* is already on the stack.
        """
        state = self._load_state()

        # Ensure hierarchy fields exist
        stack: list[str] = state.setdefault("task_stack", [])
        dispatches: dict[str, Any] = state.setdefault("task_dispatches", {})

        # Clean up expired dispatches first
        self._cleanup_expired_dispatches(state)

        # Reject duplicate push
        if task_id in stack:
            self._emit_event(
                "audit.scope.violation",
                {
                    "task_id": task_id,
                    "violation": "duplicate_push",
                    "existing_stack": list(stack),
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )
            raise DuplicateTaskError(f"Task {task_id!r} is already on the stack")

        # Build dispatch metadata
        now = datetime.now(UTC)
        parent = stack[-1] if stack else None
        dispatch_meta: dict[str, Any] = {
            "task_id": task_id,
            "parent_task_id": parent,
            "contract_id": contract_id,
            "scopes": scopes or {},
            "pushed_at": now.isoformat(),
            "pushed_at_epoch": time.time(),
            "completed_at": None,
        }

        # Emit BEFORE mutating state (durability first)
        self._emit_event(
            "audit.dispatch.validated",
            {
                "task_id": task_id,
                "parent_task_id": parent,
                "contract_id": contract_id,
                "scopes": scopes or {},
                "timestamp": now.isoformat(),
                "correlation_id": state.get("correlation_id"),
            },
        )

        # Mutate and persist
        stack.append(task_id)
        dispatches[task_id] = dispatch_meta
        self._save_state(state)

    def pop_task(self) -> str | None:
        """Pop the top task from the stack, marking it completed.

        The dispatch metadata is NOT removed -- it stays until TTL
        expiry so that downstream consumers can reconstruct the tree.

        Returns:
            The completed task_id, or None if the stack was empty.
        """
        state = self._load_state()
        stack: list[str] = state.get("task_stack", [])

        if not stack:
            return None

        task_id = stack.pop()

        # Mark completed in dispatch metadata
        dispatches: dict[str, Any] = state.get("task_dispatches", {})
        if task_id in dispatches:
            dispatches[task_id]["completed_at"] = datetime.now(UTC).isoformat()

        self._save_state(state)
        return task_id


# Singleton instance
_registry: CorrelationRegistry | None = None


def get_registry() -> CorrelationRegistry:
    """Get singleton registry instance."""
    global _registry
    if _registry is None:
        _registry = CorrelationRegistry()
    return _registry


# Convenience functions
def set_correlation_id(correlation_id: str, **kwargs: Any) -> None:
    """Store correlation ID for current session."""
    get_registry().set_correlation_id(correlation_id, **kwargs)


def get_correlation_id() -> str | None:
    """Get current correlation ID."""
    return get_registry().get_correlation_id()


def get_correlation_context() -> dict[str, Any] | None:
    """Get full correlation context."""
    return get_registry().get_correlation_context()


def clear_correlation_context() -> None:
    """Clear stored correlation context."""
    get_registry().clear()


if __name__ == "__main__":
    # Test correlation registry
    print("Testing correlation registry...")

    # Set correlation ID
    set_correlation_id(
        "test-correlation-123",
        agent_name="agent-test",
        agent_domain="testing",
        prompt_preview="This is a test prompt",
    )
    print("Correlation ID stored")

    # Retrieve correlation ID
    corr_id = get_correlation_id()
    print(f"Retrieved correlation ID: {corr_id}")

    # Get full context
    context = get_correlation_context()
    print(f"Full context: {json.dumps(context, indent=2)}")

    # Clear
    get_registry().clear()
    print("Cleared correlation state")

    print("\nAll tests passed!")
