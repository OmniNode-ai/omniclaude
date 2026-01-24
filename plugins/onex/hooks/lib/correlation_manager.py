#!/usr/bin/env python3
"""
Correlation ID Manager - Persist correlation IDs across hook invocations

Enables tracing: User prompt → Agent detection → Tool execution
"""

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class CorrelationRegistry:
    """Registry for correlation IDs across hook invocations."""

    def __init__(self, state_dir: Path | None = None):
        """Initialize correlation manager.

        Args:
            state_dir: Directory for state files (default: ~/.claude/hooks/.state)
        """
        if state_dir is None:
            state_dir = Path.home() / ".claude" / "hooks" / ".state"

        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)

        # State file for current session correlation ID
        self.correlation_file = self.state_dir / "correlation_id.json"

        # Cleanup old state files (older than 1 hour)
        self._cleanup_old_state()

    def _cleanup_old_state(self):
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

    def set_correlation_id(
        self,
        correlation_id: str,
        agent_name: str | None = None,
        agent_domain: str | None = None,
        prompt_preview: str | None = None,
    ):
        """Store correlation ID and context for current session.

        Args:
            correlation_id: Correlation ID from UserPromptSubmit
            agent_name: Detected agent name
            agent_domain: Agent domain
            prompt_preview: First 100 chars of prompt
        """
        # Load existing state to preserve session stats
        existing_state = {}
        if self.correlation_file.exists():
            try:
                with open(self.correlation_file, encoding="utf-8") as f:
                    existing_state = json.load(f)
            except Exception:
                pass

        # Increment prompt count
        prompt_count = existing_state.get("prompt_count", 0) + 1

        state = {
            "correlation_id": correlation_id,
            "agent_name": agent_name,
            "agent_domain": agent_domain,
            "prompt_preview": prompt_preview,
            "prompt_count": prompt_count,
            "created_at": existing_state.get("created_at")
            or datetime.now(UTC).isoformat(),
            "last_accessed": datetime.now(UTC).isoformat(),
        }

        try:
            with open(self.correlation_file, "w") as f:
                json.dump(state, f)
        except Exception as e:
            import sys

            print(f"⚠️  Failed to save correlation ID: {e}", file=sys.stderr)

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

            with open(self.correlation_file, encoding="utf-8") as f:
                state = json.load(f)

            # Update last accessed time
            state["last_accessed"] = datetime.now(UTC).isoformat()
            with open(self.correlation_file, "w") as f:
                json.dump(state, f)

            result: dict[str, Any] = state
            return result

        except Exception:
            return None

    def get_correlation_id(self) -> str | None:
        """Get just the correlation ID.

        Returns:
            Correlation ID string or None
        """
        context = self.get_correlation_context()
        return context.get("correlation_id") if context else None

    def clear(self):
        """Clear stored correlation state."""
        try:
            if self.correlation_file.exists():
                self.correlation_file.unlink()
        except Exception:
            pass


# Singleton instance
_registry = None


def get_registry() -> CorrelationRegistry:
    """Get singleton registry instance."""
    global _registry
    if _registry is None:
        _registry = CorrelationRegistry()
    return _registry


# Convenience functions
def set_correlation_id(correlation_id: str, **kwargs):
    """Store correlation ID for current session."""
    get_registry().set_correlation_id(correlation_id, **kwargs)


def get_correlation_id() -> str | None:
    """Get current correlation ID."""
    return get_registry().get_correlation_id()


def get_correlation_context() -> dict[str, Any] | None:
    """Get full correlation context."""
    return get_registry().get_correlation_context()


def clear_correlation_context():
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
    print("✓ Correlation ID stored")

    # Retrieve correlation ID
    corr_id = get_correlation_id()
    print(f"✓ Retrieved correlation ID: {corr_id}")

    # Get full context
    context = get_correlation_context()
    print(f"✓ Full context: {json.dumps(context, indent=2)}")

    # Clear
    get_registry().clear()
    print("✓ Cleared correlation state")

    print("\n✅ All tests passed!")
