"""Claude Code event hooks.

This package contains hooks that respond to Claude Code lifecycle events.
These hooks are designed to be installed at ~/.claude/hooks/ via symlinks
or the setup-symlinks.sh script.

Available Hooks
===============

Shell Hooks
-----------

user-prompt-submit.sh
    Main user prompt processing hook. Handles:
    - Agent detection via event-based routing (Kafka)
    - Correlation ID generation and tracking
    - Manifest injection for agent context
    - Automated workflow detection and dispatch
    - Intelligence requests to event bus
    Triggered: When user submits a prompt

session-start.sh
    Session initialization hook. Handles:
    - Session metadata capture (session_id, project_path)
    - Git branch detection
    - Database logging of session start
    Performance target: <50ms
    Triggered: When Claude Code session starts

session-end.sh
    Session completion hook. Handles:
    - Session statistics aggregation
    - Correlation state cleanup
    - Session end database logging
    Performance target: <50ms
    Triggered: When Claude Code session ends

pre-tool-use-log.sh
    Pre-tool logging hook. Handles:
    - Atomic JSON logging of tool invocations
    - High-precision timestamps with collision-resistant IDs
    - Non-blocking pass-through
    Triggered: Before any tool execution

pre-tool-use-quality.sh
    Pre-tool quality enforcement hook. Handles:
    - Write/Edit/MultiEdit interception and validation
    - Correlation ID tracking
    - Quality enforcer invocation (quality_enforcer.py)
    - Database event logging
    - Kafka logging of tool_call_start events
    Exit codes: 0=success, 2=blocked
    Triggered: Before Write/Edit/MultiEdit tools

post-tool-use-quality.sh
    Post-tool quality enforcement hook. Handles:
    - Auto-fix for naming convention violations
    - Enhanced metrics collection
    - Error detection and logging
    - Kafka logging of tool_call events
    - Agent actions database logging
    Triggered: After Write/Edit tools

stop.sh
    Response completion hook. Handles:
    - Response completion intelligence
    - Multi-tool coordination tracking
    - Performance metrics
    - Agent execution summary banner
    - Correlation state cleanup
    Performance target: <30ms
    Triggered: When response generation stops

Python Hooks
------------

pre_tool_use_permissions.py
    Permission management hook for Claude Code. Features:
    - Destructive command detection (rm, dd, mkfs, etc.)
    - Sensitive path detection (credentials, system files)
    - Safe temp path validation
    - Token bucket rate limiting (optional)
    - Defense-in-depth security patterns

    Security Note: These patterns provide defense-in-depth, NOT a
    security boundary. See docstring for known bypass vectors.

post_tool_use_enforcer.py
    Post-tool quality enforcer. Features:
    - Naming convention validation
    - AST-based auto-correction
    - Pattern tracking via Kafka
    - AI quorum consensus (when enabled)
    - Framework method preservation

Installation
============

These hooks are designed to be symlinked to ~/.claude/hooks/:

    # From repository root
    ./scripts/deploy-claude.sh

Or manually:

    ln -sf /path/to/repo/claude/hooks ~/.claude/hooks

Configuration
=============

Hooks are configured via:
- ~/.claude/settings.json (hook registration)
- ~/.claude/hooks/config.yaml (quality enforcer settings)
- Environment variables (KAFKA_BOOTSTRAP_SERVERS, POSTGRES_*, etc.)

Dependencies
============

Shell hooks require:
- jq (JSON processing)
- python3 (subprocess calls)
- claude/hooks/lib/ (Python utilities - auto-discovered via SCRIPT_DIR)

Python hooks require:
- yaml (configuration loading)
- psycopg2 (database connections)
- kafka-python (event bus integration)

The lib/ directory at claude/hooks/lib/ contains hook-specific utilities
including correlation management, event logging, and pattern tracking.

The lib/ directory at claude/lib/ contains shared utilities for the
entire claude package (core/, utils/, etc.).
"""

# Hook file names for programmatic access
SHELL_HOOKS = [
    "user-prompt-submit.sh",
    "session-start.sh",
    "session-end.sh",
    "pre-tool-use-log.sh",
    "pre-tool-use-quality.sh",
    "post-tool-use-quality.sh",
    "stop.sh",
]

PYTHON_HOOKS = [
    "pre_tool_use_permissions.py",
    "post_tool_use_enforcer.py",
]

ALL_HOOKS = SHELL_HOOKS + PYTHON_HOOKS

__all__ = ["SHELL_HOOKS", "PYTHON_HOOKS", "ALL_HOOKS"]
