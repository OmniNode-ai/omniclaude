# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""TDD tests for OMN-8823: ticket_work canary port to ProtocolProjectTracker DI.

Both tests are designed to FAIL before the prompt.md migration and PASS after.
"""

from pathlib import Path

PROMPT_MD = (
    Path(__file__).parent.parent.parent
    / "plugins"
    / "onex"
    / "skills"
    / "ticket_work"
    / "prompt.md"
)


def test_no_hardcoded_mcp_linear_calls_in_prompt() -> None:
    """Assert that prompt.md contains no hardcoded mcp__linear-server__ call sites.

    Fails before migration (8 sites present), passes after.
    """
    content = PROMPT_MD.read_text()
    violations = [
        line.strip() for line in content.splitlines() if "mcp__linear-server__" in line
    ]
    assert not violations, (
        f"Found {len(violations)} hardcoded mcp__linear-server__ call site(s) in prompt.md:\n"
        + "\n".join(f"  {v}" for v in violations)
    )


def test_tracker_di_pattern_present() -> None:
    """Assert that prompt.md declares the tracker DI pattern.

    Passes when prompt.md references resolve_project_tracker() or tracker.* methods
    or ProtocolProjectTracker, confirming the DI preamble was added.
    """
    content = PROMPT_MD.read_text()
    has_tracker = (
        "tracker." in content
        or "ProtocolProjectTracker" in content
        or "resolve_project_tracker" in content
    )
    assert has_tracker, (
        "prompt.md must reference the tracker DI pattern "
        "('tracker.', 'ProtocolProjectTracker', or 'resolve_project_tracker'). "
        "Add the DI preamble before replacing mcp__linear-server__ call sites."
    )
