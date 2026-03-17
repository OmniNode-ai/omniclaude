# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Sample fixture with deliberate aislop patterns — used to verify grep detection logic."""

# prohibited-patterns
ONEX_EVENT_BUS_TYPE = "inmemory"  # should be flagged CRITICAL

# hardcoded-topics
topic = "onex.evt.omniclaude.something.v1"  # should be flagged ERROR

# compat-shims
_unused_handler = None  # should be flagged WARNING

# empty-impls (in non-stub context)
def process_event() -> None:
    pass  # should be flagged WARNING

# NOT flagged: TODO in a test file (excluded by policy)
