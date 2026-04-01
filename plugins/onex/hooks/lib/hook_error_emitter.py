# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Emit structured hook error events to Kafka via the emit daemon.

Classifies raw error strings into tier/category and emits via emit_client_wrapper.
Designed for fail-open: never raises, never blocks.

[OMN-7158]
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from datetime import UTC, datetime
from uuid import uuid4

from omniclaude.hooks.schemas import EnumHookErrorCategory, EnumHookErrorTier

_CLASSIFICATION_RULES: list[
    tuple[re.Pattern[str], EnumHookErrorTier, EnumHookErrorCategory]
] = [
    # Tier 1 — Interpreter
    (
        re.compile(r"ImportError:"),
        EnumHookErrorTier.INTERPRETER,
        EnumHookErrorCategory.IMPORT_ERROR,
    ),
    (
        re.compile(r"TypeError:"),
        EnumHookErrorTier.INTERPRETER,
        EnumHookErrorCategory.TYPE_ERROR,
    ),
    (
        re.compile(r"SyntaxError:"),
        EnumHookErrorTier.INTERPRETER,
        EnumHookErrorCategory.SYNTAX_ERROR,
    ),
    # Tier 2 — Degraded
    (
        re.compile(r"Authorization DENIED"),
        EnumHookErrorTier.DEGRADED,
        EnumHookErrorCategory.AUTH_DENIED,
    ),
    (
        re.compile(r"unavailable or failed|classification unavailable"),
        EnumHookErrorTier.DEGRADED,
        EnumHookErrorCategory.FUNCTIONAL_DEGRADATION,
    ),
    (
        re.compile(r"timeout|timed out", re.IGNORECASE),
        EnumHookErrorTier.DEGRADED,
        EnumHookErrorCategory.TIMEOUT,
    ),
    # Tier 3 — Intentional blocks
    (
        re.compile(r"No DoD evidence"),
        EnumHookErrorTier.INTENTIONAL_BLOCK,
        EnumHookErrorCategory.DOD_BLOCK,
    ),
    (
        re.compile(r"BLOCKED:.*~/.claude/|Bash guard"),
        EnumHookErrorTier.INTENTIONAL_BLOCK,
        EnumHookErrorCategory.BASH_BLOCK,
    ),
    (
        re.compile(r"scope.*block|context scope", re.IGNORECASE),
        EnumHookErrorTier.INTENTIONAL_BLOCK,
        EnumHookErrorCategory.SCOPE_BLOCK,
    ),
]


def classify_hook_error(
    error_message: str,
) -> tuple[EnumHookErrorTier, EnumHookErrorCategory]:
    """Classify an error string into tier and category. First-match-wins."""
    for pattern, tier, category in _CLASSIFICATION_RULES:
        if pattern.search(error_message):
            return tier, category
    return EnumHookErrorTier.DEGRADED, EnumHookErrorCategory.FUNCTIONAL_DEGRADATION


def emit_hook_error(
    hook_name: str,
    error_message: str,
    session_id: str,
    python_version: str = "",
    hook_script_path: str = "",
    execution_time_ms: int = 0,
) -> bool:
    """Emit a structured hook error event. Returns True on success. Never raises."""
    try:
        from plugins.onex.hooks.lib.emit_client_wrapper import emit_event

        tier, category = classify_hook_error(error_message)

        # Apply secret redaction before emission
        from omniclaude.hooks.schemas import sanitize_text

        safe_message = sanitize_text(error_message[:1000])

        event_id = str(uuid4())
        raw = f"{hook_name}:{category.value}:{error_message}"
        fingerprint = hashlib.sha256(raw.encode()).hexdigest()[:16]

        payload = {
            "event_id": event_id,
            "hook_name": hook_name,
            "error_tier": tier.value,
            "error_category": category.value,
            "error_message": safe_message,
            "session_id": session_id,
            "python_version": python_version,
            "hook_script_path": "",  # omit local paths from event bus
            "execution_time_ms": execution_time_ms,
            "fingerprint": fingerprint,
            "emitted_at": datetime.now(UTC).isoformat(),
        }
        return emit_event("hook.health.error", payload)
    except Exception:
        return False


def main() -> None:
    """CLI entry point for common.sh temp-file handoff."""
    parser = argparse.ArgumentParser(description="Emit hook error event")
    parser.add_argument("--hook-name", required=True)
    parser.add_argument("--error-file", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--python-version", default="")
    parser.add_argument("--hook-script-path", default="")
    args = parser.parse_args()

    try:
        with open(args.error_file) as f:
            error_message = f.read().strip()
    except OSError:
        sys.exit(0)  # fail-open

    if not error_message:
        sys.exit(0)

    emit_hook_error(
        hook_name=args.hook_name,
        error_message=error_message,
        session_id=args.session_id,
        python_version=args.python_version,
        hook_script_path=args.hook_script_path,
    )


if __name__ == "__main__":
    main()
