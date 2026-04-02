# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Client for querying the Cross-Agent Memory Fabric.

Used by context injection (passive, session start) and the /recall skill (active, on-demand).
Queries the omnimemory agent learning retrieval node via HTTP.
"""

from __future__ import annotations

import os

_DEFAULT_RETRIEVAL_URL = (
    "http://localhost:8085/v1/nodes/node_agent_learning_retrieval_effect/execute"
)
_RETRIEVAL_URL = os.environ.get("AGENT_LEARNING_RETRIEVAL_URL", _DEFAULT_RETRIEVAL_URL)


def format_learnings_markdown(
    learnings: list[dict[str, object]],
    max_display: int = 5,
) -> str:
    """Format retrieved learnings as injectable markdown context.

    Output format:
    ## Recent Agent Learnings
    - [3 days ago] ci_fix: "Fixed by adding --extend-exclude."
    """
    if not learnings:
        return ""

    lines = ["## Recent Agent Learnings", ""]
    for learning in learnings[:max_display]:
        age = learning.get("age_days", "?")
        task_type = learning.get("task_type", "unknown")
        summary = str(learning.get("resolution_summary", "")).strip()
        match_type = learning.get("match_type", "unknown")

        age_str = (
            f"{age} days ago"
            if isinstance(age, int) and age != 1
            else (
                "1 day ago" if age == 1 else "today" if age == 0 else f"{age} days ago"
            )
        )
        confidence_marker = " (exact match)" if match_type == "error_signature" else ""
        lines.append(f'- [{age_str}] {task_type}{confidence_marker}: "{summary}"')

    return "\n".join(lines)
